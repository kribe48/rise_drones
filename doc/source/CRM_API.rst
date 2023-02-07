.. |DSS| replace:: Drone Safety System
.. |CRM| replace:: Central Resource Controller

.. _crmapi:

Central Resource Manager API
============================

.. index:: CRM, Central Resource Manager


The Central Resource Manager (CRM) manages resources in the RISE drone
platform. RISE hosts the CRM on a server based in Kista and the way to
access it is via an OpenVPN-connection. The CRM can be hosted on any
unix machine.

Communication
-------------

.. index:: CRM; Communication

The |CRM| offers two external interfaces towards all clients: the CRM
Ctrl Reply-socket for sending requests to and the CRM Info
Publish-socket that publishes the client lists as soon as there are
changes. API for the reply-socket is described in
:ref:`crmcontrolAPI`.

The CRM is available for all connecting ip-numbers on a given port.
RISE hosts several CRM instances on the same server so the port
numbers are not fixed. RISE uses different subnets in the VPN solution
in combination with firewall settings to separate different CRM
instances and clients running different operations. Clients from one
subnet can only communicate with the assigned CRM instance and to
other clients on the same subnet.

The port of the CRM running on each subnet is calculated as
subnet*100, where subnet can be identified from the IP-address like
so: 10.44.subnet.xxx.

The IP (VPN) address to the RISE-server called dronehost is
``10.44.160.10``.

The dronehost also hosts a web server with visualisation of crm
status, it is reached at ''10.44.160.10'', port '80'.

The port used for Info Publish-socket is not deterministic must be
requested using the :ref:`fcninfo`.

..  The standard ip and port are ``10.44.160.1:5556`` and must be
.. specified as command line arguments when starting the service:
.. ``./crm.py --ip 10.44.160.1 --port 5556``. All clients must know this
.. information in order to be able to connect to the correct ip/port. Several instances of the CRM can run on the same host why using the correct port is essential.

.. code-block:: text
  :caption: Usage of CRM service

  > ./crm.py --help
  usage: crm.py --ip IP --port PORT [--stdout] [--virgin]

  CRM "Central Resource Manager"

  optional arguments:
    --ip IP      public ip of the CRM server
    --port PORT  defines the port for the ctrl-reply socket
    --stdout     enables logging to stdout
    --virgin     defines if to start from a backup or not



.. _crmcontrolAPI:

CRM Ctrl-link API
-----------------
.. index:: CRM; Ctrl-link API

General
~~~~~~~

The ZeroMQ REQ/REP interface takes function calls as JSON objects with two
mandatory keys, "fcn" and "id", the string values are the function
name and the application id. Additional keys are described in this API
chapter. Each function call gets an ack or a nack where the key "call"
holds the name of the calling function. A generic example follows:

Function call from client to |CRM|:

.. code-block:: json
  :caption: Generic function call
  :linenos:

  {
    "fcn": "<function name>",
    "id": "<requestor id>"
  }

Response from |CRM| is an ack or a nack. The key "call" carries the
name of the function called. Some functions uses the ack reply to
transfer data, refer to API. A nack includes the key "description"
that carries a nack description string.

.. code-block:: json
  :caption: Generic ack response
  :linenos:

  {
    "fcn": "ack",
    "call": "<function_name>"
  }


.. code-block:: json
  :caption: Generic nack response
  :linenos:

  {
    "fcn": "nack",
    "call": "<function name>",
    "description": "Some text describing the issue"
  }


.. _fcnregister:

Fcn: register
~~~~~~~~~~~~~

.. compatibility:: badge
  :crm: implemented

All clients (i.e applications and DSSs) in the network registers to
the CRM. It is done via the function ``register``. The CRM will reply
with a unique id that the client from this point must use in all calls
to all clients, including calls to the CRM.

