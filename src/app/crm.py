#!/usr/bin/env python3

import argparse
import datetime
import json
import logging
import subprocess
import traceback
import psutil
import zmq
import re
import os

import dss.auxiliaries
from dss.auxiliaries.config import config

#--------------------------------------------------------------------#

__author__ = 'Lennart Ochel <lennart.ochel@ri.se>, Andreas Gising <andreas.gising@ri.se>, Kristoffer Bergman <kristoffer.bergman@ri.se>, Hanna Müller <hanna.muller@ri.se>, Joel Nordahl'
__version__ = '1.2.8'
__copyright__ = 'Copyright (c) 2021-2022, RISE'
__status__ = 'development'

#--------------------------------------------------------------------#


class CRM:
  def __init__(self, ip: str, port: int, virgin=True):
    self._logger = logging.getLogger('dss.CRM')

    assert dss.auxiliaries.zmq.valid_ip(ip), f'bad ip address: {ip}'

    self._commands = {'app_lost':            self._request_app_lost,
                      'clients':             self._request_clients,
                      'delStaleClients':     self._request_delStaleClients,
                      'get_drone':           self._request_get_drone,
                      'get_processes':       self._request_get_processes,
                      'get_info':            self._request_get_info,
                      'get_performance':     self._request_get_performance,
                      'heart_beat':          self._request_heart_beat,
                      'kill_process':        self._request_kill_process,
                      'launch_app':          self._request_launch_app,
                      'launch_drone_helper': self._request_launch_drone_helper,
                      'launch_dss':          self._request_launch_dss,
                      'launch_sitl':         self._request_launch_sitl,
                      'register':            self._request_register,
                      'release_drone':       self._request_release_drone,
                      'restart':             self._request_restart,
                      'unregister':          self._request_unregister,
                      'upgrade':             self._request_upgrade}

    self._types = ('dss', 'da', 'dsa')

    self._alive = True
    self._clients = {}
    self._context = dss.auxiliaries.zmq.Context()
    self._ip = ip
    self._nextIndex = 1
    self._restart = False
    self._upgrade = False
    self._virgin = False

    self._git_branch = dss.auxiliaries.git.branch()
    self._git_version = dss.auxiliaries.git.describe()

    self._task_queue = dss.auxiliaries.TaskQueue()
    self._task_queue.start()

    if virgin:
      self._export_clients()
    else:
      self._import_clients()

    self._socket = dss.auxiliaries.zmq.Rep(self._context, port=port, label='crm')
    self._pub_socket = dss.auxiliaries.zmq.Pub(self._context, port=port+1, label='crm')

  @property
  def alive(self):
    '''checks if CRM is alive'''
    return self._alive

  def kill(self):
    self._task_queue.stop()
    self._alive = False

#.-.-.-.-.-.-.-.-.-.-.-.-.-.-.-.-.-.-.-.-.-.-.-.-.-.-.-.-.-.-.-.-.-.-#
# TASKS that the CRM will handle asynchronously

  def task_set_owner(self, client_name, new_owner):
    self._logger.info('task_set_owner')

    ip = self._clients[client_name]['ip']
    port = self._clients[client_name]['port']

    socket = dss.auxiliaries.zmq.Req(self._context, ip=ip, port=port, label=client_name, timeout=2000)

    for x in range(3):
      self._logger.info(f'task_set_owner, try {x}')
      try:
        answer = socket.send_and_receive({'fcn': 'set_owner', 'id': 'crm', 'owner': new_owner})
        if dss.auxiliaries.zmq.is_ack(answer):
          self._clients[client_name]['owner'] = new_owner
          return
      except dss.auxiliaries.exception.NoAnswer:
        self._logger.warning('NoAnswer sending set_owner')

  def task_rtl(self, client_name):
    self._logger.info('task_rtl')

    ip = self._clients[client_name]['ip']
    port = self._clients[client_name]['port']

    # RTL only if drone is armed!
    socket = dss.auxiliaries.zmq.Req(self._context, ip=ip, port=port, label=client_name)

    answer = socket.send_and_receive({'fcn': 'get_armed', 'id': 'crm'})
    if dss.auxiliaries.zmq.is_ack(answer):
      if bool(answer['armed']):
        id_app = '{type}{index:03d}'.format(type='da', index=self._nextIndex)
        self._nextIndex += 1
        self._clients[id_app] = {'name': 'SRTL', 'desc': 'landing a drone', 'type': 'da', 'owner': 'crm', 'ip': '', 'port': '', 'timestamp': self._now}
        dss.auxiliaries.spawnDaemon.spawnDaemon('./app_srtl.py', 'app_srtl.py', f'--id={id_app}', f'--ip={self._ip}', f'--port={self._socket.port}', f'--dss={client_name}')

  def task_start_battery_stream(self, client_name):
    self._logger.info('task_start_battery_stream')

    ip = self._clients[client_name]['ip']
    port = self._clients[client_name]['port']

    socket = dss.auxiliaries.zmq.Req(self._context, ip=ip, port=port, label=client_name, timeout=1000)
    for x in range(3):
      self._logger.info(f'enable battery stream, try {x}')
      try:
        answer = socket.send_and_receive({'fcn': 'data_stream', 'id': 'crm', 'stream': 'battery', 'enable': True})
        if dss.auxiliaries.zmq.is_ack(answer):
          return
      except dss.auxiliaries.exception.NoAnswer:
        self._logger.warning('NoAnswer sending battery stream')
        pass

