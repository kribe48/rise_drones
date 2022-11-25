#!/usr/bin/env python3

'''
APP "app_skara"

This app is used to follow a cyclist. It can be configured to use one or two drones. It exposes the "follow me" interface where an application can request to be followed
'''

import argparse
from distutils.log import info
import json
import logging
import sys
import threading
import time
import traceback
import copy
import queue

import zmq

import dss.auxiliaries
import dss.client
import dss.auxiliaries.config

#--------------------------------------------------------------------#

__author__ = 'Andreas Gising <andreas.gising@ri.se>, Kristoffer Bergman <kristoffer.bergman@ri.se>'
__version__ = '0.2.0'
__copyright__ = 'Copyright (c) 2022, RISE'
__status__ = 'development'

#--------------------------------------------------------------------#

_logger = logging.getLogger('dss.app_skara')
_context = zmq.Context()

#--------------------------------------------------------------------#
# App skara- README.
# This application is used to follow a cyclist using one or two drones.
# Input parameters are
# 1. n_drones : The number of drones to use
# 2. road: The json-file containing the positions that define the road

#
# The application to connect to crm and await a "follow_her" command
# Quit application by calling kill() or Ctrl+C
#
# #--------------------------------------------------------------------#

class AppSkara():
  # Init
  def __init__(self, app_ip, app_id, crm, road, n_drones, owner):
    # Create CRM object
    self.crm = dss.client.CRM(_context, crm, app_name='app_skara.py', desc='SkarApp for following cyclist', app_id=app_id)

    self._alive = True
    self._dss_data_thread = None
    self._dss_data_thread_active = False
    self._dss_info_thread = None
    self._dss_info_thread_active = False

    # Set the owner, it shall be the process who launched the app
    self._owner = owner
    self._app_ip = app_ip
    self.drone_data = {}
    # The application sockets
    # Use ports depending on subnet used to pass RISE firewall
    # Rep: ANY -> APP
    self._app_socket = dss.auxiliaries.zmq.Rep(_context, label='app', min_port=self.crm.port, max_port=self.crm.port+50)
    # Pub: APP -> ANY
    self._info_socket = dss.auxiliaries.zmq.Pub(_context, label='info', min_port=self.crm.port, max_port=self.crm.port+50)

    # Start the app reply thread
    self._last_msg_received = time.time()
    self._app_reply_thread = threading.Thread(target=self._main_app_reply, daemon=True)
    self._app_reply_thread.start()

    # Register with CRM (self.crm.app_id is first available after the register call)
    answer = self.crm.register(self._app_ip, self._app_socket.port)
    self._app_id = answer['id']

    #Background thread, used to send zmq commands to the drones without blocking LLA subscribers
    self.background_task_queue = queue.SimpleQueue()
    self._background_task_thread = threading.Thread(target=self._background_task_executor)
    self._background_task_thread.start()

    #Threads
    self._her_lla_subscriber = None
    self._her_lla_data = None
    self._her_last_msg_received = time.time()
    self._her_lla_time_threshold = 3.0
    self.her_lla_thread = threading.Thread(target=self._her_lla_listener, daemon=True)
    self.her_lla_thread.start()
    # Create a dummy drones object
    self.drones = {}
    self.lla_publishers = {}
    self.lla_threads = {}
    self.spotlight_enabled = {}
    self.lla_publishers_timing = {}
    self.road = road

    self._follow_her_enabled = False

    #Compute the heading reference for the cyclist in "Leaving" state
    self.road_heading = dss.auxiliaries.math.compute_bearing(self.road['id0'], self.road['id1'])
    self.road_length = dss.auxiliaries.math.distance_2D(self.road['id0'], self.road['id1'])
    self.cyclist_point = Point(self.road_heading, self.road_length)
     # Create roles involved depending on number of drones that should be used
    if n_drones == 1:
      self.roles = ["Above"]
    else:
      self.roles = ["Above", "Ahead"]
    #Read parameters
    self.ahead_distance = dss.auxiliaries.config.config['app_skara']['ahead_distance']
    self.pattern_rel_alt = dss.auxiliaries.config.config['app_skara']['pattern_rel_alt']
    self.ahead_rel_alt_diff = dss.auxiliaries.config.config['app_skara']['ahead_rel_alt_diff']
    self.geofence_height_min = dss.auxiliaries.config.config['app_skara']['geofence_height_min']
    self.geofence_height_max = dss.auxiliaries.config.config['app_skara']['geofence_height_max']
    self.geofence_radius = dss.auxiliaries.config.config['app_skara']['geofence_radius']
    self.takeoff_height = dss.auxiliaries.config.config['app_skara']['takeoff_height']
    self.spotlight_switch_distance = dss.auxiliaries.config.config['app_skara']['spotlight_switch_distance']
    for role in self.roles:
      self.drones[role] = dss.client.Client(timeout=2000, exception_handler=None, context=_context)
      self.spotlight_enabled[role] = False
      self.lla_publishers[role] = dss.auxiliaries.zmq.Pub(_context, label='LLA-'+role, min_port=self.crm.port, max_port=self.crm.port+50)
      #Setup a "modified" LLA-stream thread based on the role of the drone
      self.lla_publishers_timing[role] = time.time()
      self.lla_threads[role] = threading.Thread(target=self._her_lla_publisher, args=(role,))
      self.lla_threads[role].start()
    #Above drone subscriber
    self._above_drone_lla_subscriber = None
    self._above_drone_lla_data = None
    self._above_drone_lla_thread = threading.Thread(target=self._above_drone_lla_listener)
    self._above_drone_lla_thread.start()

    self.her_id = 'none'
    self.her = None

    # Data thread locks
    self._above_data_lock = threading.Lock()
    self._her_data_lock = threading.Lock()
    # All nack reasons raises exception, registration is successful
    _logger.info('App %s listening on %s:%d', self.crm.app_id, self._app_socket.ip, self._app_socket.port)
    _logger.info(f'App_skara registered with CRM: {self.crm.app_id}')

    # Update socket labels with received id
    self._app_socket.add_id_to_label(self.crm.app_id)
    self._info_socket.add_id_to_label(self.crm.app_id)
    # start task thread
    self._main_task_thread = threading.Thread(target=self._main_task, daemon=True)
    # create initial task
    self._task_msg = {'fcn': ''}
    self._task_event = threading.Event()

    # Supported commands from ANY to APP
    self._commands = {'follow_her':   {'request': self._request_follow_her, 'task': self._follow_her},
                      'get_info':     {'request': self._request_get_info, 'task': None},
                      'heart_beat':   {'request': self._request_heart_beat, 'task': None}}