The key ``id`` must be set to an empty string (see note below though).
Set keys ``name`` and ``description`` per your own choice. For key
``type`` supply your type: 'da' for drone application, 'dsa' for drone
support application and 'dss' for DSS. Also provide the local ip
address as a string in key ``ip`` and your reply port as an in in key
``port``, this is how other clients will make contact with your
client.

All clients must provide a list of ``capabilities``. However, note that
this list is allowed to be empty. Each capability is represented as a string.
The lists of capabilities are used by the CRM to allocate available resources when
applications require a drone with certain capabilities to perform a task. The following capabilities are supported:

* SIM - Drone is simulated
* REAL - Drone is not simulated
* C0 - Drone is C0 compatible, below 250g. Note second char is a zero - Charlie Zero.
* RTK - RTK compatible
* RGB - RGB camera compatible
* IR - IR camera compatible
* LMD - Drone can do last mile delivery, can carry and drop load.
* STREAM - Drone can stream video
* SPOTLIGHT - Drone has a spotlight

If the CRM responds with an ack and the registering client is DSS it
shall set it's owner to 'crm'.

.. note::
  When register is called by a client, it is unaware of its id (exceptions exist). Use
  empty string for id unless CRM initiated your process and already
  allocated a specific id.


.. code-block:: json
  :caption: Function call: **register**
  :linenos:

  {
    "fcn": "register",
    "id": "",
    "name": "DSS HX003",
    "desc": "<description>",
    "capabilities": ["C0", "REAL"],
    "type": "dss",
    "ip": "<ip>",
    "port": 1234
  }

The reply holds the unique id that is used in all communication.

.. code-block:: json
  :caption: Reply: **register**
  :linenos:

  {
    "fcn": "ack",
    "call": "register",
    "id": "<assigned client id>"
  }

**Nack reasons:**
  - bad arguments
  - bad ip

.. _fcnunregister:

Fcn: unregister
~~~~~~~~~~~~~~~

.. compatibility:: badge
  :crm: implemented

The function unregister is used to tell CRM that a client will not
longer be available on the network. The CRM replies with an ack if the
id is currently registered, otherwise nack.

If the CRM responds with an ack and the calling client is DSS it shall
set it's owner to 'da000'.

.. code-block:: json
  :caption: Function call: **unregister**
  :linenos:

  {
    "fcn": "unregister",
    "id": "<requestor id>"
  }

**Nack reasons:**
  - bad arguments
  - unknown requestor id

.. _fcninfo:

Fcn: get_info
~~~~~~~~~~~~~~

.. compatibility:: badge
  :crm: implemented

The function get_info requests status information of the CRM.

.. code-block:: json
  :caption: Function call: ``get_info``
  :linenos:

  {
    "fcn": "info",
    "id": "<requestor id>"
  }

.. code-block:: json
  :caption: Reply: ``get_info``
  :linenos:

  {
    "fcn": "ack",
    "call": "info",
    "id": "<replier id>",
    "info_pub_port": 1234,
    "data_pub_port": 5678
    "version": "<version>",
    "git_version": "<version>-<hash>"
  }

.. _fcngetdrone:

Fcn: get_drone
~~~~~~~~~~~~~~

.. compatibility:: badge
  :crm: implemented

The function get_drone requests a drone resource from the CRM. Specific capabilities
or unique drone id can be requested. It is mandatory to use one of
the two arguments "capabilities" and "force".

.. code-block:: json
  :caption: Function call: **get_drone** with capabilities
  :linenos:

  {
    "fcn": "get_drone",
    "id": "<requestor id>",
    "capabilities": ["RGB", "RTK"]
  }

.. code-block:: json
  :caption: Function call: **get_drone** with forced id
  :linenos:

  {
    "fcn": "get_drone",
    "id": "<requestor id>",
    "force": "<forced id>"
  }


The CRM replies with id and endpoint information:

.. code-block:: json
  :caption: Reply: **get_drone**
  :linenos:

  {
    "fcn": "ack",
    "call": "get_drone",
    "id": "<assigned drone id>",
    "ip": "<ip>",
    "port": 1234
  }

