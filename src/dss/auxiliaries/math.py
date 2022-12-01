'''math auxiliaries'''

import base64
import ipaddress
import json
import numpy as np
import math
import copy
import logging


import dss.auxiliaries.exception

#--------------------------------------------------------------------#

__author__ = 'Lennart Ochel <>, Andreas Gising <andreas.gising@ri.se>, Kristoffer Bergman <kristoffer.bergman@ri.se>, Hanna Müller <hanna.muller@ri.se>'
__version__ = '1.0.0'
__copyright__ = 'Copyright (c) 2020-2022, RISE'
__status__ = 'development'

#--------------------------------------------------------------------#

def lla_to_ned(lla:dict, lla_origin:dict):
  # Transform to euclidean frame (origin = lla_origin)
  north = (lla["lat"] - lla_origin["lat"])*1852*60
  east = (lla["lon"] - lla_origin["lon"])*1852*60*math.cos(lla_origin["lat"]/180*math.pi)
  down = -lla["alt"]
  return np.array([north, east, down])

def compute_bearing(lla_1:dict, lla_2:dict):
  # Return a bearing between 0 and 360 degrees
  ned = lla_to_ned(lla_2, lla_1)
  bearing = np.arctan2(ned[1], ned[0])*180/math.pi
  if bearing < 0:
    bearing += 360
  return bearing

def compute_angle_difference(angle_2, angle_1):
  # Compute the minimum angle difference between angle_2 and angle_1
  return (angle_2 - angle_1 + 180) % 360 - 180

def ned_to_lla(ned:np.array, lla_origin:dict):
  #Transform NED to LLA
  lat = ned[0]/(1852*60)
  lon = ned[1]/(1852*60*math.cos(lla_origin["lat"]/180*math.pi))
  alt = -ned[2]
  return np.array([lat, lon, alt])

def distance_2D(lla_1:dict, lla_2:dict):
  ned_2 = lla_to_ned(lla_2, lla_1)
  ned_1 = np.array([0, 0, -lla_2['alt']])
  return math.sqrt(np.sum(ned_2-ned_1)**2)

def project_point(p1:np.array, p2:np.array, p3:np.array):
  '''Project point p3 to the line between p1 and p2'''
  #squared distance between p1 and p2
  l2 = np.sum((p1-p2)**2)
  if l2 == 0:
    return p1
  #The line extending the segment is parameterized as p1 + t (p2 - p1).
  #The projection falls where t = [(p3-p1) . (p2-p1)] / |p2-p1|^2
  #Make sure that the projected line is on the line segment
  t = max(0, min(1, np.sum((p3 - p1) * (p2 - p1)) / l2))
  projection = p1 + t * (p2 - p1)
  return projection

def compute_lookahead_lla_reference(lla_1:dict, lla_2:dict, current_lla:dict, dir:int, distance:float) :
  ned_1 = lla_to_ned(lla_1, current_lla)
  ned_2 = lla_to_ned(lla_2, current_lla)
  ned_0 = np.array([0.0, 0.0, -current_lla["alt"]])

  proj_ned = project_point(ned_1, ned_2, ned_0)
  d_wp = math.sqrt(np.sum((ned_2-ned_1)**2))
  if d_wp > 0 and distance > 0:
    # Compute new coordinates for lookahead (North, East)
    proj_ned = proj_ned + dir*(distance/d_wp)*(ned_2-ned_1)
  proj_lla = ned_to_lla(proj_ned, current_lla)
  ref_lla = copy.deepcopy(current_lla)
  # Compute the lookahead latitude and longitude
  ref_lla["lat"] = current_lla["lat"] + proj_lla[0]
  ref_lla["lon"]= current_lla["lon"] + proj_lla[1]
  #ref_lla["alt"] = proj_lla[2]
  return ref_lla