#--------------------------------------------------------------------#
  @property
  def alive(self):
    '''checks if application is alive'''
    return self._alive
  @alive.setter
  def alive(self, value):
    self._alive = value
  @property
  def app_id(self):
    '''application id'''
    return self._app_id

#--------------------------------------------------------------------#
# This method runs on KeyBoardInterrupt, time to release resources and clean up.
# Disconnect connected drones and unregister from crm, close ports etc..
  def kill(self):
    _logger.info("Closing down...")
    self.alive = False
    # Kill info and data thread
    self._dss_info_thread_active = False
    self._dss_data_thread_active = False
    self._info_socket.close()
    #Join threads
    self._task_event.set()
    self._above_drone_lla_thread.join(timeout=1.0)
    self._background_task_thread.join(timeout=1.0)
    self.her_lla_thread.join(timeout=1.0)
    self._app_reply_thread.join(timeout=1.0)
    # Unregister APP from CRM
    _logger.info("Unregister from CRM")
    answer = self.crm.unregister()
    if not dss.auxiliaries.zmq.is_ack(answer):
      _logger.error('Unregister failed: {answer}')
    _logger.info("CRM socket closed")

    # join threads and disconnect drone if drone is alive
    for role, drone in self.drones.items():
      self.lla_threads[role].join(timeout=1.0)
      if drone.alive:
        #wait until other DSS threads finished
        time.sleep(0.5)
        _logger.info("Closing socket to DSS")
        drone.close_dss_socket()
    _logger.debug('~ THE END ~')

