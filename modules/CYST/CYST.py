from slips_files.common.abstracts import Module
import multiprocessing
from slips_files.core.database.database import __database__
from slips_files.common.config_parser import ConfigParser
from slips_files.common.slips_utils import utils
import sys
import traceback
import socket
import json
import os

class Module(Module, multiprocessing.Process):
    # Name: short name of the module. Do not use spaces
    name = 'CYST'
    description = 'Communicates with CYST simulation framework'
    authors = ['Alya Gomaa']

    def __init__(self, outputqueue, redis_port):
        multiprocessing.Process.__init__(self)
        self.port = None
        self.outputqueue = outputqueue
        __database__.start(redis_port)
        self.c1 = __database__.subscribe('new_json_evidence')
        self.cyst_UDS = '/tmp/slips.sock'



    def print(self, text, verbose=1, debug=0):
        """
        Function to use to print text using the outputqueue of slips.
        Slips then decides how, when and where to print this text by taking all the processes into account
        :param verbose:
            0 - don't print
            1 - basic operation/proof of work
            2 - log I/O operations and filenames
            3 - log database/profile/timewindow changes
        :param debug:
            0 - don't print
            1 - print exceptions
            2 - unsupported and unhandled types (cases that may cause errors)
            3 - red warnings that needs examination - developer warnings
        :param text: text to print. Can include format like 'Test {}'.format('here')
        """

        levels = f'{verbose}{debug}'
        self.outputqueue.put(f'{levels}|{self.name}|{text}')



    def initialize_unix_socket(self):
        """
        Slips will be the server, so it has to run before cyst to create the socket
        """
        unix_socket = '/tmp/slips.sock'

        # Make sure the socket does not already exist
        if os.path.exists(unix_socket):
            os.unlink(unix_socket)

        # Create a UDS socket
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.bind(unix_socket)


        failure = sock.listen(2)
        if not failure:
            self.print(f"Slips is now listening. waiting for CYST to connect.")
        else:
            self.print(f" failed to initialize sips socket. Error code: {failure}")

        connection, client_address = sock.accept()
        return sock, connection


    def get_flow(self) -> tuple:
        """
        reads 1 flow from the CYST socket and converts it to dict
        returns True, flow_dict if the flow was received
        and Tuple(False, Error_msg) if there was an error
        """
        try:
            self.sock.settimeout(5)
            #todo handle multiple flows received at once i.e. split by \n
            flow: str = self.cyst_conn.recv(10000).decode()
        except ConnectionResetError:
            return False, 'Connection reset by CYST.'
        except socket.timeout:
            # no flows yet
            return False, 'CYST didnt send flows yet.'

        try:
            flow = json.loads(flow)
        except json.decoder.JSONDecodeError:
            return False, 'Invalid json line received from CYST.'

        return flow, ''

    def send_evidence(self, evidence: str):
        """
        :param evidence: json serialized dict
        """
        self.print(f"Sending evidence back to CYST.", 0, 1)
        # todo test how long will it take slips to respond to cyst
        # todo explicitly sending message length before the message itself.
        self.cyst_conn.sendall(evidence.encode())


    def close_connection(self):
        self.sock.close()

    def shutdown_gracefully(self):
        # Confirm that the module is done processing
        __database__.publish('finished_modules', self.name)
        return



    def run(self):
        if not ('-C' in sys.argv or '--CYST' in sys.argv):
            return

        # connect to cyst
        self.sock, self.cyst_conn = self.initialize_unix_socket()

        while True:
            try:
                # RECEIVE FLOWS FROM CYST
                flow, error = self.get_flow()
                if not flow:
                    self.print(error, 0, 1)
                else:
                    # send the flow to inputprocess so slips can process it normally
                    __database__.publish('new_cyst_flow', flow)


                # SEND EVIDENCE TO CYST
                print(f"@@@@@@@@@@@@@@@@@@  tryoing to get msg")
                msg = __database__.get_message(self.c1)
                if msg and msg['data'] == 'stop_process':
                    self.shutdown_gracefully()
                    return True

                if utils.is_msg_intended_for(msg, 'new_json_evidence'):
                    print(f"@@@@@@@@@@@@@@@@@@ cyst module received a new evidence . sending ... ")
                    evidence: str = msg['data']
                    self.send_evidence(evidence)

            except KeyboardInterrupt:
                self.shutdown_gracefully()
                return True
            except Exception as inst:
                exception_line = sys.exc_info()[2].tb_lineno
                self.print(f'Problem on the run() line {exception_line}', 0, 1)
                self.print(traceback.format_exc(), 0, 1)
                return True