**Nack reasons:**
  - bad arguments
  - unknown requestor id
  - unknown forced id
  - forced id not available
  - forced id is stale
  - No available drone with requested capabilities

.. _fcncrmgetperformance:

Fcn: get_performance
~~~~~~~~~~~~~~~~~~~~~~

.. compatibility:: badge
  :crm: implemented

The function get_performance requests the CRM to reply with information about the performance of the computer where the CRM is running,
including CPU, memory and load.

.. code-block:: json
  :caption: Function call: **get_performance**
  :linenos:

  {
    "fcn": "get_performance",
    "id": "<requestor id>"
  }
The CRM replies with an ack and a string which captures the performance information:

.. code-block:: json
  :caption: Reply: **get_performance**
  :linenos:

  {
    "fcn": "ack",
    "call": "get_performance",
    "performance": "000.0% @ 1701.6182499999998MHz x 24 (000%, 000%, 000%) - 005.6% of 20048MB - time 07:40:19"
  }
.. _fcncrmgetprocesses:
Fcn: get_processes
~~~~~~~~~~~~~~~~~~

.. compatibility:: badge
  :crm: implemented

The function get_processes is designed to be used by a front-end application, in order to
present the active processes on the computer where the CRM is running. Each process will be tagged
with a 'killable' flag, and only the processes associated with the project in the request will be
'killable'.

.. code-block:: json
  :caption: Function call: **get_processes**
  :linenos:

  {
    "fcn": "get_processes",
    "id": "<requestor id>",
    "project": "<project name>"
  }

The CRM replies with an ack and a list of all the processes in JSON-format

.. code-block:: json
  :caption: Reply: **get_processes**
  :linenos:

  {
    "fcn": "ack",
    "call": "get_processes",
    "processes": "[<info_object_1>, <info_object_2>]"
  }

where each info object contains the following information:

.. code-block:: json
  :caption: Info object from a get_processes call
  :linenos:

  {
    "project": "<project id>",
    "cmd": "python3 ./crm.py --ip 10.44.160.10 --port 16300",
    "memory_percent": "1.1",
    "cpu_percent": "0.1",
    "killable": true,
    "created": "2023-01-03 10:26:54",
    "pid": 34253,
    "name": "process name"
  }

.. _fcncrmkillprocess:

Fcn: kill_process
~~~~~~~~~~~~~~~~~~
This function request the CRM to kill a specific process. Use with caution! It is intended to be used by the front-end,
which only presents the 'killable' processes to the user. This function is only acked when the requester is a root application.

.. code-block:: json
  :caption: Function call: **kill_process**
  :linenos:

  {
    "fcn": "kill_process",
    "id": "<requestor id>",
    "pid": "<process id>"
  }

.. _fcncrmreleasedrone:

Fcn: release_drone
~~~~~~~~~~~~~~~~~~

.. compatibility:: badge
  :crm: implemented

The function release_drone can be called when as soon as a dss "is
parked". CRM will take back the ownership and the drone application
can disconnect from the dss.

.. code-block:: json
  :caption: Function call: **release_drone**
  :linenos:

  {
    "fcn": "release_drone",
    "id": "<requestor id>",
    "id_released": "<dss id>"
  }

The CRM replies with an ack if the requestor is the current owner of the
dss, otherwise nack:

.. code-block:: json
  :caption: Reply: **release_drone**
  :linenos:

  {
    "fcn": "ack",
    "call": "release_drone"
  }


.. _fcnhandover:

Fcn: handover
~~~~~~~~~~~~~

.. compatibility:: badge
  :crm: -

The function handover is used to pass on a drone to an other
appliction, for example during a drone swap manouver. If the drone is
handed over to a non existing application or if the application does
not receive the new drone CRM will take ownershop of the drone.

.. code-block:: json
  :caption: Function call: **handover**
  :linenos:

  {
    "fcn": "handover",
    "id": "<requestor id>",
    "id_released": "<dss id>",
    "id_new_owner": "<new_owner_id>"
  }


