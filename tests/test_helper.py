"""No physical devices or session bus are used by these protocol tests."""
import importlib.util
import pathlib
import socket
import threading
import unittest

SPEC = importlib.util.spec_from_file_location(
    "gesture_helper", pathlib.Path(__file__).resolve().parents[1] / "scripts/gesture-helper.py")
helper = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(helper)


class HelperTests(unittest.TestCase):
    def test_protocol_validation(self):
        self.assertEqual(helper.parse_request(b"PR1 1 HELLO /dev/input/event42", 0, None),
                         (1, "HELLO", "/dev/input/event42"))
        for packet, previous, target in [
            (b"PR1 1 CANCEL /dev/input/event42", 0, None),
            (b"PR1 1 HELLO /dev/input/event42", 1, "/dev/input/event42"),
            (b"PR1 3 CANCEL /dev/input/event42", 1, "/dev/input/event42"),
            (b"PR1 2 CANCEL /dev/input/event43", 1, "/dev/input/event42"),
            (b"PR1 2 HELLO /dev/input/event42", 1, "/dev/input/event42"),
            (b"PR1 2 CANCEL /dev/input/../event42", 1, "/dev/input/event42"),
            (b"PR1 1 HELLO /dev/input/event42\n", 0, None),
            (b"PR2 1 HELLO /dev/input/event42", 0, None),
            (b"PR1 18446744073709551616 HELLO /dev/input/event42", 0, None),
        ]:
            with self.subTest(packet=packet), self.assertRaises(ValueError):
                helper.parse_request(packet, previous, target)

    def test_exchange_and_oversized_packet(self):
        server, client = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        calls, errors = [], []
        class Target:
            def __init__(self, device):
                calls.append(device)
            def cancel(self):
                calls.append("cancel")
        def run():
            try:
                with client:
                    helper.serve(client, Target)
            except Exception as error:
                errors.append(error)
        worker = threading.Thread(target=run)
        worker.start()
        with server:
            server.settimeout(1)
            for seq, operation in [(1, "HELLO"), (2, "CANCEL")]:
                server.send(f"PR1 {seq} {operation} /dev/input/event42".encode())
                self.assertEqual(server.recv(256), f"PR1 {seq} OK".encode())
            server.send(b"x" * 257)
            self.assertEqual(server.recv(256), b"")
        worker.join(1)
        self.assertFalse(worker.is_alive())
        self.assertEqual(calls, ["/dev/input/event42", "cancel", "cancel"])
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], ValueError)

    def test_failure_is_not_acknowledged(self):
        class Target:
            def __init__(self, device):
                pass
            def cancel(self):
                raise RuntimeError("KWin failed")
        server, client = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        with server, client:
            server.send(b"PR1 1 HELLO /dev/input/event42")
            with self.assertRaises(RuntimeError):
                helper.serve(client, Target)
            server.setblocking(False)
            with self.assertRaises(BlockingIOError):
                server.recv(256)


if __name__ == "__main__":
    unittest.main()