#.-.-.-.-.-.-.-.-.-.-.-.-.-.-.-.-.-.-.-.-.-.-.-.-.-.-.-.-.-.-.-.-.-.-#
  def _get_clients(self, filter='') -> dict:
    client_list = {}
    for id_, client in self._clients.items():
      if filter in id_ and client['ip'] and client['port']:
        client_list[id_] = client
    return client_list

  def main(self):
    self._logger.info('CRM is listening on {ip}:{port}'.format(ip=self._ip, port=self._socket.port))

    while self._alive:
      self._now = datetime.datetime.now().timestamp()

      try:
        msg = self._socket.recv_json()
      except zmq.error.Again as error:
        self.delStaleClients()
        continue # timeout: no message received; try again

      msg = json.loads(msg)

      fcn = dss.auxiliaries.zmq.get_fcn(msg)
      if fcn in self._commands:
        if 'id' in msg:
          id_ = msg['id']
          if id_ in self._clients:
            self._clients[id_]['timestamp'] = self._now

        try:
          answer = self._commands[fcn](msg)
          self._export_clients()
        except:
          self._logger.error(f'unexpected exception\n{traceback.format_exc()}')
          answer = dss.auxiliaries.zmq.nack(fcn, 'unexpected exception')
      else:
        answer = dss.auxiliaries.zmq.nack(fcn, 'request is not supported')

      answer = json.dumps(answer)
      self._socket.send_json(answer)

    self._main_thread = None

  def delStaleClients(self) -> list:
    clientsToDelete = list()
    for id_, client in self._clients.items():
      if self._now - client['timestamp'] > 15: #seconds
        clientsToDelete.append(id_)

    for id_ in clientsToDelete:
      timestamp = self._clients[id_]["timestamp"]
      self._logger.warning(f'deleting {id_} {self._clients[id_]}')

      # If id_ (to be deleted) is owner of other client, something is wrong, write to log
      for all_id, all_client in self._clients.items():
        if all_client['owner'] == id_:
         self._logger.warning(f'CRM is deleting app {id_} that is owner of dss {all_client}')

      del self._clients[id_]
      self._logger.info(f'client {id_} got removed - it was inactive for {self._now - timestamp} seconds')

    return clientsToDelete

  def _export_clients(self):
    backup = {'nextIndex': self._nextIndex, 'clients': self._clients}
    with open('clients.json', 'w') as file:
      json.dump(backup, file, indent=2)

  def _import_clients(self):
    try:
      with open('clients.json') as file:
        backup = json.load(file)
      self._nextIndex = backup['nextIndex']
      self._clients = backup['clients']
    except:
      self._logger.error("backup file 'clients.json' couldn't be loaded")
      self._nextIndex = 1
      self._clients = {}

