# coding:utf-8
'''OpenSSL Connection Wrapper'''

import socket
import errno
from OpenSSL import SSL
from select import select

zero_errno = errno.ECONNABORTED, errno.ECONNRESET, errno.ENOTSOCK
zero_EOF_error = -1, 'Unexpected EOF'

class SSLConnection:
    '''API-compatibility wrapper for Python OpenSSL's Connection-class.'''

    def __init__(self, context, sock):
        self._context = context
        self._sock = sock
        self._connection = SSL.Connection(context, sock)
        self._io_refs = 0

    def __del__(self):
        if self._sock:
            self._sock.close()
            self._sock = None

    def __getattr__(self, attr):
        return getattr(self._connection, attr)

    def __iowait(self, io_func, *args, **kwargs):
        timeout = self._sock.gettimeout()
        fd = self._sock
        while self._connection:
            try:
                return io_func(*args, **kwargs)
            except (SSL.WantReadError, SSL.WantX509LookupError):
                #exc_clear()
                rd, _, ed = select([fd], [], [fd], timeout)
                if ed:
                    raise socket.error(ed)
                if not rd:
                    raise socket.timeout('The read operation timed out')
            except SSL.WantWriteError:
                #exc_clear()
                _, wd, ed = select([], [fd], [fd], timeout)
                if ed:
                    raise socket.error(ed)
                if not wd:
                    raise socket.timeout('The write operation timed out')
            except SSL.SysCallError as e:
                if e.args[0] == errno.EWOULDBLOCK:
                    #exc_clear()
                    rd, wd, ed = select([fd], [fd], [fd], timeout)
                    if ed:
                        raise socket.error(ed)
                    if not rd and not wd:
                        raise socket.timeout('The socket operation timed out')
                elif e.args[0] == errno.EAGAIN:
                    continue
                else:
                    raise e

    def accept(self):
        sock, addr = self._sock.accept()
        client = SSLConnection(self._context, sock)
        client.set_accept_state()
        return client, addr

    def do_handshake(self):
        self.__iowait(self._connection.do_handshake)

    def connect(self, addr):
        self.__iowait(self._connection.connect, addr)

    def send(self, data, flags=0):
        if data:
            return self.__iowait(self._connection.send, data)
        else:
            return 0
    write = send

    def sendall(self, data, flags=0):
        total_sent = 0
        total_to_send = len(data)
        if not hasattr(data, 'tobytes'):
            data = memoryview(data)
        while total_sent < total_to_send:
            sent = self.send(data[total_sent:total_sent + 32768]) # 32K
            total_sent += sent

    def recv(self, bufsiz, flags=None):
        pending = self._connection.pending()
        if pending:
            return self._connection.recv(min(pending, bufsiz))
        try:
            return self.__iowait(self._connection.recv, bufsiz, flags)
        except SSL.ZeroReturnError as e:
            if self._connection.get_shutdown() == SSL.RECEIVED_SHUTDOWN:
                return b''
            raise e
        except SSL.SysCallError as e:
            if e.args == zero_EOF_error:
                return b''
            elif e.args[0] in zero_errno:
                return b''
            raise e
    read = recv

    def recv_into(self, buffer, nbytes=None, flags=None):
        pending = self._connection.pending()
        if pending:
            return self._connection.recv_into(buffer)
        try:
            return self.__iowait(self._connection.recv_into, buffer, nbytes, flags)
        except SSL.ZeroReturnError as e:
            if self._connection.get_shutdown() == SSL.RECEIVED_SHUTDOWN:
                return 0
            raise e
        except SSL.SysCallError as e:
            if e.args == zero_EOF_error:
                return 0
            elif e.args[0] in zero_errno:
                return 0
            raise e
    readinto = recv_into

    def close(self):
        if self._io_refs < 1:
            self._connection = None
            if self._sock:
                self._sock.close()
                self._sock = None
        else:
            self._io_refs -= 1

    #if PY3:
    #    def makefile(self, *args, **kwargs):
    #        return socket.socket.makefile(self, *args, **kwargs)
    #else:
    #    def makefile(self, mode='r', bufsize=-1):
    #        self._io_refs += 1
    #        return socket._fileobject(self, mode, bufsize, close=True)
    def makefile(self, *args, **kwargs):
        return socket.socket.makefile(self, *args, **kwargs)
