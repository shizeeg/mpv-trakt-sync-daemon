import json
import socket
import threading
from time import sleep

import os


class MpvMonitor:
    @staticmethod
    def create(posix_socket_path, windows_named_pipe_path, on_connected=None, on_event=None, on_command_response=None,
               on_disconnected=None):
        if os.name == 'posix':
            return PosixMpvMonitor(posix_socket_path, on_connected, on_event, on_command_response, on_disconnected)
        elif os.name == 'nt':
            return WindowsMpvMonitor(windows_named_pipe_path, on_connected, on_event, on_command_response,
                                     on_disconnected)

    def __init__(self, on_connected, on_event, on_command_response, on_disconnected):
        self.lock = threading.Lock()
        self.command_counter = 1
        self.sent_commands = {}
        self.on_connected = on_connected
        self.on_event = on_event
        self.on_command_response = on_command_response
        self.on_disconnected = on_disconnected

    def run(self):
        pass

    def write(self, data):
        pass

    def on_line(self, line):
        try:
            mpv_json = json.loads(line)
        except json.JSONDecodeError:
            print('invalid JSON received. skipping.', line)
            return
        # print(mpv_json)
        if 'event' in mpv_json:
            if self.on_event is not None:
                self.on_event(self, mpv_json)
        elif 'request_id' in mpv_json:
            with self.lock:
                request_id = mpv_json['request_id']
                if request_id not in self.sent_commands:
                    print('got response for unsent command request', mpv_json)
                else:
                    if self.on_command_response is not None:
                        self.on_command_response(self, self.sent_commands[request_id], mpv_json)
                    del self.sent_commands[request_id]
        else:
            print('Unknown mpv output: ' + line)

    def fire_connected(self):
        if self.on_connected is not None:
            self.on_connected(self)

    def fire_disconnected(self):
        if self.on_disconnected is not None:
            self.on_disconnected()

    def send_command(self, elements):
        command = {'command': elements, 'request_id': self.command_counter}
        with self.lock:
            self.sent_commands[self.command_counter] = command
            self.command_counter += 1
            self.write(str.encode(json.dumps(command) + '\n'))

    def send_get_property_command(self, property_name):
        self.send_command(['get_property', property_name])


class PosixMpvMonitor(MpvMonitor):
    def __init__(self, socket_path, on_connected, on_event, on_command_response, on_disconnected):
        super().__init__(on_connected, on_event, on_command_response, on_disconnected)
        self.socket_path = socket_path
        self.sock = None

    def can_open(self):
        sock = socket.socket(socket.AF_UNIX)
        errno = sock.connect_ex(self.socket_path)
        sock.close()
        return errno == 0

    def run(self):
        self.sock = socket.socket(socket.AF_UNIX)
        self.sock.connect(self.socket_path)

        print('POSIX socket connected')
        self.fire_connected()

        buffer = ''
        while True:
            try:
                data = self.sock.recv(512)
            except KeyboardInterrupt:
                print('terminating')
                quit(0)  # todo: doesn't terminate, idk why
            if len(data) == 0:
                break
            buffer = buffer + data.decode('utf-8')
            if buffer.find('\n') == -1:
                print('received partial line', buffer)
            while True:
                line_end = buffer.find('\n')
                if line_end == -1:
                    break
                else:
                    self.on_line(buffer[:line_end])  # doesn't include \n
                    buffer = buffer[line_end + 1:]  # doesn't include \n

        print('POSIX socket closed')
        self.sock.close()
        self.sock = None

        self.fire_disconnected()

    def write(self, data):
        # no closed check is available, so just send it
        self.sock.send(data)


class WindowsMpvMonitor(MpvMonitor):
    def __init__(self, named_pipe_path, on_connected, on_event, on_command_response, on_disconnected):
        super().__init__(on_connected, on_event, on_command_response, on_disconnected)
        self.named_pipe_path = named_pipe_path
        self.pipe = None

    def can_open(self):
        return os.path.isfile(self.named_pipe_path)

    def run(self):
        while self.pipe is None:
            try:
                self.pipe = open(self.named_pipe_path, 'r+b')
                # Why r+b? We want rw access, no truncate and start from beginning of file.
                # (see http://stackoverflow.com/a/30566011/2634932)
            except OSError:
                # Sometimes Windows can't open the named pipe directly. I suspect a interaction between os.path.isfile()
                # and directly following open(). Sleeping for a short time and trying again seems to help.
                print('OSError. Trying again')
                sleep(0.01)

        print('Windows named pipe connected')
        self.fire_connected()

        while True:
            try:
                line = self.pipe.readline()
            except KeyboardInterrupt:
                print('terminating')
                quit(0)  # todo: doesn't terminate, idk why
            if len(line) == 0:
                break
            self.on_line(line)

        print('Windows named pipe closed')
        self.pipe.close()
        self.pipe = None

        self.fire_disconnected()

    def write(self, data):
        if self.pipe.closed:
            print('Windows named pipe was closed. Can\'t send data: ' + str(data))
        else:
            self.pipe.write(data)
