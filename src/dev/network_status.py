#!/usr/bin/python3

import json
import argparse
#import sys
#import os
import time
import traceback

from dss.auxiliaries.modem import Modem


#--------------------------------------------------------------------#

__author__ = 'Andreas Gising <andreas.gising@ri.se>, Kristoffer Bergman <kristoffer.bergman@ri.se>, Hanna Müller <hanna.muller@ri.se>'
__version__ = '0.1.0'
__copyright__ = 'Copyright (c) 2022, RISE'
__status__ = 'development'

#--------------------------------------------------------------------#

'''A tester script for Modem class'''

# Main
def main(modem):
    # # Allocate logfile
    my_log = {}

    # Get static info
    my_log['static_info'] = modem.get_static_info()

    # Enter thread to collect data
    k = 1
    while k < 5:
        # Get dynamic info
        log_item = modem.get_cell_info()

        # Add fake pos data
        log_item['pos'] = {}
        log_item['pos']['lat'] = 58.6
        log_item['pos']['long'] = 15.6
        log_item['pos']['alt'] = 102

        my_log[str(k)] = {}
        my_log[str(k)] = log_item

        time.sleep(1)
        k+=1

    print(json.dumps(my_log, indent=4))

    log_str = json.dumps(my_log, indent=4)
    print(log_str)
    with open('network-log.json','w', encoding="utf-8") as outfile:
        outfile.write(log_str)

    # Test reading from file
    dummy = modem.dummy_log()
    print(json.dumps(dummy, indent=4))

    modem.close()


#--------------------------------------------------------------------#
def _main():
  # parse command-line arguments
  parser = argparse.ArgumentParser(description='APP "app_noise"', allow_abbrev=False, add_help=False)
  parser.add_argument('-h', '--help', action='help', help=argparse.SUPPRESS)
  parser.add_argument('--tty', type=str, help='tty reference /dev/ttyXXX', required=True)
  args = parser.parse_args()


  # Initiate log file
  #dss.auxiliaries.logging.configure('app_noise', stdout=args.stdout, rotating=True, loglevel=args.log, subdir=subnet)

  # Create the Modem class

  try:
    modem = Modem(args.tty)
    main(modem)
  except:
    print("Something bad happened")
    print(traceback.format_exc())

#--------------------------------------------------------------------#
if __name__ == '__main__':
  _main()
