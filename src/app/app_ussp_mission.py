#!/usr/bin/env python3

'''
APP "app_ussp_mission"

Input parameters
1. Mission - the misssion to execute
2. Start WP - where to start

This application
1. Connects to the CRM & USSP
2. Asks for an available drone resource with correct capabilities
3. Read and parse the mission
4. Executes the mission (potentially several routes)
5. Finish the mission by landing at the return location
'''

import argparse
import json
import logging
import sys
import threading
import time
import traceback
import datetime
import copy
import uuid
import math
import zmq

import dss.auxiliaries
import dss.client
import dss.auxiliaries.config

#--------------------------------------------------------------------#

__author__ = 'Lennart Ochel <lennart.ochel@ri.se>, Andreas Gising <andreas.gising@ri.se>, Kristoffer Bergman <kristoffer.bergman@ri.se>, Hanna Müller <hanna.muller@ri.se>, Joel Nordahl'
__version__ = '0.1.0'
__copyright__ = 'Copyright (c) 2022, RISE'
__status__ = 'development'

#--------------------------------------------------------------------#

_logger = logging.getLogger('dss.app_ussp_mission')
_context = zmq.Context()


class Waypoint():
  def __init__(self, lat=0.0, lon=0.0, alt=0.0):
    self.lat = lat
    self.lon = lon
    self.alt = alt
  def set_lla(self, lat, lon, alt):
    self.lat = lat
    self.lon = lon
    self.alt = alt

#--------------------------------------------------------------------#
class AppUsspMission():
  def __init__(self, app_ip, app_id, crm, mission, capabilities, negotiate_routes):
    # Create Client object
    self.drone = dss.client.Client(timeout=2000, exception_handler=None, context=_context)

    # Create CRM object
    self.crm = dss.client.CRM(_context, crm, app_name='app_ussp_mission.py', desc='USSP compatible mission execution', app_id=app_id)

    self._alive = True
    self._dss_data_thread = None
    self._dss_data_thread_active = False
    self._dss_info_thread = None
    self._dss_info_thread_active = False

    self._app_ip = app_ip

    # load mission from file
    with open(mission, encoding='utf-8') as handle:
      self.input_routes = json.load(handle)
      if "source_file" in self.input_routes:
        self.input_routes.pop("source_file")


    for route in self.input_routes.values():
      route['status'] = "pending"
      route['speed'] = 5.0
      if "id0" in route:
        if "speed" in route["id0"]:
          route["speed"] = route["id0"]["speed"]

    self.capabilities = capabilities
    # USSP routes
    self.ussp_routes = []
    #geofence parameters
    self.delta_r_max = dss.auxiliaries.config.config['app_ussp_mission']['delta_r_max']
    self.height_max = dss.auxiliaries.config.config['app_ussp_mission']['height_max']
    self.height_min = dss.auxiliaries.config.config['app_ussp_mission']['height_min']
    self.takeoff_height = 20.0
    #
    self.drone_data = {"pos": Waypoint(), "time": datetime.datetime.utcnow(), "heading": 0.0, "velocity": [0.0, 0.0, 0.0]}
    self.start_pos = Waypoint()
    self.start_pos_received = False
    self.drone_lla_lock = threading.Lock()
    self.uas_id = None
    self.operator_id = dss.auxiliaries.config.config['app_ussp_mission']['operator_id']
    self.clearance_landing = False
    self.plan_withdrawn = False
    self.mission_complete = False

    # The application sockets
    # Use ports depending on subnet used to pass RISE firewall
    # Rep: ANY -> APP
    self._app_socket = dss.auxiliaries.zmq.Rep(_context, label='app', min_port=self.crm.port, max_port=self.crm.port+50)
    # Pub: APP -> ANY
    self._info_socket = dss.auxiliaries.zmq.Pub(_context, label='info', min_port=self.crm.port, max_port=self.crm.port+50)

    # Start the app reply thread
    self._app_reply_thread = threading.Thread(target=self._main_app_reply, daemon=True)
    self._app_reply_thread.start()

    # Supported commands from ANY to APP
    self._commands = {'push_dss':         {'request': self._request_push_dss}, # Not implemented
                      'get_info':         {'request': self._request_get_info},
                      'clearance_landing':{'request': self._request_clearance_landing}}

    # Register with CRM (self.crm.app_id is first available after the register call)
    _ = self.crm.register(self._app_ip, self._app_socket.port)

    # Update socket labels with received id
    self._app_socket.add_id_to_label(self.crm.app_id)
    self._info_socket.add_id_to_label(self.crm.app_id)

    # All nack reasons raises exception, registration is successful
    _logger.info('App %s listening on %s:%s', self.crm.app_id, self._app_socket.ip, self._app_socket.port)
    _logger.info('App registered with CRM: %s', self.crm.app_id)
    #USSP parameters
    self.ussp_ip = dss.auxiliaries.config.config['app_ussp_mission']['ussp_ip']
    self.ussp_req_port = dss.auxiliaries.config.config['app_ussp_mission']['ussp_req_port']
    self.ussp_pub_port = dss.auxiliaries.config.config['app_ussp_mission']['ussp_pub_port']
    self.ussp_sub_port = dss.auxiliaries.config.config['app_ussp_mission']['ussp_sub_port']
    _logger.info(f'App connecting to USSP: {self.ussp_ip}')
    self.ussp = dss.client.UsspClientLib(app_id, _context)
    self.ussp.connect(self.ussp_ip, self.ussp_req_port, self.ussp_pub_port, self.ussp_sub_port)
    self.ussp_alt_diff = None
    self.application_state = "idle"
    self.authorized_plans = {}
    self.negotiate_routes = negotiate_routes