#--------------------------------------------------------------------#
# Ack nack helper
	# Is message from owner?
  def from_owner(self, msg) -> bool:
    return msg['id'] == self._owner

  # Function to handle if the link to the application is lost
  def _is_link_lost(self):
    link_lost = False
    curr_time = time.time()
    t_link_lost = 10.0
    t_diff = curr_time - self._last_msg_received
    if 0.5*t_link_lost < t_diff < t_link_lost:
      _logger.warning("Application link degraded")
    elif t_diff >= t_link_lost:
      _logger.error("Application is disconnected")
      link_lost = True
    return link_lost

  def _background_task_executor(self):
    while self.alive:
      try:
        msg = self.background_task_queue.get(timeout=1)
      except queue.Empty:
        continue
      role, task, argument = msg.split(maxsplit=2)
      if task == 'spotlight':
        if argument == "enable" and not self.spotlight_enabled[role]:
          try:
            self.drones[role].enable_spotlight(brightness=100)
            self.spotlight_enabled[role] = True
          except dss.auxiliaries.exception.Nack as error:
            _logger.error(f'Nacked when sending {error.fcn}, received error: {error.msg}')
            #Wait a while before sending again
            time.sleep(0.5)
        elif argument == 'disable' and self.spotlight_enabled[role]:
          try:
            self.drones[role].disable_spotlight()
            self.spotlight_enabled[role] = False
          except dss.auxiliaries.exception.Nack as error:
            _logger.error(f'Nacked when sending {error.fcn}, received error: {error.msg}')
            #Wait a while before sending again
            time.sleep(0.5)
      elif task == 'pattern':
        if role == 'all':
          roles = self.drones.keys()
        else:
          roles = [role]
        try:
          for name in roles:
            self.drones[name].set_pattern_above(rel_alt=self.pattern_rel_alt, heading=float(argument))
        except dss.auxiliaries.exception.Nack as error:
          _logger.error(f'Nacked when sending {error.fcn}, received error: {error.msg}')
    _logger.info('Background task executor, thread exit')



#--------------------------------------------------------------------#
# Application reply thread
  def _main_app_reply(self):
    while self.alive:
      try:
        msg = self._app_socket.recv_json()
        msg = json.loads(msg)
        fcn = msg['fcn'] if 'fcn' in msg else ''
        if self.from_owner(msg):
          self._last_msg_received = time.time()
        if fcn in self._commands:
          request = self._commands[fcn]['request']
          answer = request(msg)
        else:
          answer = dss.auxiliaries.zmq.nack(msg['fcn'], 'Request not supported')
        is_ack = dss.auxiliaries.zmq.is_ack(answer)
        if is_ack and self._commands[fcn]['task'] is not None:
          self._task_msg = msg
          self._task_event.set()
        answer = json.dumps(answer)
        self._app_socket.send_json(answer)
      except:
        if self._is_link_lost() and not self._task_event.is_set():
          self.alive = False

    self._app_socket.close()
    _logger.info("Reply socket closed, thread exit")

  def _get_info_port(self, req_socket: dss.auxiliaries.zmq.Req):
    call = 'get_info'
    # build message
    msg = {'fcn': call, 'id': self.app_id}
    # send and receive message
    answer = req_socket.send_and_receive(msg)
    # handle nack
    if not dss.auxiliaries.zmq.is_ack(answer, call):
      raise dss.auxiliaries.exception.Nack(dss.auxiliaries.zmq.get_nack_reason(answer), fcn=call)
    if not 'info_pub_port' in answer:
      raise dss.auxiliaries.exception.Error('info pub port not provided')
    return answer['info_pub_port']

  def setup_her_lla_subscriber(self):
    if 'dss' in self.her_id:
      drone = dss.client.Client(timeout=2000, exception_handler=None, context=_context)
      drone.connect_as_guest(self.her['ip'], self.her['port'], app_id=self.app_id)
      drone.enable_data_stream('LLA')
      info_pub_port = drone.get_port('info_pub_port')
    else:
      #Request socket to another application (assumed LLA stream already started)
      req_socket = dss.auxiliaries.zmq.Req(_context, self.her['ip'], self.her['port'], label='her-req', timeout=2000)
      info_pub_port = self._get_info_port(req_socket)
    self._her_lla_subscriber = dss.auxiliaries.zmq.Sub(_context, self.her['ip'], info_pub_port, "her-info")

  def _above_drone_lla_listener(self):
    while self.alive:
      if self._above_drone_lla_subscriber is not None:
        try:
          (topic, msg) = self._above_drone_lla_subscriber.recv()
          if topic == "LLA":
            self._above_data_lock.acquire()
            self._above_drone_lla_data = msg
            self._above_data_lock.release()
        except:
          pass
    _logger.info("Above drone LLA listener, thread exit")

  def _her_lla_listener(self):
    while self.alive:
      if self._her_lla_subscriber is not None:
        try:
          (topic, msg) = self._her_lla_subscriber.recv()
          if topic == "LLA":
            self._her_data_lock.acquire()
            self._her_lla_data = msg
            self._her_data_lock.release()
            self._her_last_msg_received = time.time()
        except:
          pass
    _logger.info("Her LLA listener, thread exit")

  def _get_her_lla(self):
    self._her_data_lock.acquire()
    msg = copy.deepcopy(self._her_lla_data)
    self._her_data_lock.release()
    return msg

  def _her_lla_publisher(self, role):
    _logger.debug(f'Running LLA publisher for role: {role}')
    topic = 'LLA'
    while self.alive:
      if self._her_lla_data is not None and self._her_last_msg_received != self.lla_publishers_timing[role]:
        self.lla_publishers_timing[role] = copy.deepcopy(self._her_last_msg_received)
        her_lla = self._get_her_lla()
        if role == "Ahead":
          direction = 1
          if self.cyclist_point.state == "Returning":
            direction = -1
          modified_msg = dss.auxiliaries.math.compute_lookahead_lla_reference(self.road['id0'], self.road['id1'], her_lla, direction, self.ahead_distance)
        else:
          #Above drone only project
          modified_msg = dss.auxiliaries.math.compute_lookahead_lla_reference(self.road['id0'], self.road['id1'], her_lla, dir=1, distance=0)
          # Calc dist to home and monitor cyclist speed relative to home, trigger switch if conditions are met
          dist_home = dss.auxiliaries.math.distance_2D(self.road['id0'], modified_msg)
          self.cyclist_point.new_measurement(time.time(), dist_home)
          if self.cyclist_point.switched_direction(dist_home):
            if self.cyclist_point.state == "Returning":
              self.background_task_queue.put(f'all pattern {(self.road_heading-180) % 360}')
            else:
              self.background_task_queue.put(f'all pattern {self.road_heading}')

        #Use fixed altitude for smoother movements
        alt_diff = 0 if role == "Above" else self.ahead_rel_alt_diff
        modified_msg["alt"] = dss.auxiliaries.config.config["app_skara"]["ground_altitude"]+alt_diff
        self.lla_publishers[role].publish(topic, modified_msg)
        #Enable/disable spotlight?
        if dss.auxiliaries.math.distance_2D(self.road['id0'], modified_msg) < self.spotlight_switch_distance:
          if self.spotlight_enabled[role]:
            self.background_task_queue.put(f'{role} spotlight disable')
        else:
          if not self.spotlight_enabled[role]:
            self.background_task_queue.put(f'{role} spotlight enable')
      time.sleep(0.05)
    _logger.info(f"LLA publisher for {role}, thread exit")

