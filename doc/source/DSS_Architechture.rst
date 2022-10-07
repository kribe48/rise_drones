Drone Architecture overview
===========================

.. index:: Architecture

Hardware
--------

.. index:: Hardware

There is a flight control unit (FCU) mounted on top of the drone.
Within the FCU most avionics is installed. The main components within
the FCU are

- Pixhawk 2.1 Cube autopilot
- Raspberry pi 3B+ (RPI)
- Sixfab 4G modem docked to RPI
- Jetson NVIDIA TX2 mounted on J120 carrier board
- Mauch Power Cube V3

PixHawk 2.1 Cube Autopilot
~~~~~~~~~~~~~~~~~~~~~~~~~~

The autopilot is open source, both hardware and software. We run
latest stable version of Arducopter.

Raspberry Pi 3B+ (RPI)
~~~~~~~~~~~~~~~~~~~~~~

Running raspbian-stretch light.

Sixfab 4G Modem
~~~~~~~~~~~~~~~

Sixfab modem is docked onto the RPI. It allows the RPI to connect over
VPN to our network called DroneNet. This is the main data link between
the drone and the operator(s).

Jetson NVIDIA TX2
~~~~~~~~~~~~~~~~~

The Jetson NVIDIA TX2 is intended for computation heavy sensors and
has an external USB3 connection for big data flows. TX2 is powered
from payload power and can be controlled from RPI via ethernet
connection.

Mauch power module
~~~~~~~~~~~~~~~~~~

The Mauch Power Cube V3, a DCDC converter that outputs three
independent power channels, 2 at 5V and one at 10V. Both supporting
continuous current of 10A.
