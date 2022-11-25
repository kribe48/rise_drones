#!/usr/bin/env python3

'''
APP "app angel sim"


'''

import argparse
from distutils.log import info
import json
import logging
import sys
import threading
import time
import traceback

import zmq

import dss.auxiliaries
import dss.client

#--------------------------------------------------------------------#

__author__ = 'Lennart Ochel <lennart.ochel@ri.se>, Andreas Gising <andreas.gising@ri.se>, Kristoffer Bergman <kristoffer.bergman@ri.se>, Hanna Müller <hanna.muller@ri.se>, Joel Nordahl'
__version__ = '0.2.0'
__copyright__ = 'Copyright (c) 2022, RISE'
__status__ = 'development'

#--------------------------------------------------------------------#

_logger = logging.getLogger('dss.app_angel_sim')
_context = zmq.Context()

#--------------------------------------------------------------------#
# App mission - README.
#This app is used to
#1. Obtain a simulated drone
#2. Start app_skara and request "follow me" with the ip/port to the simulated drone
#2. Fly the "Skara Skyddsängel" mission to simulate a cyclist
#3. Land the simulated drone
# The input parameters are
# 1. mission: The json-file containing the mission
# 2. capabilities: List of capabilities required to perform the mission
# Quit application by calling kill() or Ctrl+C
#
# #--------------------------------------------------------------------#

class AppAngelSim():
  # Init
  def __init__(self, app_ip, app_id, crm, drone_capabilities):
    # Create Client object
    self.drone = dss.client.Client(timeout=2000, exception_handler=None, context=_context)
    self.drone_ip = None
    self.drone_info_port = None

    # Create CRM object
    self.crm = dss.client.CRM(_context, crm, app_name='app_angel_sim.py', desc='Angel sim application', app_id=app_id)

    self._alive = True
    self._dss_data_thread = None
    self._dss_data_thread_active = False
    self._dss_info_thread = None
    self._dss_info_thread_active = False

    # counter for transferred photos
    self.transferred = 0

    self.start_wp_reached = False

    self._app_ip = app_ip
    self.drone_data = None
    # capabilities for the requested drone
    self.drone_capabilities = drone_capabilities

    # The application sockets
    # Use ports depending on subnet used to pass RISE firewall
    # Rep: ANY -> APP
    self._app_socket = dss.auxiliaries.zmq.Rep(_context, label='app', min_port=self.crm.port, max_port=self.crm.port+50)
    # Pub: APP -> ANY
    self._info_socket = dss.auxiliaries.zmq.Pub(_context, label='info', min_port=self.crm.port, max_port=self.crm.port+50)

    # Start the app reply thread
    self._app_reply_thread = threading.Thread(target=self._main_app_reply, daemon=True)
    self._app_reply_thread.start()

    # Register with CRM (self.crm.app_id is first available after the register call)
    _ = self.crm.register(self._app_ip, self._app_socket.port)

    # All nack reasons raises exception, registration is successful
    _logger.info('App %s listening on %s:%d', self.crm.app_id, self._app_socket.ip, self._app_socket.port)
    _logger.info(f'App_angel_sim registered with CRM: {self.crm.app_id}')

    # Update socket labels with received id
    self._app_socket.add_id_to_label(self.crm.app_id)
    self._info_socket.add_id_to_label(self.crm.app_id)

    # Supported commands from ANY to APP
    self._commands = {'push_dss':     {'request': self._request_push_dss}, # Not implemented
                      'get_info':     {'request': self._request_get_info}}

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
    self._info_socket.close()

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
    _logger.info('Reply socket is listening on: %d', self._app_socket.port)
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
# Setup the DSS info stream thread
  def setup_dss_info_stream(self):
    #Get info port from DSS
    self.drone_info_port = self.drone.get_port('info_pub_port')
    if self.drone_info_port:
      self._dss_info_thread = threading.Thread(
        target=self._main_info_dss, args=[self.drone_ip, self.drone_info_port])
      self._dss_info_thread_active = True
      self._dss_info_thread.start()