#--------------------------------------------------------------------#
# Application reply: 'follow_her'
  def _request_follow_her(self, msg):
    fcn = dss.auxiliaries.zmq.get_fcn(msg)
    # Check nack reasons
    if not self.from_owner(msg) and msg['id'] != "GUI":
      descr = 'Requester ({}) is not the APP owner'.format(msg['id'])
      answer = dss.auxiliaries.zmq.nack(fcn, descr)
    elif not 'target_id' in msg:
      descr = 'missing target id'
      answer = dss.auxiliaries.zmq.nack(fcn, descr)
    elif msg['enable'] and self._follow_her_enabled:
      descr = 'follow her already enabled'
      answer = dss.auxiliaries.zmq.nack(fcn, descr)
    # Accept if target id in list from CRM
    else:
      answer = self.crm.clients(filter=msg['target_id'])
      if msg['target_id'] in answer['clients']:
        self.her_id = msg['target_id']
        self.her = answer['clients'][self.her_id]
        self._follow_her_enabled = msg['enable']
        answer = dss.auxiliaries.zmq.ack(fcn)
      else:
        descr = 'target id not found'
        answer = dss.auxiliaries.zmq.nack(fcn, descr)
    return answer

#--------------------------------------------------------------------#
# Application reply: 'get_info'
  def _request_get_info(self, msg):
    answer = dss.auxiliaries.zmq.ack(msg['fcn'])
    answer['id'] = self.crm.app_id
    answer['info_pub_port'] = self._info_socket.port
    answer['data_pub_port'] = None
    return answer

  def _request_heart_beat(self, msg):
    answer = dss.auxiliaries.zmq.ack(msg['fcn'])
    return answer

  # Task follow her
  def _follow_her(self, msg):
    if not msg['enable']:
      self.disable_followstream()
    else:
      #Setup LLA listener to her
      self.setup_her_lla_subscriber()
      # Allocate the drones needed for the job
      self.allocate_drones(msg['capabilities'])
      # Setup drones and enable follow stream
      self.setup_drones_and_enable_follow_stream()
      #what happens if stream enable false during await controls?

  def disable_followstream(self):
        #Start by disable follow stream
        for drone in self.drones.values():
          try:
            drone.disable_follow_stream()
          except dss.auxiliaries.exception.Nack:
            _logger.warning("Not able to disable follow stream..")
        self._her_lla_subscriber = None
        # Land the drones after stream disabled.
        #Wait for disable follow stream to finish
        time.sleep(2.0)
        for drone in self.drones.values():
          try:
            drone.dss_srtl()
          except dss.auxiliaries.exception.Nack:
            _logger.warning("Not able to perform dss srtl...")

  def allocate_drones(self, capabilities):
    # Acquire the drones.items drones.
    for role, drone in self.drones.items():
          #Obtain a drone with correct capabilities
          drone_received = False
          while not drone_received:
            self.check_if_cancelled('drone allocation')
            answer = self.crm.get_drone(capabilities=capabilities)
            if not dss.auxiliaries.zmq.is_ack(answer):
              _logger.warning('No drone with correct capabilities available.. Sleeping for 2 seconds')
              time.sleep(2.0)
            else:
              drone_received = True
          _logger.info(f"Received drone for role: {role}")
          drone.connect(answer['ip'], answer['port'], app_id=self.app_id)
          if role == "Above":
            info_port = drone.get_port('info_pub_port')
            drone.enable_data_stream('LLA')
            self._above_drone_lla_subscriber = dss.auxiliaries.zmq.Sub(_context, answer['ip'], info_port, "info above")

  def release_drones(self):
    #Disconnect the drones
    for drone in self.drones.values():
      try:
        drone.dss_disconnect()
      except:
        _logger.warning("Not able to disconnect properly. Perhaps drone not allocated?")

  def setup_drones_and_enable_follow_stream(self):
    for role, drone in self.drones.items():
      #Await controls
      _logger.debug('WAITING FOR CONTROLS')
      while not drone.is_who_controls('APPLICATION'):
        self.check_if_cancelled('await controls')
        time.sleep(0.5)
      if drone.get_flight_state() == 'flying':
        drone.set_alt(alt=self.takeoff_height, ref="init")
      else:
        # Takeoff and reset DSS SRTL
        drone.try_set_init_point()
        drone.set_geofence(height_low=self.geofence_height_min, height_high=self.geofence_height_max, radius=self.geofence_radius)
        drone.arm_and_takeoff(height=self.takeoff_height)
        drone.reset_dss_srtl()
      #Enable follow stream with pattern above
      drone.set_pattern_above(rel_alt=self.pattern_rel_alt, heading=self.road_heading)
      drone.enable_follow_stream(self._app_ip, self.lla_publishers[role].port)
      #Background thread to monitor if pilot intervenes
      monitor_thread = threading.Thread(target=self._monitor_follow_stream, args=(role,), daemon=True)
      monitor_thread.start()

  def check_if_cancelled(self, status_str):
    # Check if task is cancelled, i.e. if link is lost or if follow_her is disabled during initialization
    if self._is_link_lost():
      _logger.warning(f'Link is lost during {status_str}')
      self.release_drones()
      raise dss.auxiliaries.exception.AbortTask
    elif not self._follow_her_enabled:
      _logger.info(f'Disable follow her received during {status_str}')
      self.release_drones()
      raise dss.auxiliaries.exception.AbortTask

  def _monitor_follow_stream(self, role):
    while self.alive and self._follow_her_enabled:
      time.sleep(1.0)
      #Check if drone is idle and application is in controls
      if self.drones[role].get_idle() and self.drones[role].is_who_controls('APPLICATION'):
        # Enable follow stream again after controls has been handled back to the drone
        try:
          self.drones[role].enable_follow_stream(self._app_ip, self.lla_publishers[role].port)
        except dss.auxiliaries.exception.Nack as error:
          _logger.error(f'Nacked when sending {error.fcn}, received error: {error.msg}')


