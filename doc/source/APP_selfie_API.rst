.. _appselfieapi:

APP Selfie API
==============

.. index:: App_Selfie

The APP Selfie is an application to film an other drone. The main
function is to have a filming drone following the other drone and
filminng it. As soon APP Selfie follows an other drone it will record
video of the scene.
This app has its heritage from TYRApp.


Communication
-------------

.. index:: APP_Selfie, Communication

APP Selfie extends the drone application library to support the Selfie
GUI, :ref:`appapi`. The extended API is described in this chapter.

.. index:: APP_Selfie: Ctrl-link API

APP_Selfie Extension API
------------------------

Information is carried by JSON objects that are sent over the ZeroMQ
REQ/REP interface.

Fcn: set_pattern
~~~~~~~~~~~~~~~~

The function "set_pattern" sets a desired flight pattern for the
filming drone. The pattern describes how the drone should fly in
relation to the reference.

The pattern "above" has the key "rel_alt" for altitude relative
referene (positive means above reference), and key "heading" that can
be set [0-359], "course" or "poi".

.. note::
  If course is set when tracking a stationary reference, the heading
  behaviour might be erratic.

The pattern "cirlce" has a key "rel_alt" for altitude relative
reference (positive means above reference), a key "radius" for 2D
distance from reference. Keys "heading" and "yaw_rate" are used to
define how the drone should cricle, heading towards "poi" or set to
"course", "yaw_rate" in deg/s to set the desired yaw rate of the
circle pattern (velocity limits may limit the yaw rate applied, radius
will honored). The yaw_rate relates to the drone heading, hence will a
positive yaw rate result in a clockwise circle pattern and vice versa.
The relation between yaw_rate and radius determines the velocity as
follows: :math:`v=2*pi*r*yaw\_rate/360`, or approximately
:math:`0.0175*r*yaw\_rate`.


.. code-block:: json
  :caption: Function call: ``set_pattern``
  :linenos:

  {
    "fcn": "set_pattern",
    "id": "<application support id>",
    "pattern": "above",
    "rel_alt": 15,
    "heading": "course"
  }
  {
    "fcn": "set_pattern",
    "id": "<application support id>",
    "pattern": "circle",
    "rel_alt": 10,
    "radius": 10,
    "heading": "poi",
    "yaw_rate": 10
  }

.. todo:: Any nack reasons?

**Nack reasons:**
  - None


.. _followher:

Fcn: follow_her
~~~~~~~~~~~~~~~

The function "follow_her" requests APP_selfie to follow a specific
drone. APP_Selfie will make sure the LLA stream is enabled. The
reference position must be updated at least every 10 seconds,
otherwise the drone will stop, hover and exit the follow mode.

The loaded flight pattern will be used in relation to the reference
points streamed.

The message contains a key "enable" to enable or disable the filming
drone and the key "capability" where the only valid option for now is
camera. **VIDEO**?

.. code-block:: json
  :caption: Reply: **follow_me**
  :linenos:

  {
    "fcn": "follow_her",
    "id": "<appliction support id>",
    "enable": "bool",
    "target_id": "<The dss_id to film>"
  }

**Nack reasons:**
  - requester is not the assigned APP_Selfie


.. .. _app_selfie_infolinkapi:

.. APP Selfie Info-link API
.. ----------------------

.. APP Selfie Info-link cannot be controlled. It is fixed.


.. Clients stream
.. ~~~~~~~~~~~~~~

.. Each time the TYRApp get ownership or releses ownership of a drone it will publish a list of the DSS it currently owns
.. on the Info-socket under topic 'clients'. TYRAmote should follow the first DSS in the list.


.. .. code-block:: json
..   :caption: Info: ``topic clients``
..   :linenos:

..   {
..     "clients": ["<dss_id>", "<dss_id>"]
..   }
