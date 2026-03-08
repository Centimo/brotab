import json
import os
import queue
import socket
import threading

from brotab.mediator.log import mediator_logger


class EventServer:
    """Unix socket server that broadcasts browser tab events to connected clients.

    Listens on a Unix domain socket path. Clients connect and receive
    newline-delimited JSON events as they occur.
    """

    def __init__(self, socket_path: str, event_queue: queue.Queue):
        self._socket_path = socket_path
        self._event_queue = event_queue
        self._clients: list[socket.socket] = []
        self._lock = threading.Lock()
        self._server_socket: socket.socket | None = None

    def start(self):
        self._cleanup_socket()
        self._server_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._server_socket.bind(self._socket_path)
        self._server_socket.listen(5)
        mediator_logger.info('EventServer listening on %s', self._socket_path)

        accept_thread = threading.Thread(target=self._accept_loop, daemon=True)
        accept_thread.start()

        broadcast_thread = threading.Thread(target=self._broadcast_loop, daemon=True)
        broadcast_thread.start()

    def _cleanup_socket(self):
        try:
            os.unlink(self._socket_path)
        except FileNotFoundError:
            pass

    def _accept_loop(self):
        while True:
            try:
                client, _ = self._server_socket.accept()
                mediator_logger.info('EventServer: client connected')
                with self._lock:
                    self._clients.append(client)
            except OSError:
                break

    def _broadcast_loop(self):
        while True:
            try:
                event = self._event_queue.get()
            except Exception:
                break

            line = json.dumps(event, ensure_ascii=False) + "\n"
            data = line.encode("utf-8")

            with self._lock:
                dead = []
                for client in self._clients:
                    try:
                        client.setblocking(False)
                        client.sendall(data)
                    except (BrokenPipeError, ConnectionResetError, OSError, BlockingIOError):
                        mediator_logger.info('EventServer: client disconnected or slow, dropping')
                        dead.append(client)
                    finally:
                        try:
                            client.setblocking(True)
                        except OSError:
                            pass
                for client in dead:
                    self._clients.remove(client)
                    try:
                        client.close()
                    except OSError:
                        pass

    def shutdown(self):
        if self._server_socket:
            self._server_socket.close()
        self._cleanup_socket()
        with self._lock:
            for client in self._clients:
                try:
                    client.close()
                except OSError:
                    pass
            self._clients.clear()