#--------------------------------------------------------------------#
  @property
  def alive(self):
    '''checks if application is alive'''
    return self._alive

#--------------------------------------------------------------------#
  # This method runs on KeyBoardInterrupt, time to release resources and clean up.
  # Disconnect connected drones and unregister from crm, close ports etc..
  def kill(self):
    _logger.info("Closing down...")
    self._alive = False
    # Kill info and data thread
    self._dss_info_thread_active = False
    self._dss_data_thread_active = False

    # Unregister APP from CRM
    _logger.info("Unregister from CRM")
    answer = self.crm.unregister()
    if not dss.auxiliaries.zmq.is_ack(answer):
      _logger.error('Unregister failed: {answer}')
    _logger.info("CRM socket closed")

    # Disconnect drone if drone is alive
    if self.drone.alive:
      #wait until other DSS threads finished
      time.sleep(0.5)
      _logger.info("Closing socket to DSS")
      self.drone.close_dss_socket()

    _logger.debug('~ THE END ~')

#--------------------------------------------------------------------#
# Application reply thread
  def _main_app_reply(self):
    _logger.info('Reply socket is listening on: %s', self._app_socket.port)
    while self.alive:
      try:
        msg = self._app_socket.recv_json()
        msg = json.loads(msg)
        fcn = msg['fcn'] if 'fcn' in msg else ''

        if fcn in self._commands:
          request = self._commands[fcn]['request']
          answer = request(msg)
        else:
          answer = dss.auxiliaries.zmq.nack(msg['fcn'], 'Request not supported')
        answer = json.dumps(answer)
        self._app_socket.send_json(answer)
      except:
        pass
    self._app_socket.close()
    _logger.info("Reply socket closed, thread exit")

#--------------------------------------------------------------------#
# Application reply: 'push_dss'
  def _request_push_dss(self, msg):
    answer = dss.auxiliaries.zmq.nack(msg['fcn'], 'Not implemented')
    return answer

#--------------------------------------------------------------------#
# Application reply: 'get_info'
  def _request_get_info(self, msg):
    answer = dss.auxiliaries.zmq.ack(msg['fcn'])
    answer['id'] = self.crm.app_id
    answer['info_pub_port'] = self._info_socket.port
    answer['data_pub_port'] = None
    return answer
