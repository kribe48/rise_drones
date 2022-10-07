.. |DSS| replace:: Drone Safety System

.. _geo_awareness:

API between DSS and Geo Awareness Module
========================================

The Geo Awareness Module (GAM) responds to requests from the DSS. DSS
sends a position; a position and course; or a mission for evaluation.
GAM checks the given arguments for all entities within the database
and responds. This chapter describes the communication setup and API
for it. GAM is be hosted on ground based server connected to the DSS
over VPN.

Communication
-------------

The communication is carried as JSON-messages via ZeroMQ. GAM acts as
a server and and opens up a ZeroMQ Reply socket, DSS will send
requests via a ZeroMQ Request socket.

The IP and port numbers used are described in Settings.json. The
programs should read their settings from this file. During test and
development, both the server and the client can have the same host, if
separating server and client, change the client socket ip to the
IP-adress of the server.

.. code-block:: json
  :caption: Settings.json-file

  {
    "GAMServerSocket": "tcp://*:5566",
    "GAMClientSocket": "tcp://localhost:5566"
  }


Performance Limitations
-----------------------

Computational power available is similar to a standard laptop, data
transfer rate can be assumed to be 200kb/s and a request shall not
take longer than 2s to respond to.

GAM API
-------

GAM offers an API towards the DSS (or other application). The link is
set up as a ZeroMQ Request Reply type. The application requests
replies from the GAM server and the GAM server responds to them.

General function call
~~~~~~~~~~~~~~~~~~~~~

General function call and ack/nack functions:

.. code-block:: json
  :caption: JSON object function call

  {
    "fcn": "the_name_of_the_function",
    "arg": {
      "arg1": 0,
      "arg2": "string_argument_example"
    }
  }


General response:

.. code-block:: json
  :caption: JSON object function call response

  {
    "fcn": "ack",
    "arg": "the_name_of_the_function"
  }

  {
    "fcn": "nack",
    "arg": "the_name_of_the_function",
    "arg2": "Some text or JSON-object describing the issue"
  }

Fcn: user_set_ok
~~~~~~~~~~~~~~~~

The function user_set is called when first connecting to the GAM. An
id string and contact information are sent as arguments. The contact
information is used to send notifications to the operator when needed.
|DSS| will aslo send notification via MAVLINK.

.. code-block:: json
  :caption: Function call: **user_set**

  {
    "fcn": "user_set"
    "arg": {
      "id": "my_id_string",
      "mail": "someone@mail.com",
      "mobile": "0046701234567"
    }
  }


Fcn: geo_pos_ok
~~~~~~~~~~~~~~~

The function geo_pos_ok requests a look up for a specific location
global frame: lat [decimal degrees], long[decimal degrees], alt
[meters a above sea level]. The GAM will respond with an ack if there
are no conflicts, otherwise it will respond with a nack and where arg2
holds the specific description of the issue as a list of JSON objects
describing the conflict(s). Severity can be 1, 2 or 3, meaning TBD.
Conflict could further describe the conflict, TBD.

.. code-block:: json
  :caption: Function call: **geo_pos_ok**

  {
    "fcn": "geo_pos_ok"
    "arg": {
      "id": "my_id_string",
      "lat": 58.123456,
      "long": 16.123456,
      "alt": 100
    }
  }

the nack response reports a list with all conflict(s):

.. code-block:: json
  :caption: Function call response: **geo_pos_ok**

  {
    "fcn": "nack",
    "arg": "geo_pos_ok",
    "arg2": [{
      "db_name": "the_name_of_the_database",
      "severity": 1,
      "conflict": "TBD"
    },{
      "db_name": "the_name_of_the_database",
      "severity": 1,
      "conflict": "TBD"
    }]
  }

Fcn: geo_course_ok
~~~~~~~~~~~~~~~~~~

The function geo_course_ok requests a look up for a course over a
range given from a specific location global frame: course [degrees
true north, 0-359], range [m], lat [decimal degrees], long [decimal
degrees], alt [meters a above sea level].

The GAM will respond with an ack if there are no conflicts and a nack
if there are any conflicts on the course along the given range. The
nack response arg2 holds a list of JSON objects describing
conflict(s). Severity can be 1, 2 or 3, meaning TBD. Conflict could
further describe the conflict, TBD. Distance is meters from reference
point to conflict.

.. code-block:: json
  :caption: Function call: **geo_pos_ok**

  {
    "fcn": "geo_course_ok",
    "arg": {
      "id": "my_id_string"
      "course": 359,
      "range": 500,
      "lat": 58.123456,
      "long": 16.123456,
      "alt": 100
    }
  }

the nack response reports a list of JSON objects with all conflict(s):

.. code-block:: json
  :caption: Function call response: **geo_pos_ok**

  {
    "fcn": "nack",
    "arg": "geo_course_ok",
    "arg2": [{
      "db_name": "the_name_of_the_database",
      "severity": 1,
      "conflict": "TBD",
      "distance": 154
    },{
      "db_name": "the_name_of_the_database",
      "severity": 1,
      "conflict": "TBD",
      "distance": 202
    }]
  }


Fcn: geo_mission_ok
~~~~~~~~~~~~~~~~~~~

The function geo_mission_ok requests a look up for a mission
consisting of a number of waypoints given in lat [decimal degrees],
long[decimal degrees], alt [meters a above reference altitude],
ref_alt [reference alt meters above sea level]. The GAM will respond
with an ack if there are no conflicts flying on a straight line from
id0 to id1 to id2 to...idn. GAM will respond with a nack describing
the first conflict(s) on the route. The nack response specific
description of the issue is a list of JSON objects describing the
conflict(s). Severity can be 1, 2 or 3, meaning TBD.

.. note::
  The mission altitude is relative to launch altitude. The launch
  altitude given in AMSL is provided as the reference altitude. To
  obtain the mission AMSL altitude, add the reference altitude to each
  waypoint altitude.

.. code-block:: json
  :caption: Function call: **geo_pos_ok**

  {
    "fcn": "geo_mission_ok",
    "arg": {
      "id": "my_id_string",
      "ref_alt": 100,
      "mission": {
        "id0": {
          "lat": 57.776815,
          "lon": 16.528308,
          "alt": 20,
          "heading": -1,
          "speed": 5
        },
        "id1": {
          "lat": 57.776815,
          "lon": 16.528308,
          "alt": 20,
          "heading": -1,
          "speed": 5
        },
        "id2": {
          "lat": 57.776815,
          "lon": 16.528308,
          "alt": 20,
          "heading": -1,
          "speed": 5
        },
        "source_file": "Missions/LMD_A.plan",
        "route": "LMD_A-LMD_R"
      }
    }
  }

the nack response reports a list with all conflict(s) where the id
describes towards which wp the conflict occurs:

.. code-block:: json
  :caption: Function call response: **geo_mission_ok**

  {
    "fcn": "nack"
    "arg": "geo_mission_ok"
    "arg2": [{
      "wp-id": "id3",
      "db_name": "the_name_of_the_database",
      "severity": 1,
      "conflict": "TBD"
    },{
      "wp-id": "id3",
      "db_name": "the_name_of_the_database",
      "severity": 1,
      "conflict": "TBD"
    }]
  }
