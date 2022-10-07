AWARD Central executor and Drone executor API
=============================================

General
-------

This document further describes the interface between the Central
executor and the drone executors. The main protocol is described in
AWARD-Deliverable-D01 FINAL - v2.docx.

In general the communication is carried as JSON-messages via ZeroMQ
and there are two ZMQ links between Central executor and
DRONE-executors: one for command and control and one for status
update. The relevant parts for the drones are furter described in the
following sections.

.. %The IP number setup is as follows.
   %
   .. code-block:: json
  :caption: IP numbers, language=json,firstnumber=1]

   %{
   %  "HX_002": "25.28.54.88",
   %  "HX_003": "25.33.17.79"
   %  "P&S": "TBD"
   %}
   %


The drone executor flow
-----------------------

- Planner is connected to VPN.

- Drone is powered, pre-flight checklist is done, drone connects to
  VPN and awaits a plan.

- Central executor publishes a drone plan

- Drone operator sees the plan via text output from drone software.
  Drone operator loads the package and triggers the wait_for_ack by
  flipping a switch on transmitter when ready for takeoff.

  .. note::
    The wait for ack is completely unnecessary, but it strengthens the
    experience that the Central executor is in control of the drone.

- Central executor sends ack to drone. Drone continues the plan
  (takeoff).

- Notify is sent to tell central planner that the dock is empty

- Drone flies to one of three predefined destinations LMD_A, LMD_B,
  LMD_C.

- Drone lands.

- During unloads the package.

- Drone takes-off

- Drone sends notification to central executor and flies to the
  recovery station.

- Drone lands at drone recovery station, close to drone dock.

Settings
--------

For the drones the links are routed via VPN over the internet. The
ip-numbers and ports used are described in Settings.json:

.. code-block:: json
  :caption: Settings.json-file

  {
    "DSSServSocket": "tcp://*:5557",
    "DSSClientSocket": "tcp://localhost:5557",
    "DSSPubSocket": "tcp://*:5558",
    "DSSSubSocket": "tcp://192.168.2.2:5558",
    "CExeServSocket": "tcp://*:5559",
    "CExeClientSocket": "tcp://masked:5559",
    "CExePubSocket": "tcp://*:5564",
    "CExeSubSocket": "tcp://masked:5564"
  }


Control-link
------------

The control link is set up as a Publish and Subscribe type using
envelopes for addressing. The Central executor publishes plans and ack
messages that the executors subscribes to.

Fcn: set_plan
~~~~~~~~~~~~~

The function set_plan is used to assign an executor to certain tasks.
A typical drone plan looks like the example below. The explanation of
the different actions are described in AWARD-Deliverable-D01 FINAL -
v2.docx.

.. note::
  Two new actions are introduced: takeoff and land. Takeoff: commands
  the drone to take off to a certain altitude between 2 and 20m. Land:
  Commands the drone to land at the specified location.

.. code-block:: json
  :caption: Function call: **set_plan - a drone example**
  :linenos:

  {
  "fcn": "set_plan",
  "agent": "hx_002",
  "arg": [
    {
    "action": "load"
    "params": {
      "pallet": "p3",
      "location":"5",
      "max_duration": 9999
        }
    },
    {
    "action": "wait_for_ack",
    "params": {"ack_id": "ack_id"}
    },
    {
    "action": "takeoff"
    "params": {"height": 15}
    },
    {
    "action": "notify",
    "params": {"message": "message"}
    },
    {
    "action": "goto"
    "params": {
      "from": "5",
      "to":"LMD_A",
      "max_duration": 9999
        }
    },
    {
    "action": "land"
    "params": {"to": "LMD_A"}
    },
    {
    "action": "unload"
    "params": {
      "pallet": "p3",
      "location":"LMD_A",
      "max_duration": 9999
        }
    },
    {
    "action": "wait_for_ack",
    "params": {"ack_id": "ack_id"}
    },
    "action": "takeoff"
    "params": {"height": 15}
    },
    {
    "action": "notify",
    "params": {"message": "message"}
    },
    {
    "action": "goto"
    "params": {
      "from": "LMD_A",
      "to":"LMD_R",
      "max_duration": 9999
        }
    },
    {
    "action": "land"
    "params": {"to": "LMD_R"}
    }
    ]
  }


.. %Topic code snippet:
.. %socket.send_multipart([agent.name.encode(), json.dumps(json_function_call).encode()])

.. warning::
  max_duration will not be handled/respected by drone executors

Fcn: ack
~~~~~~~~

The function ack is used to unlock an executor that is waiting for
ack. It is sent with the destination executor as topic.

.. code-block:: json
  :caption: ack

  {
    "fcn": "ack",
    "arg": "ack_id"
  }


.. %Topic code snippet:
.. %socket.send_multipart([agent.name.encode(), json.dumps(json_function_call).encode()])


Status-link
-----------

The status-link is set up as a Request and Reply type. The Central
executor replies to requests from the executors.

Fcn: notify
~~~~~~~~~~~

The function notify function is triggered from the notify action in a
plan. It tells the central executor that the executor have reached a
certain point in the plan.

.. code-block:: json
  :caption: notify

  {
    "fcn": "notify",
    "agent": "hx_002",
    "arg": "message"
  }

.. code-block:: json
  :caption: notify reply
  
  {
    "fcn": "notify_reply"
    "arg": "ok"
  }


Fcn: wait
~~~~~~~~~

The wait function is triggered from the wait_for_ack action in a plan.
It tells the central executor that the executor have reached a certain
point in the plan and that the executor will sleep until it receives
the ack_id that was specified in the plan.

.. code-block:: json
  :caption: wait

  {
    "fcn": "wait",
    "agent": "hx_002",
    "arg": "ack_id"
  }

.. code-block:: json
  :caption: wait reply

  {
    "fcn": "wait_reply"
    "arg": "ok"
  }


Fcn: heartbit
~~~~~~~~~~~~~

The function heartbit is used by the executors to tell the Central
executor that they are a alive. The message is sent every 2 seconds
and the Central executor replies with an ok as per below.

.. code-block:: json
  :caption: heartbit

  {
    "fcn": "heartbit",
    "agent": "hx_002",
    "arg": null
  }

.. code-block:: json
  :caption: heartbit reply

  {
    "fcn": "heartbit_reply"
    "arg": "ok"
  }