#--------------------------------------------------------------------#
# Application reply: 'clearance_landing'
  def _request_clearance_landing(self, msg):
    self.clearance_landing = True
    answer = dss.auxiliaries.zmq.ack(msg['fcn'])
    return answer

#--------------------------------------------------------------------#
  # Setup the DSS info stream thread
  def setup_dss_info_stream(self):
    #Get info port from DSS
    info_port = self.drone.get_port('info_pub_port')
    if info_port:
      self._dss_info_thread = threading.Thread(
        target=self._main_info_dss, args=[self.drone._dss.ip, info_port])
      self._dss_info_thread_active = True
      self._dss_info_thread.start()

#--------------------------------------------------------------------#
  # The main function for subscribing to info messages from the DSS.
  def _main_info_dss(self, ip, port):
    # Enable streams
    self.drone.enable_data_stream('LLA')
    #self.drone.enable_data_stream('battery')
    # Create info socket and start listening thread
    info_socket = dss.auxiliaries.zmq.Sub(_context, ip, port, "info " + self.crm.app_id)
    while self._dss_info_thread_active:
      try:
        (topic, msg) = info_socket.recv()
        if topic == "LLA":
          self.drone_lla_lock.acquire()
          self.drone_data["time"] = datetime.datetime.utcnow()
          self.drone_data["pos"].set_lla(msg['lat'], msg['lon'], msg['alt'])
          self.drone_data["heading"] = msg['heading']
          if "velocity" in msg:
            self.drone_data["velocity"] = msg['velocity']
          self.drone_lla_lock.release()
          if not self.start_pos_received:
            self.start_pos.set_lla(msg['lat'], msg['lon'], msg['alt'])
            self.start_pos_received = True
            #Calculate diff in altitude compared to USSP
            self.ussp_alt_diff = self.ussp.query_ground_height(self.start_pos.lat, self.start_pos.lon) - self.start_pos.alt
            _logger.info(f"Start position received, altitude difference: {self.ussp_alt_diff}")
        elif topic == 'battery':
          _logger.debug("Not implemented yet...")
        else:
          _logger.warning("Topic not recognized on info link: %s", topic)
      except:
        pass
    info_socket.close()
    _logger.info("Stopped thread and closed info socket")

  def _stream_nrid(self):
    #Initialize NRID message
    self.ussp.initialize_nrid_msg(self.operator_id, self.uas_id)
    # Assume operator at initial point
    #self.ussp.update_nrid_operator_location(self.uas_id, self.start_pos.lat, self.start_pos.lon)
    # Set accuracies
    self.ussp.update_nrid_accuracies(self.uas_id, t_acc=4, alt_acc=4, h_acc=11, speed_acc=0)
    # Wait for the altitude diff to be received
    while self.ussp_alt_diff is None:
      time.sleep(0.5)
    while self.alive:
      self.drone_lla_lock.acquire()
      drone_data = self.drone_data
      self.drone_lla_lock.release()
      speed=0
      if "velocity" in drone_data:
        speed = math.sqrt(drone_data['velocity'][0]**2 + drone_data['velocity'][1]**2)
      if speed > 0.1:
        bearing = (180/math.pi)*math.atan2(drone_data['velocity'][1], drone_data['velocity'][0])
      else:
        bearing = drone_data['heading']
      height = self.drone_data["pos"].alt-self.start_pos.alt
      self.ussp.update_nrid_state(self.uas_id, drone_data["time"], drone_data["pos"].lat, drone_data["pos"].lon, drone_data["pos"].alt+self.ussp_alt_diff, height=height, bearing=bearing, speed=speed, vert_speed=drone_data['velocity'][2])
      self.ussp.publish_nrid_msg(self.uas_id)
      time.sleep(1.0)

  def _ussp_subscriber_thread(self):
    self.ussp.subscribe_to_topic(self.uas_id)
    while self.alive:
      try:
        (_, msg) = self.ussp.receive_subscribe_data()
        if "message" in msg and "plan ID" in msg:
          if msg["message"] == "plan withdrawn" and msg["plan ID"] in self.authorized_plans:
            _logger.warning(f"Plan withdrawn received from the USSP for plan {msg['plan ID']}. Trying to replan!")
            self.plan_withdrawn = True
            self.drone.app_abort = True
          else:
            _logger.info("Plan withdrawn from already ended plan received, ignoring..")
      except:
        pass

  def update_input_routes(self):
    old_input_routes = copy.deepcopy(self.input_routes)
    self.input_routes = {}
    for route in self.ussp_routes:
      #Cancel pending routes and add to input route list
      if route["status"] == "pending":
        self.ussp.cancel_plan(route["plan ID"])
        self.input_routes[route["type"]] = old_input_routes[route["type"]]
      #Add all waypoints associated to a route that is not ended
      elif route["status"] == "running":
        #Find what waypoints that should be kept in the plan (not visited yet)
        new_input_route = {}
        old_input_route = old_input_routes[route["type"]]
        current_wp = 0
        for wp_name, wp in old_input_route.items():
          if current_wp < self.wp_in_old_list:
            current_wp += 1
          else:
            new_input_route[wp_name] = wp
        new_input_route["status"] = "running"
        self.input_routes[route["type"]] = new_input_route
    #Reset routes list and plan withdrawn flag
    self.plan_withdrawn = False
    self.ussp_routes = []
  # Generate routes based on input, without negotiating with USSP
  def generate_routes(self):
    takeoff_time = datetime.datetime.utcnow() + datetime.timedelta(seconds=20)
    for route_type, route in self.input_routes.items():
      # Use mission as it is.
      route_wps = {}
      for wp_name, wp in route.items():
        if "id" in wp_name:
          route_wps[wp_name] = wp
      route_final = {}
      route_final["route_wps"] = route_wps
      route_final["takeoff_time"] = takeoff_time
      route_final["type"] = route_type
      route_final["status"] = route["status"]
      route_final["takeoff_height"] = self.takeoff_height
      self.ussp_routes.append(route_final)
      takeoff_time = takeoff_time + datetime.timedelta(minutes=1)
  # Generate routes based on positions to visit
  def generate_ussp_routes(self):
    # Request flight authorizations from the USSP. Expects altitude as height over ground
    takeoff_time = datetime.datetime.utcnow() + datetime.timedelta(seconds=40)
    current_position = copy.deepcopy(self.drone_data["pos"])
    current_position.alt += self.ussp_alt_diff
    self.authorized_plans = {}
    for route_type, route in self.input_routes.items():
      input_positions = [current_position]
      #Add takeoff waypoint to USSP if mission is pending
      if route["status"] == "pending":
         takeoff_position = copy.deepcopy(current_position)
         takeoff_position.alt += self.takeoff_height
         input_positions.append(takeoff_position)

      for wp_name, wp in route.items():
        if "id" in wp_name:
          #compensate for altitude diff
          alt = wp['alt'] + self.ussp_alt_diff
          #Transform relative to AMSL?
          if wp["alt_type"] == 'relative':
            alt += self.start_pos.alt

          input_positions.append(Waypoint(wp["lat"], wp["lon"], alt) )
      #Add waypoint on the ground
      landing_position = copy.deepcopy(input_positions[-1])
      landing_position.alt = self.ussp.query_ground_height(landing_position.lat, landing_position.lon)
      input_positions.append(landing_position)
      if route["status"] == 'running':
        takeoff_time = datetime.datetime.utcnow() + datetime.timedelta(seconds=20)
      (plan_id, delay) = self.ussp.request_plan(self.operator_id, self.uas_id, epsg=4979, use_altitude=True, positions=input_positions, takeoff_time=takeoff_time, speed=route['speed'], max_speed=7.0, ascend_rate=2.0, descend_rate=1.0)
      if plan_id is None or delay is None:
        raise dss.auxiliaries.exception.Error
      _logger.info(f"request plan sent, sleeping for {delay} seconds")
      time.sleep(delay)
      (status, plan) = self.ussp.get_plan(plan_id)
      _logger.info(f"status from get plan: {status} for {plan_id}")
      if status != "authorized":
        raise dss.auxiliaries.exception.Error
      #Accept plan
      self.authorized_plans[plan_id] = True
      if not self.ussp.accept_plan(plan_id):
        raise dss.auxiliaries.exception.Error
      #Convert to internal representation
      route_wps = self.ussp.transform_plan(plan, use_altitude=True, ussp_alt_diff=self.ussp_alt_diff)
      #save route
      route_ussp = {}
      route_ussp["route_wps"] = route_wps
      route_ussp["transform_current_wp"] = self.map_input_to_ussp_wps(route, route_wps)
      route_ussp["takeoff_time"] = datetime.datetime.fromisoformat(plan[0]["time"])
      route_ussp["plan ID"] = plan_id
      route_ussp["type"] = route_type
      route_ussp["status"] = route["status"]
      if route_ussp["status"] == "pending":
        route_ussp["takeoff_height"] = min(plan[1]["position"][2] - plan[0]["position"][2], 30.0)
        _logger.info(f"takeoff_height: {route_ussp['takeoff_height']}")
      print(f"takeoff_time requested: {takeoff_time}, takeoff from USSP: {route_ussp['takeoff_time']}")
      landing_time = datetime.datetime.fromisoformat(plan[-1]["time"])
      route_ussp["landing_time"] = landing_time
      self.ussp_routes.append(route_ussp)
      #Update takeoff time
      current_position = Waypoint(input_positions[-1].lat, input_positions[-1].lon, input_positions[-1].alt)
      takeoff_time = landing_time + datetime.timedelta(seconds=plan[-1]["time margin"]) + datetime.timedelta(seconds=10)

  @staticmethod
  def map_input_to_ussp_wps(route, ussp_route_wps):
    input_mapper = []
    for ussp_wp in ussp_route_wps.values():
      wp_mapped = 0
      for wp_name, wp in route.items():
        if "id" in wp_name:
          if abs(wp["lat"]-ussp_wp["lat"]) < 1e-6 and abs(wp["lon"] - ussp_wp["lon"]) < 1e-6:
            break
          wp_mapped += 1
      input_mapper.append(wp_mapped)
    return input_mapper