**Nack reasons:**
  - requestor is not current owner

.. _fcnlaunchapp:

Fcn: launch_app
~~~~~~~~~~~~~~~

.. compatibility:: badge
  :crm: implemented

The function launch_app requests CRM to launch the app specified by
the key "app". The argument is the filename complete filename of the
process to start.

It can take some time to find available ports for the launched app.
Therefore, the reply does not hold enpoint information, but id
information. The user must call :ref:`fcnclients` and look for the
client id until the enpoint information is available.

The command takes the optional argument `extra_args`, which can be
skipped completly. If specified though, it must be a list of strings
which will be passed directly to the application as command line
arguments.

.. code-block:: json
  :caption: Function call: **launch_app**
  :linenos:

  {
    "fcn": "launch_app",
    "id": "<requestor id>",
    "app": "app_monitor.py",
    "extra_args": ["--log=debug"]
  }

The CRM replies with an ack and the id of the app just launched.

.. code-block:: json
  :caption: Reply: **launch_app**
  :linenos:

  {
    "fcn": "ack",
    "call": "launch_app",
    "id": "<assigned application id>"
  }


.. _fcnclients:


Fcn: clients
~~~~~~~~~~~~

.. compatibility:: badge
  :crm: implemented

The function clients requests a JSON-formatted string which contains all connected clients. The key
"filter" can be used to filer only the matching client id's of
interest, for example "dss" to get all connected dss's, "dss001" to
get a specific dss or an empty string "" to get all clients.  In the return
value there is a JSON struct with id's a keys holding JSON structs with all info.

.. code-block:: json
  :caption: Function call: **clients**
  :linenos:

  {
    "fcn": "clients",
    "id": "<requestor id>",
    "filter": "<client id filter>"
  }

The CRM replies with an ack and the client information that that matches the search patternand.

.. code-block:: json
  :caption: Reply: **clients**
  :linenos:

  {
    "fcn": "ack",
    "call": "clients",
    "clients": {
      "dss001": {"name": "hx-003", "desc": "Drone, green", "type": "dss", "owner": "da001", "ip": "<ip>", "port": 5789},
      "dss002": {"name": "hx-004", "desc": "Drone, blue", "type": "dss", "owner": "crm", "ip": "<ip>", "port": 5789},
      "da020": {"name": "AppKeyboard", "desc": "test application for debugging", "type": "da", "owner": "crm", "ip": "<ip>", "port": 5789}
      }
  }

**Nack reasons:**
  - bad arguments
  - unknown requestor id


.. _fcnapplost:

Fcn: app_lost
~~~~~~~~~~~~~

.. compatibility:: badge
  :crm: implemented
  :ardupilot: -
  :dji: -

The function app_lost is called by a DSS that has lost the link to its
application owner. This happens when no hearbeat message has been
received in the last 5 seconds, or if the application called
:ref:`fcndisconnect`.

.. code-block:: json
  :caption: Function call: **app_lost**
  :linenos:

  {
    "fcn": "app_lost",
    "id": "<requestor id>",
  }

The CRM replies with an ack. CRM can decide to recover or redistribute
the DSS or just let the DSS recover for it self.

.. code-block:: json
  :caption: Reply: **app_lost**
  :linenos:

  {
    "fcn": "ack",
    "call": "app_lost"
  }


.. _crminfoAPI:

CRM Info-link API
-----------------
.. index:: CRM; Info-link API

The CRM can publish information on a publish socket. The format for
each attribute is described in the following sections.

.. _CLIENTS:

CLIENTS - Client list updated
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. compatibility:: badge
  :crm: implemented

As soon as there are changes to the clients list of the CRM it will
publish the updated client list under topic "clients". The message is equal to the
response of the clients command, :ref:`fcnclients`.

