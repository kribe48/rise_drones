#!/usr/bin/env python3

import argparse
import threading
import logging
import threading
import time
import traceback
import sys
import json
import zmq
import math

import dss.auxiliaries
import dss.client
from mqtt_agent.mqtt_agent import MqttAgent

#--------------------------------------------------------------------#

__author__ = 'Lennart Ochel <lennart.ochel@ri.se>, Andreas Gising <andreas.gising@ri.se>, Kristoffer Bergman <kristoffer.bergman@ri.se>, Hanna Müller <hanna.muller@ri.se>, Joel Nordahl'
__version__ = '1.0.0'
__copyright__ = 'Copyright (c) 2021, RISE'
__status__ = 'development'

#--------------------------------------------------------------------#

_logger = logging.getLogger('dss.monitor')
_context = zmq.Context()

#--------------------------------------------------------------------#
class Monitor():
  def __init__(self, app_ip, app_id, crm, mqtt_agent):
    # Import the client lib
    dss.client.Client.__init__(self, timeout=2000, exception_handler=None, context=_context)

    self.crm = dss.client.CRM(_context, crm, app_name='app_monitor.py', desc='Monitor application', app_id=app_id)
    #self._app_id = self.crm.app_id

    self._alive = True

    # If dronenet VPN is used, find the VPN ip of host machine
    # Find the VPN ip of host machine
    self._app_ip = app_ip
    auto_ip = dss.auxiliaries.zmq.get_ip()
    if auto_ip != app_ip:
      _logger.warning("Automatic get ip function and given ip does not agree: %s vs %s", auto_ip, app_ip)

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
    self._commands = {'get_info':         {'request': self._request_get_info},
                      'get_drone_data':   {'request': self._request_get_drone_data}}
    # Register with CRM (self.crm.app_id is first available after the register call)
    _ = self.crm.register(self._app_ip, self._app_socket.port)

    # Update socket labels with received id
    self._app_socket.add_id_to_label(self.crm.app_id)
    self._info_socket.add_id_to_label(self.crm.app_id)

    # All nack reasons raises exception, registreation is successful
    _logger.info('App %s listening on %s:%s', self.crm.app_id, self._app_socket.ip, self._app_socket.port)
    _logger.info(f'App_monitor registered with CRM: {self.crm.app_id}')

    # Clients that are connected to the CRM
    self.clients = {}
    self._info_threads = {}
    #Store the data received from the drones
    self.drone_data = {}
    self.drone_data_locks = {}
    self.battery_data = {}
    self.mqtt_agent = mqtt_agent
    self._mqtt_threads = {}
    # Use pre-allocated IDs to remove ghost problem in mqtt
    self.allocated_idxs = {}
    self.max_drones = 100
    self.available_idxs = []
    for ii in range(0, self.max_drones):
      self.available_idxs.append(ii)

#--------------------------------------------------------------------#
  @property
  def alive(self):
    '''checks if CRM is alive'''
    return self._alive

#--------------------------------------------------------------------#
  def kill(self):
    # Clean the clients list to stop subscription threads and closing sockets.
    self.clients = {}

    # Unregister APP from CRM
    _logger.info("Unregister from CRM")
    answer = self.crm.unregister()
    if not dss.auxiliaries.zmq.is_ack(answer):
      _logger.error('Unregister failed: {answer}')
    _logger.info("CRM socket closed")

    if self._app_socket:
      self._app_socket.close()
      _logger.info("APP socket closed")
    _logger.debug('~ THE END ~')

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
# Application reply functions
  def _request_get_info(self, msg):
    answer = dss.auxiliaries.zmq.ack(msg['fcn'])
    answer['id'] = self.crm.app_id
    answer['info_pub_port'] = self._info_socket.port
    answer['data_pub_port'] = None
    return answer

  def _request_get_drone_data(self, msg):
    answer = dss.auxiliaries.zmq.ack(msg['fcn'])
    for key in self.drone_data_locks:
      self.drone_data_locks[key].acquire()
    answer['data'] = self.drone_data
    for key in self.drone_data_locks:
      self.drone_data_locks[key].release()
    return answer

#--------------------------------------------------------------------#
  @staticmethod
  def client_in_dict(client_id, client_dict) -> bool:
    return client_id in client_dict

  def print_clients(self):
    if len(self.clients) == 0:
      _logger.info('\nThe current list of dss clients is empty')
    else:
      _logger.info('\nThe current list of dss clients, [#](ID, NAME):')
      i = 1
      for client_id, client in self.clients.items():
        _logger.info(f'  [{i}] {client_id, client["name"]}')
        i += 1

