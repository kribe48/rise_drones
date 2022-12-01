#!/usr/bin/python3

import json
import argparse
import traceback

from dss.auxiliaries.modem import Modem


#--------------------------------------------------------------------#

__author__ = 'Andreas Gising <andreas.gising@ri.se>, Kristoffer Bergman <kristoffer.bergman@ri.se>, Hanna Müller <hanna.muller@ri.se>'
__version__ = '0.1.0'
__copyright__ = 'Copyright (c) 2022, RISE'
__status__ = 'development'

#--------------------------------------------------------------------#

'''A script to print some informative modem info to script server'''

# Main
def main(modem):
    # Print mount point
    tty = {'tty': modem.ser.port}
    # Get static info
    static_info = modem.get_static_info()
    # Get signal quality
    signal_quality = modem.send_at_and_parse('sig_quality')
    # Merge into one dict
    modem_status = {**tty, **static_info, **signal_quality}

    # Print to scrren
    print(json.dumps(modem_status, indent=4))

    modem.close()


#--------------------------------------------------------------------#
def _main():
  # parse command-line arguments
  parser = argparse.ArgumentParser(description='APP "app_noise"', allow_abbrev=False, add_help=False)
  parser.add_argument('-h', '--help', action='help', help=argparse.SUPPRESS)
  args = parser.parse_args()

  # Connect to modem on specified path
  dev_paths = [2,3]
  connected=False
  for dev_path in dev_paths:
    device=f"/dev/serial/by-id/usb-Android_Android-if0{dev_path}-port0"
    if not connected:
      try:
        modem = Modem(device)
        print(f'MODEM: Connected to modem on {device}')
        connected=True
      except:
        print(f'MODEM: Could not find modem device, {device}')

  # None of the dev_paths works..
  if not connected:
    return

  # Finally try main
  try:
    main(modem)
  except:
    print("main(modem) in network_status failed somehow")
    print(traceback.format_exc())

#--------------------------------------------------------------------#
if __name__ == '__main__':
  _main()