.. code-block:: json
  :caption: Info-socket: Topic ``clients``
  :linenos:

  {
    "dss001": {"name": "hx-003", "desc": "Drone, green", "type": "dss", "owner": "da001", "ip": "<ip>", "port": 5789},
    "dss002": {"name": "hx-004", "desc": "Drone, blue", "type": "dss", "owner": "crm", "ip": "<ip>", "port": 5789},
    "da20": {"name": "AppKeyboard", "desc": "test application for debugging", "type": "da", "owner": "crm", "ip": "<ip>", "port": 5789}
  }



Flows
-----

Below follows some flows that helps describing how the platform is
designed to be used.


.. _ownershipflow:

Drone ownership flow
~~~~~~~~~~~~~~~~~~~~

When using the |CRM| each |DSS| instance has its owner that has been
negotiated with the |CRM|. The |CRM| can also make decisions to
reallocate the resources among the clients based on priorities. The
ownership flow is the following.

Flow with one DSS, one application and the CRM:
_______________________________________________

1. The DSS sends the register command to the CRM. The CRM responds
with ``ack`` and a unique identifier for the client. The CRM owns the
client.

.. mermaid::

  sequenceDiagram
  dss001 ->> +CRM: register (type, ip, port)
  CRM -->> -dss001: ack (id=dss001)

2. An application (e.g. ``da001``) requests a drone from the CRM by
issuing :ref:`fcngetdrone`. CRM assigns a DSS (e.g. ``dss001``) to the
application by calling the function :ref:`fcnsetowner`. After that,
the application can control the DSS. Note: The application will not
get notified, but can easily check the ownership with the
:ref:`fcnclients` command.

.. mermaid::

  sequenceDiagram
  da001 ->> +CRM: get_drone
  CRM -->> -da001: ack (id=dss001)

  CRM ->> +dss001: set_owner (owner=da001)
  dss001 -->> -CRM: ack

  loop
    da001 ->> +CRM: clients (filter=dss001)
    CRM -->> -da001: ack
  end

3. As the application (e.g. ``da001``) has finished it's mission, it
issues :ref:`fcncrmreleasedrone` to the CRM. The CRM then takes
ownership of the DSS (e.g. ``dss001``) by calling :ref:`fcnsetowner`.
Note: It is good practice for the application to monitor the ownership
of the DSS and first shutdown once the ownership is successfully
transferred back to the CRM.

.. mermaid::

  sequenceDiagram
  da001 ->> +CRM: release_drone
  CRM -->> -da001: ack

  CRM ->> +dss001: set_owner (owner=crm)
  dss001 -->> -CRM: ack

  loop
    da001 ->> +CRM: clients (filter=dss001)
    CRM -->> -da001: ack
  end


Flow where there is a drone change:
_____________________________________

Preconditions: dsa001 is the owner of dss001, dsa001 has called CRM
for a drone replacement via launch_app. A drone helper application has
been launched (dsa002) and been assigned a drone (dss002) and is ready
to switch drones.

1. dsa002 parks dss002 and issues :ref:`fcncrmreleasedrone` to CRM.
The CRM claims ownership by calling :ref:`fcnsetowner` to dss002 and
maintains it's heartbeats to dss002.

.. mermaid::

  sequenceDiagram
  participant CRM
  participant dss001
  participant dss002
  participant dsa001
  participant dsa002

  Note left of CRM: step 1
  dsa002 -->> dss002: park

  dsa002 ->> +CRM: release_drone
  CRM -->> -dsa002: ack

  CRM ->> +dss002: set_owner (owner=crm)
  dss002 -->> -CRM: ack

  loop
    dsa002 ->> +CRM: clients (filter=dss002)
    CRM -->> -dsa002: ack
  end

  CRM -->> dss002: heart_beat

2. dsa002 calls :ref:`fcnappreleasedss` to dsa001, and starts issuing
:ref:`getowner` to dss001 in 1Hz - waiting to be able to get the drone
assigned from the CRM.