#--------------------------------------------------------------------#
  def setup_client(self, client_id):
    self._info_threads[client_id] = threading.Thread(target=self._subscriber_thread, args=(client_id,))
    self.drone_data_locks[client_id]= threading.Lock()
    self._info_threads[client_id].start()

  def setup_mqtt_client(self, client_id):
    self._mqtt_threads[client_id] = threading.Thread(target=self._mqtt_client, args=(client_id,))
    self._mqtt_threads[client_id].start()
# MQTT-thread. Connect an agent to WARA-PS core system and report position
  def _mqtt_client(self, client_id):
    drone_id = client_id
    drone_name = self.clients[drone_id]['drone_name']
    drone_type = self.clients[drone_id]['drone_type']
    sim_real = self.clients[drone_id]['sim_real']
    mqtt_agent = MqttAgent(drone_name, drone_type, sim_real)
    # Wait until position has been streamed
    time.sleep(2.0)
    rate: float = 1.0 / mqtt_agent.logic.rate #1.0
    while self.client_in_dict(drone_id, self.clients):
      drone_data = None
      self.drone_data_locks[drone_id].acquire()
      try:
        drone_data = self.drone_data[drone_id]
      except KeyError:
        _logger.warning("No data received from drone with with ID %s" % drone_id)
      self.drone_data_locks[drone_id].release()
      if drone_data :
        mqtt_agent.set_lla(drone_data['lat'], drone_data['lon'], drone_data['alt'])
        mqtt_agent.set_heading(drone_data['heading'])
        if 'vel_n' in drone_data:
          speed = math.sqrt(drone_data['vel_n']**2 + drone_data['vel_e']**2)
          mqtt_agent.set_speed(speed)
          if speed > 0.1 :
            course = (180/math.pi)*math.atan2(drone_data['vel_e'], drone_data['vel_n'])
            mqtt_agent.set_course(course)
      mqtt_agent.send_heartbeat()
      mqtt_agent.send_sensor_info()
      mqtt_agent.send_position()
      mqtt_agent.send_speed()
      mqtt_agent.send_course()
      mqtt_agent.send_heading()
      mqtt_agent.send_direct_execution_info()
      time.sleep(rate)

#--------------------------------------------------------------------#
  # An subscribe thread. One per client will be launched. Thread is killed when client is removed from list
  def _subscriber_thread(self, client_id):
    drone_id = client_id
    ip = self.clients[drone_id]['ip']
    port = self.clients[drone_id]['port']
    # print("Debug: New client ip and port: ", ip, port)

    # Connect the Request socket to enable the STATE stream
    req_socket = dss.auxiliaries.zmq.Req(_context, ip, port, label=drone_id, timeout=2000)
    # Enable stream
    stream = 'STATE'
    self.enable_stream(stream,req_socket)
    # Get info port from DSS
    sub_port = self.get_port(req_socket, 'info_pub_port')

    # Create subscription socket and start listening thread
    sub_socket = dss.auxiliaries.zmq.Sub(_context, ip, sub_port, drone_id)
    sub_socket.subscribe(stream)

    if self.mqtt_agent:
      self.setup_mqtt_client(client_id)

    while self.client_in_dict(drone_id, self.clients):
      try:
        (topic, msg) = sub_socket.recv()
        if topic == stream:
          self.drone_data_locks[drone_id].acquire()
          self.drone_data[drone_id] = msg
          self.drone_data_locks[drone_id].release()
        elif topic == 'battery':
          self.battery_data[drone_id] = msg
        else:
          pass
      except:
        pass
    #Remove the drone from the map
    self.drone_data_locks[drone_id].acquire()
    try :
      self.drone_data.pop(drone_id)
      self.battery_data.pop(drone_id)
    except KeyError :
      _logger.info("Not all data received from client with ID %s" % drone_id)
    self.drone_data_locks[drone_id].release()
    self.drone_data_locks.pop(drone_id)
    _logger.info("Stopped thread and closed socket for client: %s" % drone_id)

#--------------------------------------------------------------------#
  # Call the DSS reply socket using the req_socket to enable a stream
  # Ref fcn: 'data_stream'
  def enable_stream(self, stream, socket):
    msg = {'fcn': 'data_stream', 'id': self.crm.app_id}
    msg['stream'] = stream
    msg['enable'] = True
    answer = socket.send_and_receive(msg)
    if not dss.auxiliaries.zmq.is_ack(answer):
      _logger.error('data_stream error: %s', answer)

#--------------------------------------------------------------------#
  # Call the DSS reply socket using the req_socket to disable a stream
  # Ref fcn: 'data_stream'
  def disable_stream(self, stream, socket):
    msg = {'fcn': 'data_stream', 'id': self.crm.app_id}
    msg['stream'] = stream
    msg['enable'] = False
    answer = socket.send_and_receive(msg)
    if not dss.auxiliaries.zmq.is_ack(answer):
      _logger.error('data_stream error: %s', answer)

