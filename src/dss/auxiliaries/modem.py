#!/usr/bin/python3

import json
import serial
import time

#--------------------------------------------------------------------#

__author__ = 'Andreas Gising <andreas.gising@ri.se>, Kristoffer Bergman <kristoffer.bergman@ri.se>, Hanna Müller <hanna.muller@ri.se>'
__version__ = '0.1.0'
__copyright__ = 'Copyright (c) 2022, RISE'
__status__ = 'development'

class Modem:
    def __init__(self, tty_name):
        self.ser = serial.Serial()
        self.ser.port = tty_name
        self.ser.timeout = 0.05     # readline timeout in seconds
        self.ser.baudrate = 115200  # baudrate
        self.ser.open()
        self.ser.flushInput()
        self.ser.flushOutput()
        self.mode = None

        # AT command convenience table
        self._commands =   {
                            # Static info
                            'hardware':             'ATI',
                            'imsi':                 'AT+CIMI',
                            'imei':                 'AT+GSN',
                            'my_number':            'AT+CNUM',
                            'iccid':                'AT+QCCID',
                            'current_operator':     'AT+COPS?',
                            'preferred_operator':   'AT+CPOL?',
                            'config':               'AT+QCFG=?',

                            # Get supported entities
                            'support_s_profile':    'AT+CGQREQ=?',
                            'support_eng_mode':     'AT+QENG=?',

                            # Dynamic info
                            'sig_quality':          'AT+CSQ',
                            'ext_signal_quality':   'AT+QSCQ',
                            'sig_serving_cell':     'AT+QENG="servingcell"',
                            'sig_neighbour_cell':   'AT+QENG="neighbourcell"',
                            'band':                 'AT+QCFG="band"',
                            'network_info':         'AT+QNWINFO',
                            'network_reg':          'AT+CREG?',
                            'network_reg_status':   'AT+CEREG?',
                            'registered_network':   'AT+QSPN',
                            'time':                 'AT+QLTS=2',
                            'date_time':           'AT+QLTS=2',


                            # Setters
                            'network_reg_set_opt0': 'AT+CREG=0',
                            'network_reg_set_opt1': 'AT+CREG=1',
                            'network_reg_set_opt2': 'AT+CREG=2', # Req for cell id

                            # Not working..
                            'hsdpa':                'AT+QCFG="hsdpacat',
                            'hsupa':                'AT+QCFG="hsupacat'}
        # # Set modem to provide to cell_ID
        if not self.set_modem('network_reg_set_opt2'):
            print("MODEM.py: WARNING: Modem set to report Cell-ID on request FAILED")

    def send_at_and_parse(self, cmd_str):
        params = {}
        answers = self.get_info(cmd_str)
        # Protect faulty parsing, save data even if parsing fails
        try:
            params = self.parse(cmd_str, answers)
        except:
            params['error parsing'] = answers
        return params

    # Parse a response into dict
    def parse(self, cmd_str, answers):
        params = {}
        if cmd_str == 'hardware':
            # Check for correct lenght
            if len(answers) == 3:
                params['manufacturer'] = answers[0]
                params['model'] = answers[1]
                revlist = answers[2].split(' ')
                params['revision'] = revlist[1]

        elif cmd_str == 'iccid':
            #Check for correct length
            if len(answers) == 1:
                split = answers[0].split(": ")
                params['iccid'] = split[1].replace("\"", "")

        elif cmd_str == 'imsi':
            # Check for correct lenght
            if len(answers) == 1:
                params['imsi'] = answers[0]

        elif cmd_str == 'imei':
            # Check for correct lenght
            if len(answers) == 1:
                params['imei'] = answers[0]

        elif cmd_str == 'my_number':
            # Check for correct lenght
            if len(answers) == 1:
                split1 = answers[0].split(',"')
                split2 = split1[1].split('",')
                params['number'] = split2[0]
            # HX 003 does not support number and returns blank.
            else:
                params['number'] = "-"

        elif cmd_str == 'sig_quality':
            # Check for correct length
            if len(answers) == 1:
                split = answers[0].split(': ')
                split2 = split[1].split(',')
                params["rssi"] = split2[0].replace("\"", "")
                params["bit_error_rate"] = split2[1].replace("\"", "")

        elif cmd_str == 'registered_network':
            # Check for correct length
            if len(answers) == 1:
                split1 = answers[0].split(',')
                split2 = split1[0].split(' "')
                params["full_network_name"] = split2[1].replace("\"", "")
                params["short_network_name"] = split1[1].replace("\"", "")
                params["spn"] = split1[2].replace("\"", "")

        elif cmd_str == 'time':
            if len(answers) == 1:
                lst = answers[0].split(',')
                t_split = lst[1].split('+')
                time = t_split[0]
                params['time'] = time

        elif cmd_str == 'date_time':
            if len(answers) == 1:
                lst = answers[0].split(',')
                d_split = lst[0].split('\"')
                date = d_split[1].replace('/','-')
                t_split = lst[1].split('+')
                time = t_split[0]
                time_zone = "+" + t_split[1]
                params['date'] = date
                params['time'] = time
                params['time-zone'] = time_zone


        elif cmd_str == 'sig_serving_cell':
            #['+QENG: "servingcell","NOCONN","LTE","FDD",240,01,18A8118,442,1471,3,4,4,9D,-96,-9,-68,14,-']
            lst = answers[0].split(',')
            #split = split[1].split(",")

            params['state'] = lst[1].replace("\"", "")
            params['mode'] = lst[2].replace("\"", "") # LTE / GSM
            if params['mode'] == "LTE":
                self.mode = "LTE"
                params['is_tdd'] = lst[3].replace("\"", "")
                params['mcc'] = lst[4].replace("\"", "")
                params['mnc'] = lst[5].replace("\"", "")
                params['cellid'] = lst[6].replace("\"", "")
                params['pcid'] = lst[7].replace("\"", "")
                params['earfnc'] = lst[8].replace("\"", "")
                params['freq_band_ind'] = lst[9].replace("\"", "")
                params['ul_bandwidth'] = lst[10].replace("\"", "")
                params['dl_bandwidth'] = lst[11].replace("\"", "")
                params['tac'] = lst[12].replace("\"", "")
                params['rsrp'] = lst[13].replace("\"", "")
                params['rsrq'] = lst[14].replace("\"", "")
                params['rssi'] = lst[15].replace("\"", "")
                params['sinr'] = lst[16].replace("\"", "")
                params['arxlev'] = lst[17].replace("\"", "")


            elif params['mode'] == "GSM":
                self.mode = "GSM"
                params['mcc'] = lst[3].replace("\"", "")
                params['mnc'] = lst[4].replace("\"", "")
                params['lac'] = lst[5].replace("\"", "")
                params['cellid'] = lst[6].replace("\"", "")
                params['bsic'] = lst[7].replace("\"", "")
                params['arfnc'] = lst[8].replace("\"", "")
                params['band'] = lst[9].replace("\"", "")
                params['rxlev'] = lst[10].replace("\"", "")
                params['txp'] = lst[11].replace("\"", "")
                params['rla'] = lst[12].replace("\"", "")
                params['drx'] = lst[13].replace("\"", "")
                params['c1'] = lst[14].replace("\"", "")
                params['c2'] = lst[15].replace("\"", "")
                params['gprs'] = lst[16].replace("\"", "")
                params['tch'] = lst[17].replace("\"", "")
                params['ts'] = lst[18].replace("\"", "")
                params['ta'] = lst[19].replace("\"", "")
                params['maio'] = lst[20].replace("\"", "")
                params['hsn'] = lst[21].replace("\"", "")
                params['rxlevsub'] = lst[22].replace("\"", "")
                params['rxlevfull'] = lst[23].replace("\"", "")
                params['rxqualsub'] = lst[24].replace("\"", "")
                params['rxqualfull'] = lst[25].replace("\"", "")
                params['videocodec'] = lst[26].replace("\"", "")

            elif params['mode'] == "WCDMA":
                self.mode = "WCDMA"
                params['uarfcn'] = split[3].replace("\"","")
                params['psc'] = split[4].replace("\"","")
                params['rscp'] = split[5].replace("\"","")
                params['ecno'] = split[6].replace("\"","")

        elif cmd_str == 'sig_neighbour_cell':
            for i in range (0,len(answers)):
                cell = answers[i]
                lst = cell.split(',')
                params[i] = {}
                params[i]['mode'] = lst[1].replace("\"", "") # LTE / GSM

                # Depending on operational mmode different info is sent.
                # Use answer length and last known mode to determine
                if params[i]['mode'] == "LTE":
                    if len(lst) == 13:
                        # LTE mode, neighbourcell intra based on lenth
                        if self.mode == "LTE" or self.mode == None:
                            params[i]['earfcn'] = lst[2].replace("\"","")
                            params[i]['pcid'] = lst[3].replace("\"","")
                            params[i]['rsrq'] = lst[4].replace("\"","")
                            params[i]['rsrp'] = lst[5].replace("\"","")
                            params[i]['rssi'] = lst[6].replace("\"","")
                            params[i]['sinr'] = lst[7].replace("\"","")
                            params[i]['srxlev'] = lst[8].replace("\"","")
                            params[i]['cell_resel_priority'] = lst[9].replace("\"","")
                            params[i]['s_non_intra_search'] = lst[10].replace("\"","")
                            params[i]['thresh_serving_low'] = lst[11].replace("\"","")
                            params[i]['s_intra_search'] =lst[12].replace("\"","")

                    if len(lst) == 12:
                        # LTE mode, neightbourcell inter based on length
                        if self.mode == "LTE" or self.mode == None:
                            params[i]['earfcn'] = lst[2].replace("\"","")
                            params[i]['pcid'] = lst[3].replace("\"","")
                            params[i]['rsrq'] = lst[4].replace("\"","")
                            params[i]['rsrp'] = lst[5].replace("\"","")
                            params[i]['rssi'] = lst[6].replace("\"","")
                            params[i]['sinr'] = lst[7].replace("\"","")
                            params[i]['srxlev'] = lst[8].replace("\"","")
                            params[i]['theshX_low'] = lst[9].replace("\"","")
                            params[i]['treshX_high'] = lst[10].replace("\"","")
                            params[i]['cell_resel_priority'] = lst[11].replace("\"","")

                    if len(lst) == 7:
                        # WCDMA mode, neightbourcell
                        params[i]['earfcn'] = lst[2].replace("\"","")
                        params[i]['cellid'] = lst[3].replace("\"","")
                        params[i]['rsrp'] = lst[4].replace("\"","")
                        params[i]['rsrq'] = lst[5].replace("\"","")
                        params[i]['s_rxlev'] = lst[6].replace("\"","")

                    if len(lst) == 6:
                        # GSM mode, neightbourcell
                        params[i]['earfcn'] = lst[2].replace("\"","")
                        params[i]['pcid'] = lst[3].replace("\"","")
                        params[i]['rsrp'] = lst[4].replace("\"","")
                        params[i]['rsrq'] = lst[5].replace("\"","")

                elif params[i]['mode'] == "GSM":
                    if len(lst) == 13:
                        # GSM mode, neighbourcell
                        params[i]['mcc'] = lst[2].replace("\"","")
                        params[i]['mnc'] = lst[3].replace("\"","")
                        params[i]['lac'] = lst[4].replace("\"","")
                        params[i]['cellid'] = lst[5].replace("\"","")
                        params[i]['bsic'] = lst[6].replace("\"","")
                        params[i]['arfcn'] = lst[7].replace("\"","")
                        params[i]['rxelev'] = lst[8].replace("\"","")
                        params[i]['c1'] = lst[9].replace("\"","")
                        params[i]['c2'] = lst[10].replace("\"","")
                        params[i]['c31'] = lst[11].replace("\"","")

                    if len(lst) == 6:
                        # WCDMA mode, neighbourcell
                        params[i]['bsic'] = lst[2].replace("\"","")
                        params[i]['rssi'] = lst[3].replace("\"","")
                        params[i]['rxlev'] = lst[4].replace("\"","")
                        params[i]['rank'] = lst[5].replace("\"","")

                    if len(lst) == 11:
                        # LTE mode, neighbourcell
                        params[i]['arfcn'] = lst[2].replace("\"","")
                        params[i]['cell_resel_priority'] = lst[3].replace("\"","")
                        params[i]['thresh_gsm_high'] = lst[4].replace("\"","")
                        params[i]['thresh_gsm_low'] = lst[5].replace("\"","")
                        params[i]['ncc_permitted'] = lst[6].replace("\"","")
                        params[i]['band'] = lst[7].replace("\"","")
                        params[i]['bsic_id'] = lst[8].replace("\"","")
                        params[i]['rssi'] = lst[9].replace("\"","")
                        params[i]['srxlev'] = lst[10].replace("\"","")

        else:
            params[cmd_str] = "Not defined in parser"
        return params

    # Send specified AT command and return answer(s)
    def send_at_command(self, cmd_str):
        cmd = cmd_str + "\r\n"
        self.ser.write(cmd.encode())
        answers = []
        while True:
            answer = self.ser.readline()
            if self.is_timeout(answer):
                # This is a timeout
                break
            if self.is_empty_line(answer):
                # Discard empty line
                continue
            # Decode bytes to string
            decoded = answer.decode()
            # Clean trailing carriage return and newlines
            decoded = decoded.rstrip('\r\n')
            # Append to answer list
            answers.append(decoded)
        return answers

    # Send AT command to aquire info via look-up directory
    def get_info(self, key):
        # Look-up key
        if key in self._commands:
            cmd = self._commands[key] + "\r\n"
        else:
            # create exception..
            print("MODEM.py: Key not recognized:" , key)
            return []
        self.ser.write(cmd.encode())
        answers = []
        attempts = 1
        # Send command and read answer until timeout
        while True:
            answer = self.ser.readline()
            if self.is_timeout(answer):
                # This is a timeout
                if not answers and attempts < 5:
                    # time out and no received answers
                    if attempts == 5:
                        print("MODEM.py: Warning, no answer recevied within 5 timeouts")
                        break
                    #print("MODEM.py: No response within timeout, try again. Attempts: ", attempts)
                    attempts += 1
                    continue
                # Complete response is already received
                break
            # Discard empty lines
            if self.is_empty_line(answer):
                continue
            # Print to stdout on receiving ERROR
            if self.is_error(answer):
                print("MODEM.py: Received ERROR when sending ", self._commands[key])
            # Discart 'OK' from answer
            if self.is_ok(answer):
                # Dont log the 'OK'
                continue
            # Decode bytes to string
            decoded = answer.decode()
            # Clean trailing carriage return and newlines
            decoded = decoded.rstrip('\r\n')
            # Append to answer list
            answers.append(decoded)
        return answers

    # Send AT command from look-up directory, return bool
    def set_modem(self, key):
        # Look-up key
        if key in self._commands:
            cmd = self._commands[key] + "\r\n"
        else:
            # create exception..
            print("MODEM.py: Key not recognized:" , key)
            return False
        self.ser.write(cmd.encode())
        answers = []
        attempts = 1
        while True:
            answer = self.ser.readline()
            if self.is_timeout(answer):
                # This is a timeout
                if not answers and attempts < 5:
                    # time out and no received answers
                    if attempts == 5:
                        print("MODEM.py: Warning, no answer recevied within 5 timeouts")
                        break
                    #print("MODEM.py: No response within timeout, try again. Attempts: ", attempts)
                    attempts += 1
                    continue
                # Complete response is already received
                break
            # Discard empty lines
            if self.is_empty_line(answer):
                continue
            # If 'ERROR'
            if self.is_error(answer):
                return False
            # If 'OK'
            elif self.is_ok(answer):
                return True
            else:
                return False

    # Test for timeout answer
    def is_timeout(self, bytes):
        return b'' == bytes

    # Test for carriage return and newline with no data
    def is_empty_line(self, bytes):
        return b'\r\n' == bytes

    # Test for 'ERROR'
    def is_error(self, bytes):
        return b'ERROR\r\n' == bytes

    # Test for 'OK'
    def is_ok(self, bytes):
        return b'OK\r\n' == bytes

    # Test AT command and print answer
    def test(self, cmd):
        answer = self.get_info(cmd)
        print(answer)

    # Debug function to test cmd_str and modem compability
    def test_sequence(self):
        self.test('support_eng_mode')
        print("Static (?) information")
        self.test('hardware')
        self.test('imsi')
        self.test('imsi')
        self.test('imei')
        self.test('my_number')
        self.test('iccid')
        self.test('current_operator')
        self.test('preferred_operator')
        self.test('date_time')
        self.test('time')

        self.test('config')

        print("\nDynamic information")
        self.test('sig_quality')
        self.test('ext_signal_quality')
        self.test('sig_serving_cell')
        self.test('sig_neighbour_cell')
        self.test('band')
        self.test('network_info')
        self.test('network_reg')
        self.test('network_reg_status')
        self.test('registered_network')

    # Debug funciton to test parsing
    def parse_sequence(self):
        hw = self.send_at_and_parse('hardware')
        imsi = self.send_at_and_parse('imsi')
        imei = self.send_at_and_parse('imei')
        my_number = self.send_at_and_parse('my_number')

        # Merge
        static_info = {**hw, **imsi, **imei, **my_number}
        print(json.dumps(static_info, indent = 2))

        serving_cell = self.send_at_and_parse('sig_serving_cell')
        print(json.dumps(serving_cell, indent = 2))

        neighbour_cell = self.send_at_and_parse('sig_neighbour_cell')
        print(json.dumps(neighbour_cell, indent = 2))

    # Convenience function for getting a static data
    def get_static_info(self):
        date_time = self.send_at_and_parse('date_time')
        hw = self.send_at_and_parse('hardware')
        imsi = self.send_at_and_parse('imsi')
        imei = self.send_at_and_parse('imei')
        iccid = self.send_at_and_parse('iccid')
        my_number = self.send_at_and_parse('my_number')
        registered_network = self.send_at_and_parse('registered_network')
        spn = {'spn': registered_network['spn']}
        # Merge
        static_info = {**date_time, **hw, **imsi, **imei, **iccid, **my_number, **spn}
        return static_info

    # Convenience method for getting cell info
    def get_cell_info(self):
        log_item = {}
        log_item['serving_cell'] = self.send_at_and_parse('sig_serving_cell')
        log_item['neighbour_cell'] = self.send_at_and_parse('sig_neighbour_cell')
        log_item['time'] = self.send_at_and_parse('time')
        return log_item

    # Setup serial, not used for now
    def serConf(self):
        self.ser.baudrate = 9600
        self.ser.bytesize = serial.EIGHTBITS
        self.ser.parity = serial.PARITY_NONE
        self.ser.stopbits = serial.STOPBITS_ONE
        self.ser.timeout = 0 # Non-Block reading
        self.ser.xonxoff = False # Disable Software Flow Control
        self.ser.rtscts = False # Disable (RTS/CTS) flow Control
        self.ser.dsrdtr = False # Disable (DSR/DTR) flow Control
        self.ser.writeTimeout = 2

    # Close serial
    def close(self):
        self.ser.close()

    # Report a dummy log, for test puposes
    def dummy_log(self):
        with open('network-log.json', 'r', encoding='utf-8') as infile:
            dummy_logfile = json.load(infile)
            return dummy_logfile