#------------------------TASKS----------------------------------------#
  def connect_to_drone(self, capabilities):
    drone_received = False
    while self.alive and not drone_received:
      # Get a drone
      answer = self.crm.get_drone(capabilities=capabilities)
      if dss.auxiliaries.zmq.is_nack(answer):
        _logger.info(f"No drone with {capabilities} available - sleeping for 2 seconds")
        time.sleep(2.0)
      else:
        drone_received = True

    # Connect to the drone, set app_id in socket
    self.drone.connect(answer['ip'], answer['port'], app_id=self.crm.app_id)
    _logger.info("Connected as owner of drone: [%s]", self.drone._dss.dss_id)

    # Setup info stream to DSS
    self.setup_dss_info_stream()
    _logger.info("Setup dss info stream")

    self.uas_id = str(uuid.uuid1())

  def initialize_waypoints(self, waypoints, reset_geofence=True):
    self.drone.try_set_init_point()
    if reset_geofence:
      self.drone.set_geofence(self.height_min, self.height_max, self.delta_r_max)
    self.drone.upload_mission_LLA(waypoints)

  def launch_drone(self, takeoff_height, reset_dss_srtl=True):
    self.drone.await_controls()
    self.drone.arm_and_takeoff(takeoff_height)
    if reset_dss_srtl:
      self.drone.reset_dss_srtl()

  def await_clearance_landing(self):
    #TODO Set to false when being implemented
    self.clearance_landing = True
    while not self.clearance_landing:
      self.drone.raise_if_aborted()
      time.sleep(1.0)

  def fly_waypoints(self):
    start_wp = 0
    while True:
      try:
        self.drone.fly_waypoints(start_wp)
      except dss.auxiliaries.exception.Nack as nack:
        if nack.msg == 'State is not flying':
          _logger.info("Pilot has landed")
          break
        elif nack.msg == 'Task not prioritized':
          _logger.warning("Another task with higher priority is being executed by DSS, sleeping for 1 second")
          time.sleep(1.0)
        else:
          _logger.info("Fly route was nacked %s", nack.msg)
          break
      except dss.auxiliaries.exception.AbortTask:
        if self.plan_withdrawn:
          #USSP plan withdrawn received - need to replan!
          break
        # Otherwise - PILOT took controls
        (current_wp, _) = self.drone.get_currentWP()
        # Prepare to continue the route
        start_wp = current_wp
        _logger.info("Pilot took controls, awaiting PILOT action")
        self.drone.await_controls()
        _logger.info("PILOT gave back controls")
        # Try to continue route
        continue
      else:
        # route is completed
        break
  def check_action(self, phase, route_type):
    if phase == "pre takeoff":
      if route_type == 'drop off':
        #Make sure that the package is loaded
        self.drone.load_package()
    elif phase == "post takeoff":
      if route_type == 'camera route':
        self.drone.set_gimbal(0,90,0)
    elif phase == "pre land":
      if route_type == 'camera route':
        self.drone.set_gimbal(0,0,0)
      elif route_type == 'first responder':
        #Hover above the Object of interest for 90 seconds
        start_time = datetime.datetime.utcnow()
        hover_time = 60
        while datetime.datetime.utcnow() < start_time + datetime.timedelta(seconds=hover_time) :
          _logger.info(f"Hovering above object, time remaining: {start_time + datetime.timedelta(seconds=hover_time) - datetime.datetime.utcnow()}")
          time.sleep(1.0)
    elif phase == "landed":
      if route_type == "drop off":
        self.drone.unload_package()
      elif route_type == "pickup":
        self.drone.load_package()
      else:
        self.application_state = "idle"
        self.mission_complete = True
