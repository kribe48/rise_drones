#!/usr/bin/env python3

'''
APP "app_lmd"

Input parameters
1. Mission - the misssion to execute
2. Start WP - where to start

This application
1. Connects to the CRM
2. Asks for an available drone resource with correct capability
3. Loads the mission and pass it to the drone
4. Executes the mission
5. Finish the mission by returning to a return location
'''

import argparse
import json
import logging
import sys
import threading
import time
import traceback
from pathlib import Path
import zmq

import dss.auxiliaries
import dss.client

#--------------------------------------------------------------------#

__author__ = 'Lennart Ochel <lennart.ochel@ri.se>, Andreas Gising <andreas.gising@ri.se>, Kristoffer Bergman <kristoffer.bergman@ri.se>, Hanna Müller <hanna.muller@ri.se>, Joel Nordahl'
__version__ = '0.1.0'
__copyright__ = 'Copyright (c) 2022, RISE'
__status__ = 'development'

#--------------------------------------------------------------------#

_logger = logging.getLogger('dss.app_geopoint')
_context = zmq.Context()

#--------------------------------------------------------------------#
class AppGeo():
  def __init__(self, app_ip, app_id, crm):
    # Create Client object
    self.drone = dss.client.Client(timeout=2000, exception_handler=None, context=_context)

    # Create CRM object
    self.crm = dss.client.CRM(_context, crm, app_name='app_lmd.py', desc='LMD mission', app_id=app_id)

    self._alive = True
    self._dss_data_thread = None
    self._dss_data_thread_active = False
    self._dss_info_thread = None
    self._dss_info_thread_active = False

    self._app_ip = app_ip

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
    self._commands = {'get_info':         {'request': self._request_get_info}}

    # Register with CRM (self.crm.app_id is first available after the register call)
    _ = self.crm.register(self._app_ip, self._app_socket.port)

    # Update socket labels with received id
    self._app_socket.add_id_to_label(self.crm.app_id)
    self._info_socket.add_id_to_label(self.crm.app_id)

    # All nack reasons raises exception, registration is successful
    _logger.info('App %s listening on %s:%s', self.crm.app_id, self._app_socket.ip, self._app_socket.port)
    _logger.info('App_lmd registered with CRM: %s', self.crm.app_id)

    self._input_commands = {'1':    {'description': 'Connect to a drone', 'fcn': self.connect_to_drone},
                            '2':      {'description': 'Store geopoint at current location', 'fcn': self.store_geopoint},
                            '3': {'description': 'Print current gnss_state', 'fcn': self.display_gnss_state},
                            '4': {'description': 'Print current gnss_state threshold', 'fcn': self.display_gnss_threshold},
                            '5': {'description': 'Increase current gnss_state threshold', 'fcn': self.increase_gnss_threshold},
                            '6': {'description': 'Decrease current gnss_state threshold', 'fcn': self.decrease_gnss_threshold},
                            'q'      : {'description': 'Quit program', 'fcn': self.quit_application},
                            'h'      : {'description': 'List available commands', 'fcn': self.display_help}}

    self._gnss_state_threshold = 6
    self.drone_received = False
    self.drone_data = None
    self.drone_data_lock = threading.Lock()

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
# reply: 'get_info'
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
    # Create info socket and start listening thread
    info_socket = dss.auxiliaries.zmq.Sub(_context, ip, port, "info " + self.crm.app_id)
    while self._dss_info_thread_active:
      try:
        (topic, msg) = info_socket.recv()
        if topic == "LLA":
          self.drone_data_lock.acquire()
          self.drone_data = msg
          self.drone_data_lock.release()
        elif topic == 'battery':
          _logger.debug("Not implemented yet...")
        else:
          _logger.warning("Topic not recognized on info link: %s", topic)
      except:
        pass
    info_socket.close()
    _logger.info("Stopped thread and closed info socket")