.. mermaid::

  sequenceDiagram
  participant CRM
  participant dss001
  participant dss002
  participant dsa001
  participant dsa002

  Note left of CRM: step 2
  dsa002 -->> dsa001: release_dss

  loop
    dsa002 ->> +CRM: clients
    CRM -->> -dsa002: ack
  end

3. dsa001 parks dss001 and then issues :ref:`fcncrmreleasedrone` to
CRM. The CRM claims ownership by issuing :ref:`fcnsetowner` to dss001 and
maintains it's heartbeats.

.. mermaid::

  sequenceDiagram
  participant CRM
  participant dss001
  participant dss002
  participant dsa001
  participant dsa002

  Note left of CRM: step 3
  dsa001 -->> dss001: park

  dsa001 ->> +CRM: release_drone
  CRM -->> -dsa001: ack

  CRM ->> +dss001: set_owner (owner=crm)
  dss001 -->> -CRM: ack

  loop
    dsa001 ->> +CRM: clients (filter=dss001)
    CRM -->> -dsa001: ack
  end

  CRM -->> dss001: heart_beat

4. dsa001 issues :ref:`fcngetdrone` to the CRM. This triggers the CRM to set the ownership of
dss002 to dsa001 and dsa001 can continue mission.

.. mermaid::

  sequenceDiagram
  participant CRM
  participant dss001
  participant dss002
  participant dsa001
  participant dsa002

  Note left of CRM: step 4
  dsa001 ->> +CRM: get_drone
  CRM -->> -dsa001: ack (id=dss002)

  CRM ->> +dss002: set_owner (owner=dsa001)
  dss002 -->> -CRM: ack

  loop
    dsa001 ->> +CRM: clients (filter=dss002)
    CRM -->> -dsa001: ack
  end

5. dsa002 has noticed that dss001 is available and issues
:ref:`fcngetdrone` from CRM and gets the ownership of dss001.

.. mermaid::

  sequenceDiagram
  participant CRM
  participant dss001
  participant dss002
  participant dsa001
  participant dsa002

  Note left of CRM: step 5
  dsa002 ->> +CRM: get_drone
  CRM -->> -dsa002: ack (id=dss001)

  CRM ->> +dss001: set_owner (owner=dsa002)
  dss001 -->> -CRM: ack

  loop
    dsa002 ->> +CRM: clients (filter=dss001)
    CRM -->> -dsa002: ack
  end


CRM owns flying DSS:
____________________

Preconditions: CRM has the ownership of a flying DSS.

.. mermaid::

  sequenceDiagram
  participant App_SRTL
  participant DSS
  participant CRM


  CRM ->> +App_SRTL:(start app with: -id, -ip, -port, -dss)

  App_SRTL ->> +CRM: (get_drone(dss))
  CRM -->> -App_SRTL: (ack)
  CRM ->> +DSS: (set_owner(App_SRTL))
  DSS --> -CRM: (ack)
  Note left of App_SRTL: until ack
  loop
    App_SRTL ->> +DSS: (heartbeat)
    DSS -->> -App_SRTL: (ack/nack)
  end

  App_SRTL ->> +DSS: (dss_srtl)
  DSS -->> -App_SRTL: (ack)

  Note left of App_SRTL: until false
  loop
    App_SRTL ->> +DSS: (get_armed)
    DSS -->> -App_SRTL: (true/false)
  end

  App_SRTL ->> +CRM: (release_drone)
  CRM -->> -App_SRTL: (ack)

  App_SRTL ->> +CRM: (unregister)
  CRM -->> -App_SRTL: (ack)
  Note left of App_SRTL: App_SRTL exit


TYRAmote sends follow_me = fasle:
_________________________________

Preconditions: TYRAmote, TYRApp, DSS and CRM are connected and DSS is
following TYRAmote. TYRAmote sends follow_me = false.