#--------------------------------------------------------------------#
  # Call the reply socket of the DSS to obtain the publish ports used
  # Ref fcn: 'ping'
  def get_port(self, socket, port_name) -> int:
    msg = {'fcn': 'get_info', 'id': self.crm.app_id}
    answer = socket.send_and_receive(msg)
    if not dss.auxiliaries.zmq.is_ack(answer):
      _logger.error('get_info error: %s', answer)
      return 0
    return int(answer[port_name])

#--------------------------------------------------------------------#
  def main(self):
    cursor = ['  |o....|','  |.o...|', '  |..o..|', '  |...o.|','  |....o|', '  |...o.|', '  |..o..|', '  |.o...|']
    cursor_index = 7


    # Prepare for main loop
    print("Monitoring dss clients registered with CRM")

    # Main loop looking for changes in crm clients list
    while self._alive:
      answer = self.crm.clients('dss')
      if dss.auxiliaries.zmq.is_ack(answer, 'clients'):
        # The latest list of clients from crm
        crm_clients = answer['clients']

        # Figure if we already have all clients in our local list. Loop through the CRM-dict -> append
        for client_id, client in crm_clients.items():
          if not self.client_in_dict(client_id, self.clients):
            if client['ip'] != '':
              #Allocate an ID
              lowest_idx = min(self.available_idxs)
              self.allocated_idxs[client_id]= lowest_idx
              self.available_idxs.remove(lowest_idx)
              if "[SIM]" in client['desc']:
                client['sim_real'] = "simulation"
                client['drone_name'] = "RISE-" + '{index:03d}'.format(index=self.allocated_idxs[client_id])
                client['drone_type'] = 'air'
              elif "HX" in client['desc']:
                client['sim_real'] = "real"
                client['drone_name'] = "RISE-" + client['desc']
                client['drone_type'] = 'air'
              else:
                client['sim_real'] = "real"
                client['drone_name'] = "RISE-"+ '{index:03d}'.format(index=self.allocated_idxs[client_id])
                client['drone_type'] = "air"
              self.clients[client_id]=client
              _logger.info(f'Client {client_id}, {client} added to the list')
              self.setup_client(client_id)
              self.print_clients()
            else:
              _logger.info(client_id + " has no ip, not adding to list..")

        # Figure if there is a client on our local list that is not in the CRM-list -> pop
        clients_to_pop = {}
        for client_id in self.clients:
          if not self.client_in_dict(client_id, crm_clients):
            # Collect clients to pop outside the for loop
            clients_to_pop[client_id] = 1
        # Pop clients from client list, subscription will be ended and socket closed
        for client_id in clients_to_pop:
          self.clients.pop(client_id)
          current_idx = self.allocated_idxs[client_id]
          self.available_idxs.append(current_idx)
          self.allocated_idxs.pop(client_id)
          _logger.info('Client {the_client} popped from the list'.format(the_client=client_id))
          self.print_clients()

      time.sleep(1)
      cursor_index += 1
      if cursor_index >= len(cursor):
        cursor_index = 0
      print(cursor[cursor_index], end = '\r', flush=True)


#--------------------------------------------------------------------#
def _main():
  # parse command-line arguments
  parser = argparse.ArgumentParser(description='DSS-APP "monitor"', allow_abbrev=False, add_help=False)
  parser.add_argument('-h', '--help', action='help', help=argparse.SUPPRESS)
  parser.add_argument('--id', type=str, default=None, help='id of the app_monitor instance provided by crm')
  parser.add_argument('--crm', type=str, help='<ip>:<port> of crm', required=True)
  parser.add_argument('--app_ip', type=str, help='ip of the app', required=True)
  parser.add_argument('--mqtt_agent', action='store_true', help='enable MQTT sensor reporting (level 1 agent) to WARA-PS core system')
  parser.add_argument('--owner', type=str, help='id of the instance controlling app_monitor - not used in this use case')
  parser.add_argument('--log', type=str, default='debug', help='logging threshold')
  parser.add_argument('--stdout', action='store_true', help='enables logging to stdout')
  args = parser.parse_args()

  # Identify subnet to sort log files in structure
  subnet = dss.auxiliaries.zmq.get_subnet(ip=args.app_ip)
  # Initiate the log file
  dss.auxiliaries.logging.configure('app_monitor', stdout=args.stdout, rotating=True, loglevel=args.log, subdir=subnet)

  # Create the monitor class
  try:
    app = Monitor(args.app_ip, args.id, args.crm, args.mqtt_agent)
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
