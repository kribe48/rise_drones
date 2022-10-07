API between GLANA-application and GLANA-control
===============================================

In the GLANA integration a Lumenera 16059H is integrated to the drone
platform. In the architecture there are two single card computers and
three processes; DSS, GLANA-application and GLANA-control. DSS and
GLANA-application runs on a Raspberry Pi3B+, the GLANA-control runs on
a Jetson TX2 installed on a J120 carrier board. Raspberry Pi and
Jetson are connected via Ethernet where Jetson distributes DHCP.

The DSS offers an API towards GLANA-application, it is documented
earlier in this document. The GLANA-application and GLANA-control uses
the API described in this chapter.

Communication
-------------

The communication is carried as JSON-messages via ZeroMQ. Socket
description TBD. There are two ZMQ connections between application and
control: control-link and logdata-link. They are further described in
the following sections.


The IP number setup is as follows.

.. code-block:: json
  :caption: IP numbers

  {
    "Raspberry Pi": "192.168.0.2",
    "Jetson": "192.168.0.1"
  }


The ports used are described in Settings.json. The programs should
read their settings from this file.

.. code-block:: json
  :caption: Settings.json-file

  {
    "DSSServSocket": "tcp://*:5557",
    "DSSClientSocket": "tcp://localhost:5557",
    "DSSPubSocket": "tcp://*:5558",
    "DSSSubSocket": "tcp://192.168.2.2:5558",
    "GlanaClientSocket": "tcp://192.168.2.3:5562",
    "GlanaServSocket": "tcp://*:5562"
  }


Control-link
------------

The control link is set up as a Request and Reply type. The
GLANA-application will Request Replies from the GLANA-control.

General function call and ack/nack functions:

.. code-block:: json
  :caption: JSON object function call

  {
    "fcn": "the_name_of_the_function"
    "arg": {
      "arg1": 0,
      "arg2": "string_argument_example"
    }
  }


Response from GLANA-control.

.. code-block:: json
  :caption: JSON object function call response

  {
    "fcn": "ack"
    "arg": "the_name_of_the_function"
  }

  {
    "fcn": "nack"
    "arg": "the_name_of_the_function"
    "arg2": "Some text describing the issue"
  }


Fcn: up
~~~~~~~

The function up requests the GLANA-control to ack that it is alive. If
the message is received and interpreted correctly GLANA-control
replies with an ack, otherwise with a nack.

.. code-block:: json
  :caption: Function call: **up**

  {
    "fcn": "up"
    "arg": ""
  }


Fcn: start_camera
~~~~~~~~~~~~~~~~~

The function start_camera requests the GLANA-control to start camera
recording and save collected data at the path given as argument. If
the message is received and interpreted correctly GLANA-control
replies with an ack, otherwise with a nack.

.. code-block:: json
  :caption: Function call: **start_recording**

  {
    "fcn": "start_rec"
    "arg": "path/examplepath/example_path"
  }


Fcn: stop_camera
~~~~~~~~~~~~~~~~

The function stop_camera requests the GLANA-control to stop camera
recording. If the message is received and interpreted correctly
GLANA-control replies with an ack, otherwise with a nack.

.. code-block:: json
  :caption: Function call: **stop_recording**

  {
    "fcn": "stop_rec"
    "arg": ""
  }


Fcn: rec_ok
~~~~~~~~~~~

The function rec_ok requests the recording status from GLANA-control.
If the camera is recording GLANA-control shall reply with an ack, if
the camera is not recording GLANA-control shall reply with a nack.
This is a special use case for the ack/nack structure defined.

.. code-block:: json
  :caption: Function call: **rec_ok**

  {
    "fcn": "rec_ok"
    "arg": ""
  }


Logdata-link
------------

The logdata-link is set up as Publish Subscribe type. The
GLANA-application acquire the DSS to Publish data and GLANA-control
will Subscribe to data.

The logdata Published is in the formats described in the following
sections.

GPS data
~~~~~~~~

GPS data is given in the location global frame, lat [decimal
degreees], long[decimal degrees], alt [meters a above sea level]. Data
rate is around 3Hz.

.. code-block:: json
  :caption: Data: **location_global_frame**

  {
    "Data": "lgf",
    "lat": 58.3254094,
    "lon": 15.6324897,
    "alt": 114.1
  }


Attitude data
~~~~~~~~~~~~~

The attitude data is given in the copter coordinate system, r
[radians], p [radians], y [radians true north]. R, p and y is for
roll, pitch and yaw. Positive roll is leaning right, positive pitch is
nose up, yaw increases in clockwise direction. Data rate is
approximately 10Hz.

.. code-block:: json
  :caption: Data: **attitude**

  {
    "Data": "att",
    "r": -0.0018926148768514395,
    "p": 0.0014366497052833438,
    "y": 0.0123
  }



Gimbal attitude data
~~~~~~~~~~~~~~~~~~~~

The gimbal attitude data is given in the copter coordinate system, r
[radians], p [radians], y [radians true north]. R, p and y is for
roll, pitch and yaw. Positive roll is leaning right, positive pitch is
nose up, yaw increases in clockwise direction. Data rate is not known
yet..

.. code-block:: json
  :caption: Data: **gimbal_attitude**

  {
    "Data": "gatt",
    "r": -0.00189261,
    "p": 0.001436642,
    "y": 0.0123
  }