#--------------------------------------------------------------------#
  def _main_task(self):
    '''Executes the current task'''
    while self.alive:
      fcn = self._task_msg['fcn']
      if fcn:
        _logger.debug(f"fcn: {fcn}")
        try:
          task = self._commands[fcn]['task']
          task(self._task_msg)
        except dss.auxiliaries.exception.AbortTask:
          _logger.warning('abort current task')
        except dss.auxiliaries.exception.Error:
          _logger.error(traceback.format_exc())

      if self.alive:
        self._task_event.clear()
        self._task_event.wait()
    _logger.info("Main task executor, thread exit")


  #--------------------------------------------------------------------#
  def main(self):
    self._main_task_thread.start()
    cursor = ['  |o....|','  |.o...|', '  |..o..|', '  |...o.|','  |....o|', '  |...o.|', '  |..o..|', '  |.o...|']
    cursor_index = 7
    while self.alive:
      time.sleep(1)
      cursor_index += 1
      if cursor_index >= len(cursor):
        cursor_index = 0
      print(cursor[cursor_index], end = '\r', flush=True)

## The Point class that tracks the cyclist and triggers when cyclist switches direction
## The class instance is fed with new measurements of distance to home.
class Point():
  # Init
  def __init__(self, road_heading, road_length):
    # Create CRM object
    self.prev_time = time.time()
    self.prev_distance = 0.0
    self.filt_speed_home = 0.0
    self.state = "Leaving"
    self.trigger_speed = 1.2
    self.road_heading = road_heading
    self.road_length = road_length  # Not sure if this works.. otherwise return bool on switched

  def new_measurement(self, t, dist_home):
    # Calc delta distance and delta time
    delta_d = dist_home - self.prev_distance
    delta_t = t - self.prev_time
    # Store data for next calculation
    self.prev_distance = dist_home
    self.prev_time = t
    # Calc raw speed
    speed_home = -delta_d/delta_t
    # Update filtered speed
    k = 2
    self.filt_speed_home = (k*self.filt_speed_home + speed_home)/(k+1)
    _logger.info(f'filtered speed {self.filt_speed_home}, distance home: {dist_home}')

  def switched_direction(self, dist_home):
    #Have we reached the end of the road? Switch state before cyclist is actually returning
    switched = False
    if self.state == 'Leaving' and self.road_length-dist_home < 3.0:
      self.state = "Returning"
      self.filt_speed_home = 0.0
      switched = True
      _logger.info('End of road reached, cyclist is now Returning')
    elif self.filt_speed_home < -self.trigger_speed:
      if self.state == "Returning" and self.road_length-dist_home > 3.0:
        # Cyclist has switched
        self.state = "Leaving"
        switched = True
        _logger.info('Cyclist is now Leaving')
    # If cyclist is returning
    elif self.filt_speed_home > self.trigger_speed:
      # Cyclist is returning
      if self.state == "Leaving":
        # Cyclist has switched
        self.state = "Returning"
        switched = True
        _logger.info('Cyclist is now Returning')
    return switched