#.-.-.-.-.-.-.-.-.-.-.-.-.-.-.-.-.-.-.-.-.-.-.-.-.-.-.-.-.-.-.-.-.-.-#
# REQUESTS that the CRM will handle synchronously

  def _request_app_lost(self, msg: dict) -> dict:
    '''The function app_lost is called by a dss that has lost the link to its app for 5s.'''
    fcn = dss.auxiliaries.zmq.get_fcn(msg)

    # check arguments
    if 'id' not in msg:
      return dss.auxiliaries.zmq.nack(fcn, 'bad arguments: {id} are mandatory')

    id_ = msg['id']
    if id_ not in self._clients:
      return dss.auxiliaries.zmq.nack(fcn, 'unknown client id')

    # remove owner if not 'crm'
    owner = self._clients[id_]['owner']
    if owner != 'crm':
      self._task_queue.add(self.task_set_owner, id_, 'crm')

      # send rtl for now!
      self._task_queue.add(self.task_rtl, id_)

    return dss.auxiliaries.zmq.ack(fcn)

  def _request_clients(self, msg: dict) -> dict:
    fcn = dss.auxiliaries.zmq.get_fcn(msg)

    # check arguments
    if not all(key in msg for key in ['id', 'filter']):
      return dss.auxiliaries.zmq.nack(fcn, 'bad arguments: {id, filter} are mandatory')

    id_ = msg['id']
    if id_ not in self._clients and id_ != 'root':
      return dss.auxiliaries.zmq.nack(fcn, 'unknown client id')

    client_list = self._get_clients(msg['filter'])

    return dss.auxiliaries.zmq.ack(fcn, {'clients': client_list})

  def _request_delStaleClients(self, msg: dict) -> dict:
    fcn = dss.auxiliaries.zmq.get_fcn(msg)

    # check arguments
    if 'id' not in msg:
      return dss.auxiliaries.zmq.nack(fcn, 'bad arguments: {id} are mandatory')

    if msg['id'] != 'root':
      return dss.auxiliaries.zmq.nack(fcn, 'prohibited')

    clientsToDelete = self.delStaleClients()
    return dss.auxiliaries.zmq.ack(fcn, {'deleted': clientsToDelete})

  def _request_get_drone(self, msg: dict) -> dict:
    fcn = dss.auxiliaries.zmq.get_fcn(msg)

    # check arguments
    if not all(key in msg for key in ['id']):
      return dss.auxiliaries.zmq.nack(fcn, 'bad arguments: {id} is mandatory')
    if not any(key in msg for key in ['force', 'capabilities']):
      return dss.auxiliaries.zmq.nack(fcn, 'bad arguments: either force or capabilities must be used')

    requester_id = msg['id']
    if requester_id not in self._clients:
      return dss.auxiliaries.zmq.nack(fcn, 'unknown requestor id')

    if 'force' in msg:
      force = msg['force']
      if force not in self._clients:
        return dss.auxiliaries.zmq.nack(fcn, 'unknown forced id')
      if self._clients[force]['owner'] != 'crm':
        return dss.auxiliaries.zmq.nack(fcn, 'forced id not available')
      if self._now - self._clients[force]['timestamp'] > 20: #seconds
        return dss.auxiliaries.zmq.nack(fcn, 'forced id is stale')
      self._task_queue.add(self.task_set_owner, force, requester_id)
      return dss.auxiliaries.zmq.ack(fcn, {'id': force, 'ip': self._clients[force]['ip'], 'port': self._clients[force]['port']})
    else:
      #Get capabilities as a set for easy comparison. The casefold makes sure that the comparison is not case sensitive
      capabilities = set({capa.casefold(): capa for capa in msg['capabilities']})
      drone_found = False
      n_capabilities = 100
      for id_, client in self._clients.items():
        client_capabilities = set({capa.casefold(): capa for capa in client['capabilities']})
        # Try to find a suitable drone. Pick the one with least amount of total capabilities that satisfies the requirements.
        if client['owner'] == 'crm' and client['type'] == 'dss' and capabilities.issubset(client_capabilities) and len(client_capabilities) < n_capabilities and (self._now - client['timestamp']) < 20:
          drone_found = True
          n_capabilities = len(client_capabilities)
          dss_id = id_
      if drone_found:
        self._task_queue.add(self.task_set_owner, dss_id, requester_id)
        return dss.auxiliaries.zmq.ack(fcn, {'id': dss_id, 'ip': self._clients[dss_id]['ip'], 'port': self._clients[dss_id]['port']})

    return dss.auxiliaries.zmq.nack(fcn, 'no available drone with requested capabilities')

  def _request_get_info(self, msg: dict) -> dict:
    fcn = dss.auxiliaries.zmq.get_fcn(msg)

    # check arguments
    if not all(key in msg for key in ['id']):
      return dss.auxiliaries.zmq.nack(fcn, 'bad arguments: {id} is mandatory')

    requester = msg['id']
    if requester not in self._clients and requester != 'root':
      return dss.auxiliaries.zmq.nack(fcn, 'unknown client id')

    return dss.auxiliaries.zmq.ack(fcn, {'info_pub_port': self._pub_socket.port, 'data_pub_port': None, 'version': __version__, 'git_version': self._git_version, 'git_branch': self._git_branch})

  def _request_get_processes(self, msg: dict) -> dict:
    fcn = dss.auxiliaries.zmq.get_fcn(msg)

    # check arguments
    if not all(key in msg for key in ['id', 'project']):
      return dss.auxiliaries.zmq.nack(fcn, 'bad arguments: {id, project} is mandatory')

    requester = msg['id']
    project = msg["project"]
    if requester not in self._clients and requester != 'root':
      return dss.auxiliaries.zmq.nack(fcn, 'unknown client id')

    #List all processes
    processes = list()
    for proc in psutil.process_iter():
      try:
        if 'python' not in proc.name().lower() and 'arducopter' not in proc.name() and 'mavproxy' not in proc.name():
          continue
        # get process detail as dictionary
        info = proc.as_dict(attrs=['pid', 'name', 'cpu_percent', 'memory_percent', 'create_time', 'cmdline'])
        info['cmd'] = ' '.join(info['cmdline'])
        if not info['cmd']:
          continue
        info['project'] = 'unknown'
        for project in config["zeroMQ"]["subnets"]:
          regexp = re.compile(f'^.*[:=]{config["zeroMQ"]["subnets"][project]["subnet"]}[0-9][0-9].*$')
          if regexp.match(info['cmd']):
            info['project'] = project
            break
        info['killable'] = 'crm.py' not in info['cmd'] and project == info['project']
        info['memory_percent'] = str(round(info['memory_percent'], 1))
        info['created'] = datetime.datetime.fromtimestamp(info['create_time']).strftime('%Y-%m-%d %H:%M:%S')

        processes.append(info)
      except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        pass
    msg = dss.auxiliaries.zmq.ack(fcn)
    msg['processes'] = processes
    return msg

  def _request_get_performance(self, msg):
    fcn = dss.auxiliaries.zmq.get_fcn(msg)
    # check arguments
    if not all(key in msg for key in ['id']):
      return dss.auxiliaries.zmq.nack(fcn, 'bad arguments: {id} is mandatory')

    now = datetime.datetime.now()
    current_time = now.strftime("%H:%M:%S")
    cpu = str(psutil.cpu_percent(interval=0.1)).zfill(5)
    mem = str(psutil.virtual_memory().percent).zfill(5)
    load = [str(round(x*100)).zfill(3) + '%' for x in os.getloadavg()]
    load = '(' + ', '.join(load) + ')'
    msg = dss.auxiliaries.zmq.ack(fcn)
    msg['performance'] = f'{cpu}% @ {psutil.cpu_freq().current}MHz x {psutil.cpu_count(logical=True)} {load} - {mem}% of {psutil.virtual_memory().total // 2**20}MB - time {current_time}'
    return msg

  def _request_kill_process(self, msg: dict) -> dict:
    fcn = dss.auxiliaries.zmq.get_fcn(msg)
    # check arguments
    if not all(key in msg for key in ['id', 'pid']):
      return dss.auxiliaries.zmq.nack(fcn, 'bad arguments: {id, pid} is mandatory')
    pid = msg["pid"]
    try:
      p = psutil.Process(int(pid))
      p.terminate()
      msg = dss.auxiliaries.zmq.ack(fcn)
    except (psutil.NoSuchProcess):
      msg = dss.auxiliaries.zmq.nack(fcn, f'process (pid {pid}) no longer exists')
    except:
      msg = dss.auxiliaries.zmq.nack(fcn, str(traceback.format_exc()))
    return msg



  def _request_heart_beat(self, msg: dict) -> dict:
    fcn = dss.auxiliaries.zmq.get_fcn(msg)

    # check arguments
    if not all(key in msg for key in ['id']):
      return dss.auxiliaries.zmq.nack(fcn, 'bad arguments: {id} is mandatory')

    id_ = msg['id']
    if id_ not in self._clients:
      return dss.auxiliaries.zmq.nack(fcn, 'unknown client id')

    # send always ack if client is in list
    return dss.auxiliaries.zmq.ack(fcn)

  def _request_launch_app(self, msg: dict) -> dict:
    fcn = dss.auxiliaries.zmq.get_fcn(msg)

    # check arguments
    if not all(key in msg for key in ['id', 'app']):
      return dss.auxiliaries.zmq.nack(fcn, 'bad arguments: {id} is mandatory')

    owner = msg['id']
    if owner not in self._clients and owner != 'root':
      return dss.auxiliaries.zmq.nack(fcn, 'unknown client id')

    if owner == 'root':
      owner = 'crm'

    # optional command line arguments that are passed directly yo the application
    extra_args = msg.get('extra_args', [])
    for arg in extra_args:
      assert isinstance(arg, str), 'extra_args must be of time string'

    app = msg['app']

    id_app = '{type}{index:03d}'.format(type='da', index=self._nextIndex)
    self._nextIndex += 1

    self._clients[id_app] = {'name': app, 'desc': '', 'type': 'da', 'owner': owner, 'ip': '', 'port': '', 'timestamp': self._now}

    launch = msg['launch'] if 'launch' in msg else True
    if launch:
      crm_connection_string = self._ip + ":" + str(self._socket.port)
      dss.auxiliaries.spawnDaemon.spawnDaemon(f'./{app}', app, f'--app_ip={self._ip}', f'--id={id_app}', f'--crm={crm_connection_string}', f'--owner={owner}', *extra_args)

    return dss.auxiliaries.zmq.ack(fcn, {'id': id_app})

  def _request_launch_drone_helper(self, msg: dict) -> dict:
    fcn = dss.auxiliaries.zmq.get_fcn(msg)
    return dss.auxiliaries.zmq.nack(fcn, 'not implemented')

  # Launch_dss is used by crm to launch crm_dss to a SITL running on the host machine.
  def _request_launch_dss(self, msg: dict) -> dict:
    fcn = dss.auxiliaries.zmq.get_fcn(msg)

    # check arguments
    if not all(key in msg for key in ['id', 'client_ip']):
      return dss.auxiliaries.zmq.nack(fcn, 'bad arguments: {id, client_ip} is mandatory')

    id_ = msg['id']
    if id_ not in self._clients and id_ != 'root':
      return dss.auxiliaries.zmq.nack(fcn, 'unknown client id')

    port = self._socket.port

    subprocess.Popen(['build/sitl/bin/arducopter', '-S', '--model', '+', '--speedup', '1', '--home', f'{config["CRM"]["SITL"]["drone_1"]["lat"]},{config["CRM"]["SITL"]["drone_1"]["lon"]},{config["CRM"]["SITL"]["drone_1"]["alt"]},{config["CRM"]["SITL"]["drone_1"]["heading"]}', f'--defaults={config["CRM"]["SITL"]["ardupilot_dir"]}Tools/autotest/default_params/copter.parm', f'--base-port={port+56}', '-I0', '--sysid', '1'], cwd=f'{config["CRM"]["SITL"]["ardupilot_dir"]}', shell=False)
    subprocess.Popen(['.ardupilot/bin/python3', '.ardupilot/bin/mavproxy.py', f'--master=tcp:127.0.0.1:{port+56}', f'--out=tcpin:0.0.0.0:{port+87}', f'--out=tcpin:0.0.0.0:{port+88}', '--daemon'], cwd=f'{config["CRM"]["SITL"]["ardupilot_dir"]}', shell=False)

    dss_id = '{type}{index:03d}'.format(type='dss', index=self._nextIndex)
    self._nextIndex += 1
    self._clients[dss_id] = {'name': 'crm_dss.py', 'desc': '', 'type': 'dss', 'owner': 'crm', 'ip': '', 'port': '', 'timestamp': self._now}
    dss.auxiliaries.spawnDaemon.spawnDaemon('./crm_dss.py', 'crm_dss.py', f'--dss_id={dss_id}', f'--crm={self._ip}:{self._socket.port}', f'--drone={self._ip}:{port+88}', f'--dss_ip={self._ip}', '--descr=dss->port 88 [SIM]', '--without-clearance-check', '--without-midstick-check', '--capabilities', 'C0', 'RTK', 'LMD', 'RGB', 'VIDEO', 'SIM')
    return dss.auxiliaries.zmq.ack(fcn)

  def _request_launch_sitl(self, msg: dict) -> dict:
    fcn = dss.auxiliaries.zmq.get_fcn(msg)

    # check arguments
    if not all(key in msg for key in ['id', 'client_ip']):
      return dss.auxiliaries.zmq.nack(fcn, 'bad arguments: {id, client_ip} is mandatory')

    id_ = msg['id']
    if id_ not in self._clients and id_ != 'root':
      return dss.auxiliaries.zmq.nack(fcn, 'unknown client id')

    port = self._socket.port

    # arducopter expects an interactive shell (mavproxy --daemon does not)
    subprocess.Popen(['build/sitl/bin/arducopter', '-S', '--model', '+', '--speedup', '1', '--home', f'{config["CRM"]["SITL"]["drone_2"]["lat"]},{config["CRM"]["SITL"]["drone_2"]["lon"]},{config["CRM"]["SITL"]["drone_2"]["alt"]},{config["CRM"]["SITL"]["drone_2"]["heading"]}', f'--defaults={config["CRM"]["SITL"]["ardupilot_dir"]}Tools/autotest/default_params/copter.parm', f'--base-port={port+51}', '-I0', '--sysid', '1'], cwd=f'{config["CRM"]["SITL"]["ardupilot_dir"]}', shell=False)
    subprocess.Popen(['.ardupilot/bin/python3', '.ardupilot/bin/mavproxy.py', f'--master=tcp:127.0.0.1:{port+51}', f'--out=tcpin:0.0.0.0:{port+81}', f'--out=tcpin:0.0.0.0:{port+82}', '--daemon'], cwd=f'{config["CRM"]["SITL"]["ardupilot_dir"]}', shell=False)

    subprocess.Popen(['build/sitl/bin/arducopter', '-S', '--model', '+', '--speedup', '1', '--home', f'{config["CRM"]["SITL"]["drone_3"]["lat"]},{config["CRM"]["SITL"]["drone_3"]["lon"]},{config["CRM"]["SITL"]["drone_3"]["alt"]},{config["CRM"]["SITL"]["drone_3"]["heading"]}', f'--defaults={config["CRM"]["SITL"]["ardupilot_dir"]}Tools/autotest/default_params/copter.parm', f'--base-port={port+61}', '-I1', '--sysid', '2'], cwd=f'{config["CRM"]["SITL"]["ardupilot_dir"]}', shell=False)
    subprocess.Popen(['.ardupilot/bin/python3', '.ardupilot/bin/mavproxy.py', f'--master=tcp:127.0.0.1:{port+61}', f'--out=tcpin:0.0.0.0:{port+83}', f'--out=tcpin:0.0.0.0:{port+84}', '--daemon'], cwd=f'{config["CRM"]["SITL"]["ardupilot_dir"]}', shell=False)

    subprocess.Popen(['build/sitl/bin/arducopter', '-S', '--model', '+', '--speedup', '1', '--home', f'{config["CRM"]["SITL"]["drone_4"]["lat"]},{config["CRM"]["SITL"]["drone_4"]["lon"]},{config["CRM"]["SITL"]["drone_4"]["alt"]},{config["CRM"]["SITL"]["drone_4"]["heading"]}', f'--defaults={config["CRM"]["SITL"]["ardupilot_dir"]}Tools/autotest/default_params/copter.parm', f'--base-port={port+71}', '-I2', '--sysid', '3'], cwd=f'{config["CRM"]["SITL"]["ardupilot_dir"]}', shell=False)
    subprocess.Popen(['.ardupilot/bin/python3', '.ardupilot/bin/mavproxy.py', f'--master=tcp:127.0.0.1:{port+71}', f'--out=tcpin:0.0.0.0:{port+85}', f'--out=tcpin:0.0.0.0:{port+86}', '--daemon'], cwd=f'{config["CRM"]["SITL"]["ardupilot_dir"]}', shell=False)

    dss_id = '{type}{index:03d}'.format(type='dss', index=self._nextIndex)
    self._nextIndex += 1
    self._clients[dss_id] = {'name': 'crm_dss.py', 'desc': '', 'type': 'dss', 'owner': 'crm', 'ip': '', 'port': '', 'timestamp': self._now}
    dss.auxiliaries.spawnDaemon.spawnDaemon('./crm_dss.py', 'crm_dss.py', f'--dss_id={dss_id}', f'--crm={self._ip}:{self._socket.port}', f'--drone={self._ip}:{port+82}', f'--dss_ip={self._ip}', '--descr=dss->port 82 [SIM]', '--without-clearance-check', '--without-midstick-check', '--capabilities', 'C0', 'RGB', 'SIM')

    dss_id = '{type}{index:03d}'.format(type='dss', index=self._nextIndex)
    self._nextIndex += 1
    self._clients[dss_id] = {'name': 'crm_dss.py', 'desc': '', 'type': 'dss', 'owner': 'crm', 'ip': '', 'port': '', 'timestamp': self._now}
    dss.auxiliaries.spawnDaemon.spawnDaemon('./crm_dss.py', 'crm_dss.py', f'--dss_id={dss_id}', f'--crm={self._ip}:{self._socket.port}', f'--drone={self._ip}:{port+84}', f'--dss_ip={self._ip}', '--descr=dss->port 84 [SIM]', '--without-clearance-check', '--without-midstick-check', '--capabilities', 'RTK',  'RGB', 'VIDEO', 'SPOTLIGHT', 'SIM')

    dss_id = '{type}{index:03d}'.format(type='dss', index=self._nextIndex)
    self._nextIndex += 1
    self._clients[dss_id] = {'name': 'crm_dss.py', 'desc': '', 'type': 'dss', 'owner': 'crm', 'ip': '', 'port': '', 'timestamp': self._now}
    dss.auxiliaries.spawnDaemon.spawnDaemon('./crm_dss.py', 'crm_dss.py', f'--dss_id={dss_id}', f'--crm={self._ip}:{self._socket.port}', f'--drone={self._ip}:{port+86}', f'--dss_ip={self._ip}', '--descr=dss->port 86 [SIM]', '--without-clearance-check', '--without-midstick-check', '--capabilities', 'LMD', 'RTK', 'SIM')

    return dss.auxiliaries.zmq.ack(fcn)

  def _request_register(self, msg: dict) -> dict:
    fcn = dss.auxiliaries.zmq.get_fcn(msg)

    # check arguments
    if not all(key in msg for key in ['name', 'desc', 'type', 'ip', 'port', 'capabilities']):
      return dss.auxiliaries.zmq.nack(fcn, 'bad arguments: {name, desc, type, ip, port, capabilities} are mandatory')

    if not dss.auxiliaries.zmq.valid_ip(msg['ip']):
      return dss.auxiliaries.zmq.nack(fcn, f'bad ip: {msg["ip"]}')

    if not isinstance(msg['port'], int) or msg['port'] < 1000:
      return dss.auxiliaries.zmq.nack(fcn, f'bad port: {msg["port"]}')

    if msg['type'] not in self._types:
      return {'fcn': 'nack', 'call': fcn, 'description': 'unknown client type'}

    if 'id' in msg and msg['id']:
      id_ = msg['id']
      if id_ not in self._clients:
        return dss.auxiliaries.zmq.nack(fcn, 'unknown client id')

      if self._clients[id_]['ip']:
        return dss.auxiliaries.zmq.nack(fcn, 'client is already bound to endpoint')

      # double-check the name and type attributes
      if not all(msg[key] == self._clients[id_][key] for key in ['name', 'type']):
        return dss.auxiliaries.zmq.nack(fcn, 'unexpected name or type')

      self._clients[id_]['ip'] = msg['ip']
      self._clients[id_]['port'] = msg['port']
      self._clients[id_]['desc'] = msg['desc']
      #Store capabilities as a set for easy comparison. The casefold makes sure that the comparison is not case sensitive
      self._clients[id_]['capabilities'] = msg['capabilities']
      self._clients[id_]['timestamp'] = self._now
    else:
      # delete dss if one with same ip exists
      if msg['type'] == 'dss':
        for client_id, client in self._clients.items():
          if client['ip'] == msg['ip'] and client['type'] == msg['type']:
            if self._now - client['timestamp'] < 20:
              return dss.auxiliaries.zmq.nack(fcn, 'dss with same ip found')
            else:
              self._logger.warning('stale dss with same ip found and replaced')
              self._logger.warning(f'deleting {client_id} {self._clients[client_id]}')
              del self._clients[client_id]

      id_ = '{type}{index:03d}'.format(type=msg['type'], index=self._nextIndex)
      self._nextIndex += 1
      self._clients[id_] = {'name': msg['name'], 'type': msg['type'], 'capabilities': msg['capabilities'], 'desc': msg['desc'], 'owner': 'crm', 'ip': msg['ip'], 'port': msg['port'], 'timestamp': self._now}
    #Publish that a new client has been added to the list
    client_list = self._get_clients()
    self._pub_socket.publish('clients', client_list)
    if msg['type'] == 'dss':
      self._task_queue.add(self.task_start_battery_stream, id_)

    return dss.auxiliaries.zmq.ack(fcn, {'id': id_})

  def _request_release_drone(self, msg: dict) -> dict:
    fcn = dss.auxiliaries.zmq.get_fcn(msg)

    # check arguments
    if not all(key in msg for key in ['id', 'id_released']):
      return dss.auxiliaries.zmq.nack(fcn, 'bad arguments: {id, id_released} are mandatory')

    id_ = msg['id']
    if id_ not in self._clients:
      return dss.auxiliaries.zmq.nack(fcn, f'unknown client id: {id}')

    id_released = msg['id_released']
    if id_released not in self._clients:
      return dss.auxiliaries.zmq.nack(fcn, f'unknown client id (id_released): {id_released}')

    self._task_queue.add(self.task_set_owner, id_released, 'crm')

    # send rtl for now!
    self._task_queue.add(self.task_rtl, id_released)

    return dss.auxiliaries.zmq.ack(fcn)

  def _request_restart(self, msg: dict) -> dict:
    fcn = dss.auxiliaries.zmq.get_fcn(msg)

    # check arguments
    if 'id' not in msg:
      return dss.auxiliaries.zmq.nack(fcn, 'bad arguments: {id} are mandatory')

    if msg['id'] != 'root':
      return dss.auxiliaries.zmq.nack(fcn, 'prohibited')

    self._restart = True
    self._upgrade = False
    self._virgin = msg['virgin']
    self.kill()
    return dss.auxiliaries.zmq.ack(fcn)

  def _request_unregister(self, msg: dict) -> dict:
    fcn = dss.auxiliaries.zmq.get_fcn(msg)

    # check arguments
    if 'id' not in msg:
      return dss.auxiliaries.zmq.nack(fcn, 'bad arguments: {id} is mandatory')

    id_ = msg['id']
    if id_ not in self._clients:
      return dss.auxiliaries.zmq.nack(fcn, 'unknown client id')

    for client_id, client in self._clients.items():
      if client['owner'] == id_ and client['type'] == 'dss':
        self._task_queue.add(self.task_set_owner, client_id, 'crm')

    self._logger.warning(f'deleting {id_} {self._clients[id_]}')
    del self._clients[id_]
    client_list = self._get_clients()
    self._pub_socket.publish('clients', client_list)
    return dss.auxiliaries.zmq.ack(fcn)

  def _request_upgrade(self, msg: dict) -> dict:
    fcn = dss.auxiliaries.zmq.get_fcn(msg)

    # check arguments
    if 'id' not in msg:
      return dss.auxiliaries.zmq.nack(fcn, 'bad arguments: {id} are mandatory')

    if msg['id'] != 'root':
      return dss.auxiliaries.zmq.nack(fcn, 'prohibited')

    self._restart = True
    self._upgrade = True
    self._virgin = msg['virgin']
    self.kill()
    return dss.auxiliaries.zmq.ack(fcn)

