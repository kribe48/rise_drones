.. _skarappapi:

SkarApp API
===========

.. index:: SkarApp

The SkarApp is an application to support a cyclist.
The main function is to have two drones following the
remote that the cyclist carries, Skaramote, providing dynamic spotlights on the road.


Communication
-------------

.. index:: SkarApp, Communication

SkarApp extends the drone application library to support the Skaramote,
:ref:`appapi`. The extended API is described in this chapter.

.. index:: SkarApp: Ctrl-link API

SkarApp Extension API
---------------------

Information is carried by JSON objects that are sent over the ZeroMQ
REQ/REP interface.

.. _followher_skara:

Fcn: follow_her
~~~~~~~~~~~~~~~

The function "follow_her" is called to tell app Skara to aquire drones to follow
the targed specified by ``target_id``. Prior to calling "follow_her" the target
id LLA-stream must be enabled on her dynamic publish-socket. The flight pattern
used is "above", where relative altitude is specified as a parameter in the
config file. The message contains a key ``enable`` to enable or disable
following drones. Disabling follow her will return and land any allocated
drones. The key ``capabilities`` is a list of capabilities that the following
drones must match.

.. code-block:: json
  :caption: Request: **follow_her**
  :linenos:

  {
    "fcn": "follow_her",
    "id": "<appliction support id>",
    "enable": true,
    "target_id": "da001"
    "capabilities": ["SPOTLIGHT"]
  }

**Nack reasons:**
  - Requestor (id) is not the app owner
  - Missing target id
  - Target id not found
  - Follow her already enabled

SkarApp Info API
---------------------
In order to control two drones following the same stream, and to make sure that the drone is following the road, SkarApp publishes a modified
LLA stream for each drone based on the LLA-stream from the target in :ref:`followher_skara`. These modified streams are used when calling :ref:`follow_stream` for each drone.
The ports for publishing are dynamically allocated in the interval [crm.port, crm.port+50].