#------------------------TASKS----------------------------------------#
  def connect_to_drone(self):
    if self.drone_received:
      _logger.info("Already connected to a drone!")
      return
    user_input = input("Use forced ID? [yes/no]:")
    if user_input.lower() == "yes":
      capabilities = None
      forced_id = input("Specify name of dss to connect to:")
    else:
      capabilities = ['RTK']
      forced_id = None
    failed_count = 0
    while self.alive and not self.drone_received and failed_count < 10:
      # Get a drone
      if capabilities:
        answer = self.crm.get_drone(capabilities=capabilities)
        if dss.auxiliaries.zmq.is_nack(answer):
          failed_count += 1
          _logger.info(f"No drone available with capabilities: {capabilities} - sleeping for 2 seconds")
          time.sleep(2.0)
        else:
          self.drone_received = True
      else:
        answer = self.crm.get_drone(force=forced_id)
        if dss.auxiliaries.zmq.is_nack(answer):
          failed_count += 1
          _logger.info(f"Not possible to connect to drone with name: {forced_id} - sleeping for 2 seconds")
          time.sleep(2.0)
        else:
          self.drone_received = True
    if not self.drone_received:
      _logger.info("Not possible to connect to a drone, check c2m2 for status and try again....")


    # Connect to the drone, set app_id in socket
    self.drone.connect(answer['ip'], answer['port'], app_id=self.crm.app_id)
    _logger.info("Connected as owner of drone: [%s]", self.drone._dss.dss_id)

    # Setup info stream to DSS
    self.setup_dss_info_stream()
#--------------------------------------------------------------------#
  def display_gnss_state(self):
    if self.drone_data:
      self.drone_data_lock.acquire()
      try:
        gnss_state = self.drone_data["gnss_state"]
        _logger.info(f"GNSS state : {gnss_state}")
      except KeyError:
        _logger.info("GNSS state is not known")
      self.drone_data_lock.release()
    else:
      _logger.info("No LLA stream received yet")
#--------------------------------------------------------------------#
  def display_gnss_threshold(self):
    _logger.info(f"GNSS state threshold : {self._gnss_state_threshold}")

#--------------------------------------------------------------------#
  def increase_gnss_threshold(self):
    self._gnss_state_threshold = min(6, self._gnss_state_threshold+1)
    _logger.info(f"GNSS state threshold : {self._gnss_state_threshold}")

#--------------------------------------------------------------------#
  def decrease_gnss_threshold(self):
    self._gnss_state_threshold = max(3, self._gnss_state_threshold-1)
    _logger.info(f"GNSS state threshold : {self._gnss_state_threshold}")
#--------------------------------------------------------------------#
  def display_help(self):
    _logger.info("***The available commands***")
    for key, value in self._input_commands.items():
      _logger.info(f"{key}: {value['description']}")
#--------------------------------------------------------------------#
  def quit_application(self):
    self._alive = False
#--------------------------------------------------------------------#
  def store_geopoint(self):
    if self.drone_data:
      self.drone_data_lock.acquire()
      try:
        drone_data = self.drone_data
        gnss_state = drone_data["gnss_state"]
      except KeyError:
        _logger.info("GNSS state is not known")
        self.drone_data_lock.release()
        return
      self.drone_data_lock.release()
      if gnss_state >= self._gnss_state_threshold:
        #Store LLA at POI.json
        poi = {"lat": drone_data["lat"], "lon": drone_data["lon"], "alt": drone_data["alt"], "gnss_state": gnss_state}
        fname = input("Enter waypoint name: ")
        wp_fp = Path.cwd().joinpath(fname+'.txt')
        with open(wp_fp, 'w') as file:
          json.dump(poi, file, indent=2)
        _logger.info(f"Waypoint stored at {wp_fp}")
      else:
        _logger.info(f"GNSS state not high enough. Current state: {gnss_state}")
    else:
      _logger.info("No LLA stream received yet. Make sure that you are connected to a drone")

#--------------------------------------------------------------------#
# Main function
  def main(self):
    while self.alive:
      user_input = input("Enter command: ")
      if user_input.lower() in self._input_commands:
        current_fcn = self._input_commands[user_input.lower()]['fcn']
        current_fcn()
      else:
        _logger.info("Unknown command. Type help to list available commands")

#--------------------------------------------------------------------#
def _main():
  # parse command-line arguments
  parser = argparse.ArgumentParser(description='APP "app_noise"', allow_abbrev=False, add_help=False)
  parser.add_argument('-h', '--help', action='help', help=argparse.SUPPRESS)
  parser.add_argument('--app_ip', type=str, help='ip of the app', required=True)
  parser.add_argument('--id', type=str, default=None, help='id of this app instance if started by crm')
  parser.add_argument('--crm', type=str, help='<ip>:<port> of crm', required=True)
  parser.add_argument('--log', type=str, default='debug', help='logging threshold')
  parser.add_argument('--stdout', action='store_true', help='enables logging to stdout')
  args = parser.parse_args()

  # Identify subnet to sort log files in structure
  subnet = dss.auxiliaries.zmq.get_subnet(ip=args.app_ip)
  # Initiate log file
  dss.auxiliaries.logging.configure('app_geopoint', stdout=args.stdout, rotating=True, loglevel=args.log, subdir=subnet)

  # Create the AppLMD class

  try:
    app = AppGeo(args.app_ip, args.id, args.crm)
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