#--------------------------------------------------------------------#
# The main function for subscribing to info messages from the DSS.
  def _main_info_dss(self, ip, port):
    # Enable LLA stream
    self.drone.enable_data_stream('LLA')
    # Enable waypoint subscription
    #self.drone.enable_data_stream('currentWP')
    # Create info socket and start listening thread
    info_socket = dss.auxiliaries.zmq.Sub(_context, ip, port, "info " + self.crm.app_id)
    while self._dss_info_thread_active:
      try:
        (topic, msg) = info_socket.recv()
        if topic == 'LLA':
          self.drone_data = msg
        elif topic == 'battery':
          _logger.info('Remaining battery time: %s seconds', msg["remaining_time"])
        else:
          _logger.debug('Topic not recognized on info link: %s', topic)
      except:
        pass
    info_socket.close()
    _logger.info("Stopped thread and closed info socket")
  #--------------------------------------------------------------------#
  def setup_app_skara_socket(self, skara_id):
    #Find all applications
    app_skara_found = False
    while not app_skara_found:
      answer = self.crm.clients(filter=skara_id)
      _logger.info(answer)
      if skara_id in answer['clients']:
        client = answer['clients'][skara_id]
        if client['ip'] and client['port']:
          self._app_skara_socket = dss.auxiliaries.zmq.Req(_context, client['ip'], client['port'], label='app-skara-req', timeout=2000)
          self._app_skara_socket.start_heartbeat(self.crm.app_id)
          app_skara_found = True
      if not app_skara_found:
        _logger.info(f'App_skara not found, sleeping for 2 seconds')
        time.sleep(2.0)

  def send_follow_her(self, enable):
    dss_id = self.drone.get_id()
    # Create message
    call = 'follow_her'
    msg = {'fcn': call, 'id': self.crm.app_id, 'enable': enable, 'target_id': dss_id, 'capabilities': ['SPOTLIGHT', 'SIM']}
    answer = self._app_skara_socket.send_and_receive(msg)
    # handle nack
    if not dss.auxiliaries.zmq.is_ack(answer, call):
      raise dss.auxiliaries.exception.Nack(dss.auxiliaries.zmq.get_nack_reason(answer), fcn=call)
    # return
    #
    return
  #--------------------------------------------------------------------#
  # Main function
  def main(self, mission):
    #Launch app skara
    answer = self.crm.launch_app('app_skara.py')
    if dss.auxiliaries.zmq.is_nack(answer):
      _logger.error('Unable to launch app_skara')
    # Setup connection to app_skara
    self.setup_app_skara_socket(answer['id'])
    # Get a drone with the right capabilities
    answer = self.crm.get_drone(capabilities=self.drone_capabilities)

    if dss.auxiliaries.zmq.is_nack(answer):
      _logger.error('Did not receive a drone: %s', dss.auxiliaries.zmq.get_nack_reason(answer))
      return

    # Connect to the drone, set app_id in socket
    self.drone_ip = answer['ip']
    try:
      self.drone.connect(self.drone_ip, answer['port'], app_id=self.crm.app_id)
      _logger.info("Connected as owner of drone: [%s]", self.drone._dss.dss_id)
    except dss.auxiliaries.exception.Nack:
      _logger.error("Failed to connect as owner, check crm")
      return
    # Setup info and data stream to DSS
    self.setup_dss_info_stream()

    # Send a command to the connected drone and print the result
    _logger.info(self.drone._dss.get_info())

    # Request app_skara to follow the drone
    self.send_follow_her(enable=True)
    # Wait for other drones to launch
    sleep_time = 60
    start_time = time.time()
    while time.time() < start_time + sleep_time:
      _logger.info(f"Waiting for drones to start, time remaining: {start_time + sleep_time - time.time()}")
      time.sleep(1.0)
    # Request controls from PILOT
    _logger.info("Requesting controls")
    self.drone.await_controls()
    _logger.info("Application is in controls")

    # Initialization
    self.drone.try_set_init_point('drone')
    self.drone.set_geofence(1, 30, 1000)

    # Upload mission
    if "lat" in mission["id0"]:
      self.drone.upload_mission_LLA(mission)
    else:
      self.drone.upload_mission_XYZ(mission)

    # take-off
    _logger.info("Take off")
    self.drone.arm_and_takeoff(max(2.5, min(30, mission["id0"]["alt"])))
    self.drone.reset_dss_srtl()
    # Fly waypoints, allow PILOT intervention.
    current_wp = 0
    while True:
      try:
        self.drone.fly_waypoints(current_wp)
        self.drone.land()
      except dss.auxiliaries.exception.Nack as nack:
        if nack.msg == 'Not flying':
          _logger.info("Pilot has landed")
        else:
          _logger.warning('Fly mission was nacked: %s', nack.msg)
        break
      except dss.auxiliaries.exception.AbortTask:
        # PILOT took controls
        (current_wp, _) = self.drone.get_currentWP()
        _logger.info("Pilot took controls, awaiting PILOT action")
        self.drone.await_controls()
        _logger.info("PILOT gave back controls")
        # Try to continue mission
        continue
      else:
        # Mission is completed
        break

    self.send_follow_her(enable=False)
    # rtl if not already on ground
    if self.drone.is_armed():
      self.drone.rtl()

#--------------------------------------------------------------------#
def _main():
  # parse command-line arguments
  parser = argparse.ArgumentParser(description='APP "app angel sim"', allow_abbrev=False, add_help=False)
  parser.add_argument('-h', '--help', action='help', help=argparse.SUPPRESS)
  parser.add_argument('--app_ip', type=str, help='ip of the app', required=True)
  parser.add_argument('--capabilities', type=str, default=None, nargs='*', help='If any specific capability is required')
  parser.add_argument('--id', type=str, default=None, help='id of this instance if started by crm')
  parser.add_argument('--crm', type=str, help='<ip>:<port> of crm', required=True)
  parser.add_argument('--log', type=str, default='debug', help='logging threshold')
  parser.add_argument('--mission', type=str, default='Mission_lla.json')
  parser.add_argument('--owner', type=str, help='id of the instance controlling the app- not used in this use case')
  parser.add_argument('--stdout', action='store_true', help='enables logging to stdout')
  args = parser.parse_args()

  # Identify subnet to sort log files in structure
  subnet = dss.auxiliaries.zmq.get_subnet(ip=args.app_ip)
  # Initiate log file
  dss.auxiliaries.logging.configure('app_angel_sim', stdout=args.stdout, rotating=True, loglevel=args.log, subdir=subnet)
  # Create the PhotoMission class
  try:
    app = AppAngelSim(args.app_ip, args.id, args.crm, args.capabilities)
  except dss.auxiliaries.exception.NoAnswer:
    _logger.error('Failed to instantiate application: Probably the CRM couldn\'t be reached')
    sys.exit()
  except:
    _logger.error('Failed to instantiate application\n%s', traceback.format_exc())
    sys.exit()

  # load mission from file
  with open(args.mission, encoding='utf-8') as handle:
    mission = json.load(handle)
  if "source_file" in mission:
    mission.pop("source_file")

  _logger.debug(json.dumps(mission, indent=2))

  # Try to setup objects and initial sockets
  try:
    # Try to run main
    app.main(mission)
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