#--------------------------------------------------------------------#
# Main function
  def main(self):
    self.connect_to_drone(self.capabilities)
    # Start USSP subscriber thread
    ussp_sub_thread = threading.Thread(target=self._ussp_subscriber_thread, daemon=True)
    ussp_sub_thread.start()
    #Reset DSS SRTL and geofence only once
    reset_dss_srtl = True
    reset_geofence = True
    while self.alive and self.ussp_alt_diff is None:
      _logger.info("Waiting for the drone to stream its current position")
      time.sleep(0.5)
    # Start streaming NRID
    nrid_thread = threading.Thread(target=self._stream_nrid, daemon=True)
    nrid_thread.start()
    self.application_state = "planning"
    while not self.mission_complete:
      # Generate USSP routes
      if self.negotiate_routes:
        self.generate_ussp_routes()
      else:
        self.generate_routes()
      self.application_state = "executing"
      for route in self.ussp_routes:
        self.initialize_waypoints(route["route_wps"], reset_geofence)
        # Only update geofence once
        reset_geofence = False
        #Wait for takeoff time
        while datetime.datetime.utcnow() + datetime.timedelta(seconds=10) < route["takeoff_time"]:
          _logger.info(f"Waiting to start route execution, time remaining: {route['takeoff_time']-datetime.datetime.utcnow()-datetime.timedelta(seconds=10)}")
          time.sleep(1)
        # check action and activate route
        self.drone.await_controls()
        self.check_action("pre takeoff", route["type"])
        if self.negotiate_routes:
          self.ussp.activate_plan(route["plan ID"])
        # Launch drone
        if route["status"] == "pending":
          self.launch_drone(route["takeoff_height"], reset_dss_srtl)
          #Only reset dss srtl once
          reset_dss_srtl = False
        # Fly to waypoints
        if not self.plan_withdrawn:
          #Check if any action post takeoff before flying waypoints
          self.check_action("post takeoff", route["type"])
          self.fly_waypoints()
        if self.plan_withdrawn:
          #Make the drone hover
          self.drone.set_vel_BODY(0,0,0,0)
          route["status"] = "running"
          self.application_state = "planning"
          (current_wp, _) = self.drone.get_currentWP()
          self.wp_in_old_list = route["transform_current_wp"][current_wp]
          self.update_input_routes()
          break
        #wait for reaching waypoint
        time.sleep(1.0)
        #Await landing clearance?
        self.await_clearance_landing()
        #Land
        self.check_action("pre land", route["type"])
        if route["type"] == "first responder":
          self.drone.dss_srtl(hover_time=5.0)
        else:
          self.drone.land()
          _logger.info(f"Landed at time: {datetime.datetime.utcnow()}, USSP landing time: {route['landing_time']}")
        # End plan
        if self.negotiate_routes:
          self.ussp.end_plan(route["plan ID"])
          self.authorized_plans.pop(route["plan ID"])
        route["status"] = "ended"
        #Check if plan withdrawn during landing
        if self.plan_withdrawn:
          self.application_state == "planning"
          self.update_input_routes()
        # Check landing action depending on route type
        self.drone.await_controls()
        self.check_action("landed", route["type"])




