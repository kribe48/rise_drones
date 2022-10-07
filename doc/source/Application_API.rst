
.. _appapi:

Application API
===============

.. index:: Application, General

Applications are custom made, this is where the user creates an
application utilizing the API of the Drone Safety System. Each
application have to implement the general application support
described in this chapter.

Communication
-------------

.. index:: Application, Communication

Applications must host an Application Control Link. The Ctrl
Reply-Socket is used for helper applications to call functions and
receive ack/nack and information. Available commands are described in
:ref:`appcontrollapi`.

The socket ports for non CRM operations are described below. In CRM
operations the CRM will present the ip and Ctrl-Reply-socket port for
each client, and the publish port(s) can be requested by directly
connecting to the client of interest and issuing get_info. The sockets
are open for all connecting ip-numbers.

Since applications often run on the same ip as CRM, the port
number is dynamic.

.. code-block:: json
  :caption: Application Sockets port definition if **NOT** using CRM
  :linenos:

  {
    "Ctrl-Reply-socket": 5560
    "Info-Publish-Socket": 5000-6000
  }

.. _typicalFLOW:

Typical Flow
~~~~~~~~~~~~
An exampel of a typial flow for an Applicaiton when not using the CRM.

.. mermaid::

  sequenceDiagram
  Autopilot ->> +DSSctrl: Continous coms
  DSSctrl ->> +Autopilot: Continous coms


  loop
    Application ->> +DSSctrl: who_controls
    DSSctrl -->> -Application: APPLICATION
  end

  Application ->> +DSSctrl: upload_mission_LLA
  DSSctrl -->> -Application: ack

  Application ->> +DSSctrl: take_off(2m)
  DSSctrl -->> -Application: ack

  loop
    Application -->> +DSSctrl: get_posD
    DSSctrl -->> -Application: posD
  end

  Application -->> +DSSctrl: gogo  (start mission)
  DSSctrl -->> -Application: ack

  Application ->> +DSSctrl: data_stream(currentWP)
  DSSctrl -->> -Application: ack

  DSSinfo -->> +Application: currentWP

  Application ->> +DSSctrl: heart_beat
  DSSctrl -->> -Application: ack

  Application ->> +DSSctrl: DSSRtl
  DSSctrl -->> -Application: ack

  Note left of DSSctrl: Until nack
  loop
    Application ->> +DSSctrl: armed
    DSSctrl -->> -Application: ack/nack
  end

  Application ->> +DSSctrl: disconnect
  DSSctrl -->> -Application: ack

.. index:: Application: Ctrl-link API

.. _appcontrollapi:

Application API
---------------

General
~~~~~~~

Information is carried by JSON objects that are sent over the ZeroMQ
REQ/REP interface.

.. _fcnappreleasedss:

Fcn: release_dss DEPRICATED
~~~~~~~~~~~~~~~~~~~~~~~~~~~


The function ``release_dss`` requests the drone application to release
the control of the connected drone. The drone application must first
resolve possible dependencies, then stop the drone and finally release
it by calling CRM function  :ref:`fcncrmreleasedrone`.

The message contains a key ``id`` for requester id and a key
``action`` for informing the application if it's drone is being
replaced or if the application should quit. Valid strings for key
``action`` are "replace" and "quit".

If the key ``action`` is "replace" there is also a key ``new_dss`` with the id of the replacing dss.


.. code-block:: json
  :caption: Function call: ``release_dss`` DEPRICATED
  :linenos:

  {
    "fcn": "release_dsss",
    "id": "<requestor id>",
    "action": "replace",
    "new_dss": "<replacing dss id>"
  }

**Nack reasons:**
  - None

.. _fcnpushdss:

Fcn: push_dss
~~~~~~~~~~~~~~~~

The function ``push_dss`` is used when the CRM wants to push a new drone with corresponding DSS onto an application. If the message is nacked the CRM will take control of the DSS in question.

The message contains a key ``id`` for requester id and a key
``action`` for informing the application if it's drone is being
replaced or if the application should quit. Valid strings for key
``action`` are "replace" and "quit".

If the key ``action`` is "replace" there is also a key ``new_dss`` with the id of the replacing dss.


.. code-block:: json
  :caption: Function call: ``push_dss``
  :linenos:

  {
    "fcn": "push_dss",
    "id": "<requestor id>",
    "dss_id": "<replacing dss id>"
  }

**Nack reasons:**
  - Requestor not CRM
  - Application does not accept the dss

.. _fcnappgetinfo:

Fcn: get_info
~~~~~~~~~~~~~


The function ``get_info`` requests the drone application prove that it is
still alive and to share some connection information. It is typically
sent from the CRM every now and then. The application answers with an
ack and applicable information, the two publish ports are optional -
if not using a publish port omitt it.

.. code-block:: json
  :caption: Function call: ``get_info``
  :linenos:

  {
    "fcn": "get_info",
    "id": "<requestor id>"
  }

.. code-block:: json
  :caption: Reply: ``get_info``
  :linenos:

  {
    "fcn": "ack",
    "call": "get_info",
    "id": "<replier id>",
    "info_pub_port": 1234,
    "data_pub_port": 5678
  }

**Nack reasons:**
  - None

.. _appinfolinkapi:

Info-link API
-------------

Each time an application is assigned or unassigned owner of a client, a list of clients owned must be published on the Info-Publish port with topic "clients".

.. code-block:: json
  :caption: Info-socket: Topic ``clients``
  :linenos:

  {
    "clients": ["dss010", "dss011"]
  }