.. mermaid::

  sequenceDiagram
  participant TYRAmote
  participant TYRApp
  participant DSS
  participant CRM


  TYRAmote ->> + TYRApp: (follow_me = false)
  TYRApp -->> -TYRAmote: (ack)
  TYRApp ->> +DSS: (follow_stream = false)
  DSS -->> -TYRApp: (ack)
  TYRApp ->> +CRM: (release_drone)
  CRM -->> -TYRApp: (ack)
  CRM ->> +DSS: (set_owner = crm)
  DSS -->> -CRM: (ack)
  Note left of TYRAmote: Ref flow: CRM owns flying DSS


TYRAmote quits by unregister:
_____________________________

Preconditions: TYRAmote, TYRApp, DSS and CRM are connected and DSS is
following TYRAmote. TYRAmote quits by X-icon and therefore sends
unregister to CRM.

.. mermaid::

  sequenceDiagram
  participant TYRAmote
  participant TYRApp
  participant DSS
  participant CRM


  TYRAmote ->> + CRM: (unregister)
  CRM -->> -TYRAmote: (ack)
  CRM ->> +TYRApp: (release_dss)
  TYRApp -->> -CRM: (ack)
  TYRApp ->> +DSS: (hover)
  DSS -->> -TYRApp: (ack)
  TYRApp -> +CRM: (release_drone)
  CRM --> -TYRApp: (ack)
  Note left of TYRApp: TYRApp close()
  CRM ->> + DSS: (set_owner = crm)
  DSS -->> -CRM: (ack)
  Note left of TYRAmote: Ref flow: CRM owns flying DSS


TYRAmote crashes:
_________________

Preconditions: TYRAmote, TYRApp, DSS and CRM are connected and DSS is
following TYRAmote. TYRAmote crashes.

.. mermaid::

  sequenceDiagram
  participant TYRAmote
  participant TYRApp
  participant DSS
  participant CRM

  Note left of TYRAmote: TYRAmote crash
  TYRApp ->> +DSS: (hover)
  DSS -->> -TYRApp: (ack)
  TYRApp -> +CRM: (release_drone)
  CRM --> -TYRApp: (ack)
  Note left of TYRApp: TYRApp close()
  CRM ->> + DSS: (set_owner = crm)
  DSS -->> -CRM: (ack)
  Note left of TYRAmote: Ref flow: CRM owns flying DSS



Drone change:
_____________

Preconditions: App, DSS1, DSS2 and CRM are connected. DSS1 is flown by
App and App has requested a drone cheange. Drone helper has started,
received DSS2 and taken off. DSS1 and DSS2 publishes LLA messages.

.. mermaid::

  sequenceDiagram
  participant App
  participant DSS1
  participant DroneHelper
  participant DSS2
  participant CRM

  DroneHelper ->> +DSS2: (set_alt, above DSS1)
  DSS2 -->> -DroneHelper: (ack)
  DroneHelper ->> +DSS2: (follow_stream, above DSS1)
  DSS2 -->> -DroneHelper: (ack)

  loop
    DroneHelper ->> DroneHelper: (Compare DSS1 and DSS2 pos)
  end

  DroneHelper ->> +DSS2: (hover)
  DSS2 -->> -DroneHelper: (ack)
  DroneHelper ->> +CRM: (handover, DSS2 to App)
  CRM -->> -DroneHelper: (ack)
  DroneHelper ->> + DroneHelper: (pub clients)

  CRM ->> +App: (push_dss)
  App -->> -CRM: (ack)

  App -->> +App: (pub clients)

  CRM ->> +DSS2: (set_owner, App)
  DSS2 -->> -CRM: (ack)

  App ->> +DSS1: (hover)
  DSS1 -->> -App: (ack)
  App ->> +CRM: (release_drone DSS1)
  CRM -->> -App: (ack)
  App ->> +App: (pub clients)




  CRM ->> +DSS1: (set_owner crm)
  DSS1 -->> -CRM: (ack)
  Note left of DSS1: CRM owns flying dss flow