#--------------------------------------------------------------------#
def _main():
  # parse command-line arguments
  parser = argparse.ArgumentParser(description='APP "app_ussp_mission"', allow_abbrev=False, add_help=False)
  parser.add_argument('-h', '--help', action='help', help=argparse.SUPPRESS)
  parser.add_argument('--app_ip', type=str, help='ip of the app', required=True)
  parser.add_argument('--id', type=str, default=None, help='id of this app_noise instance if started by crm')
  parser.add_argument('--crm', type=str, help='<ip>:<port> of crm', required=True)
  parser.add_argument('--log', type=str, default='debug', help='logging threshold')
  parser.add_argument('--owner', type=str, help='id of the instance controlling app_noise - not used in this use case')
  parser.add_argument('--stdout', action='store_true', help='enables logging to stdout')
  parser.add_argument('--mission', type=str, required=True)
  parser.add_argument('--without-negotiation', action='store_true', help='Disables the route negotiation step with the USSP', required=False)
  parser.add_argument('--capabilities', type=str, default=None, nargs='*', help='If any specific capability is required')
  args = parser.parse_args()

  # Identify subnet to sort log files in structure
  subnet = dss.auxiliaries.zmq.get_subnet(ip=args.app_ip)
  # Initiate log file
  dss.auxiliaries.logging.configure('app_ussp_mission', stdout=args.stdout, rotating=True, loglevel=args.log, subdir=subnet)
  # Create the AppUsspMission class
  try:
    app = AppUsspMission(args.app_ip, args.id, args.crm, args.mission, args.capabilities, negotiate_routes=not args.without_negotiation)
  except dss.auxiliaries.exception.NoAnswer:
    _logger.error('Failed to instantiate application: Probably the CRM couldn\'t be reached')
    sys.exit()
  except:
    _logger.error('Failed to instantiate application\n%s', traceback.format_exc())
    sys.exit()

  # Try to setup objects and initial sockets
  try:
    # Try to run main
    app.main()
  except KeyboardInterrupt:
    print('', end='\r')
    _logger.warning('Shutdown due to keyboard interrupt')
  except dss.auxiliaries.exception.Nack as error:
    _logger.error(f'Nacked when sending {error.fcn}, received error: {error.msg}')
  except dss.auxiliaries.exception.NoAnswer as error:
    _logger.error(f'NoAnswer when sending: {error.fcn} to {error.ip}:{error.port}')
  except:
    _logger.error(f'unexpected exception\n{traceback.format_exc()}')

  try:
    app.kill()
  except:
    _logger.error(f'unexpected exception\n{traceback.format_exc()}')


#--------------------------------------------------------------------#
if __name__ == '__main__':
  _main()
