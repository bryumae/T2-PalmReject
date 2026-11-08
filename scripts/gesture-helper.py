#!/usr/bin/python3
# SPDX-License-Identifier: GPL-3.0-only
"""Unprivileged, device-scoped bridge to the patched KWin cancellation method."""
import argparse
import os
import pathlib
import re
import socket
import struct
import sys
import time

NAME = "PalmReject MacBookPro16,1 Touchpad"
INTERFACE = "org.kde.KWin.InputDevice"
DEVICE = re.compile(r"/dev/input/(event[0-9]+)\Z")
MESSAGE = re.compile(rb"PR1 ([1-9][0-9]{0,19}) (HELLO|CANCEL) (/dev/input/event[0-9]+)\Z")


def parse_request(packet, previous, selected):
    match = MESSAGE.fullmatch(packet)
    if not match:
        raise ValueError("Malformed gesture request")
    sequence = int(match[1])
    operation = match[2].decode("ascii")
    device = match[3].decode("ascii")
    if sequence != previous + 1 or sequence > 2**64 - 1:
        raise ValueError("Invalid gesture sequence")
    if (previous == 0 and operation != "HELLO") or (previous and operation != "CANCEL"):
        raise ValueError("Unexpected gesture operation")
    if selected is not None and device != selected:
        raise ValueError("Gesture target changed")
    return sequence, operation, device


def validate_device(device):
    match = DEVICE.fullmatch(device)
    if not match:
        raise ValueError("Invalid event node")
    path = (pathlib.Path("/sys/class/input") / match[1] / "device").resolve(strict=True)
    if not str(path).startswith("/sys/devices/virtual/input/"):
        raise ValueError("Gesture target is not virtual")
    if (path / "name").read_text().strip() != NAME:
        raise ValueError("Unexpected gesture target name")
    if int((path / "id/vendor").read_text(), 16) != 0x05AC or int(
        (path / "id/product").read_text(), 16
    ) != 0x0340:
        raise ValueError("Unexpected gesture target identity")
    return match[1]


class KWin:
    def __init__(self, device):
        import dbus
        from xml.etree import ElementTree

        event = validate_device(device)
        self.bus = dbus.SessionBus()
        self.owner = self.bus.get_name_owner("org.kde.KWin")
        self.obj = self.bus.get_object(self.owner, "/org/kde/KWin/InputDevice/" + event,
                                       introspect=False)
        deadline = time.monotonic() + 2
        while True:
            try:
                xml = self.obj.Introspect(dbus_interface="org.freedesktop.DBus.Introspectable",
                                          timeout=0.2)
                break
            except dbus.DBusException as error:
                if error.get_dbus_name() != "org.freedesktop.DBus.Error.UnknownObject" or time.monotonic() >= deadline:
                    raise
                time.sleep(0.01)
        root = ElementTree.fromstring(str(xml))
        if not any(i.get("name") == INTERFACE and
                   any(m.get("name") == "cancelTapGestures" for m in i.findall("method"))
                   for i in root.findall("interface")):
            raise RuntimeError("KWin lacks cancelTapGestures; install the matching patched package")
        props = self.obj.GetAll(INTERFACE, dbus_interface="org.freedesktop.DBus.Properties", timeout=0.2)
        if (props.get("name") != NAME or props.get("sysName") != event or
                not props.get("touchpad") or props.get("vendor") != 0x05AC or
                props.get("product") != 0x0340):
            raise RuntimeError("KWin device identity mismatch")

    def check_owner(self):
        if self.bus.get_name_owner("org.kde.KWin") != self.owner:
            raise RuntimeError("KWin owner changed")

    def cancel(self):
        self.check_owner()
        if not self.obj.cancelTapGestures(dbus_interface=INTERFACE, timeout=0.075):
            raise RuntimeError("KWin rejected gesture cancellation")


def serve(connection, factory=KWin):
    previous, selected, target = 0, None, None
    connection.settimeout(0.25)
    while True:
        try:
            packet, _, flags, _ = connection.recvmsg(256)
        except socket.timeout:
            if target is not None:
                target.check_owner()
            continue
        if not packet:
            return
        if flags & socket.MSG_TRUNC:
            raise ValueError("Oversized gesture request")
        sequence, operation, device = parse_request(packet, previous, selected)
        if operation == "HELLO":
            target = factory(device)
            selected = device
        target.cancel()
        reply = f"PR1 {sequence} OK".encode("ascii")
        if connection.send(reply) != len(reply):
            raise RuntimeError("Short gesture reply")
        previous = sequence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--socket")
    mode.add_argument("--check-session", action="store_true",
                      help="Check the session KWin owner without creating or grabbing input")
    args = parser.parse_args()
    if os.getuid() == 0:
        parser.error("Run as the selected desktop user, not root")
    if args.check_session:
        import dbus
        dbus.SessionBus().get_name_owner("org.kde.KWin")
        return
    with socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET) as connection:
        deadline = time.monotonic() + 10
        while True:
            try:
                connection.connect(args.socket)
                break
            except (FileNotFoundError, ConnectionRefusedError):
                if time.monotonic() >= deadline:
                    raise RuntimeError("Timed out waiting for PalmReject")
                time.sleep(0.025)
        _, uid, _ = struct.unpack("3i", connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
        if uid != 0:
            raise RuntimeError("Gesture server is not root")
        serve(connection)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"Gesture helper: {error}", file=sys.stderr)
        sys.exit(1)