#--------------------------------------------------------------------#
def _main():
  # parse command-line arguments
  parser = argparse.ArgumentParser(description='APP "app skara"', allow_abbrev=False, add_help=False)
  parser.add_argument('-h', '--help', action='help', help=argparse.SUPPRESS)
  parser.add_argument('--app_ip', type=str, help='ip of the app', required=True)
  parser.add_argument('--id', type=str, default=None, help='id of this instance if started by crm')
  parser.add_argument('--crm', type=str, help='<ip>:<port> of crm', required=True)
  parser.add_argument('--log', type=str, default='debug', help='logging threshold')
  parser.add_argument('--owner', type=str, help='id of the instance controlling the app')
  parser.add_argument('--stdout', action='store_true', help='enables logging to stdout')
  args = parser.parse_args()

  # Identify subnet to sort log files in structure
  crm_ip_port = args.crm.split(':')
  subnet = dss.auxiliaries.zmq.get_subnet(port=int(crm_ip_port[1]))
  # Initiate log file
  dss.auxiliaries.logging.configure('app_skara', stdout=args.stdout, rotating=True, loglevel=args.log, subdir=subnet)

  # load mission from file
  road_str = dss.auxiliaries.config.config["app_skara"]["road_ref"]
  with open(road_str, encoding='utf-8') as handle:
    road = json.load(handle)
  if "source_file" in road:
    road.pop("source_file")
  n_drones = dss.auxiliaries.config.config["app_skara"]["n_drones"]
  # Create the AppSkara class
  try:
    app = AppSkara(args.app_ip, args.id, args.crm, road, n_drones, args.owner)
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