#--------------------------------------------------------------------#

def _main():
  # parse command-line arguments
  parser = argparse.ArgumentParser(description='CRM "Drone Swarm Controller"', allow_abbrev=False, add_help=False)
  parser.add_argument('-h', '--help', action='help', help=argparse.SUPPRESS)
  parser.add_argument('--ip', type=str, default=config['CRM']["default_crm_ip"], help='public ip of the CRM server', required=False)
  parser.add_argument('--log', type=str, default='debug', help='logging threshold')
  parser.add_argument('--port', type=int, default=config['CRM']["default_crm_port"], help='defines the port for the ctrl-reply socket', required=False)
  parser.add_argument('--stdout', action='store_true', help='enables logging to stdout')
  parser.add_argument('--virgin', action='store_true', help='defines if to start from a backup or not')
  args = parser.parse_args()

  subnet = dss.auxiliaries.zmq.get_subnet(port=args.port)
  dss.auxiliaries.logging.configure('crm.log', stdout=args.stdout, rotating=True, loglevel=args.log, subdir=subnet)

  crm = CRM(args.ip, args.port, virgin=args.virgin)
  try:
    crm.main()
  except KeyboardInterrupt:
    logging.warning('shutdown due to keyboard interrupt')
  except:
    logging.error(traceback.format_exc())
  finally:
    if crm._upgrade:
      logging.info('downloading the latest version')
      dss.auxiliaries.git.pull()
    if crm._restart:
      logging.info('restarting the service')
      if crm._virgin:
        dss.auxiliaries.spawnDaemon.spawnDaemon('./crm.py', 'crm.py', f'--ip={args.ip}', f'--port={args.port}', '--virgin')
      else:
        dss.auxiliaries.spawnDaemon.spawnDaemon('./crm.py', 'crm.py', f'--ip={args.ip}', f'--port={args.port}')
    crm.kill()

#--------------------------------------------------------------------#

if __name__ == '__main__':
  _main()
