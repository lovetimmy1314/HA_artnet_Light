"""Fake Art-Net node for testing the integration without hardware.

Answers ArtPoll (so the node shows up in discovery) and prints received DMX.

    python tools/fake_node.py --ip 192.168.1.50 --name TestNode --universes 0 1

Run it on a machine on the same LAN as Home Assistant (not on the HA host
itself, since both want UDP 6454).
"""

from __future__ import annotations

import argparse
from pathlib import Path
import socket
import sys
import types

PKG_DIR = Path(__file__).resolve().parent.parent / "custom_components" / "artnet_light"
_pkg = types.ModuleType("artnet_core")
_pkg.__path__ = [str(PKG_DIR)]
sys.modules.setdefault("artnet_core", _pkg)

from artnet_core.artnet import ARTNET_PORT, build_artpollreply, is_artpoll, parse_artdmx  # noqa: E402


def local_ip() -> str:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ip", default=None, help="IP to report in ArtPollReply (default: auto)")
    parser.add_argument("--name", default="FakeNode")
    parser.add_argument("--mac", default="02:00:00:00:00:01")
    parser.add_argument("--universes", type=int, nargs="*", default=[0])
    parser.add_argument("--channels", type=int, default=16, help="how many channels to print")
    args = parser.parse_args()

    ip = args.ip or local_ip()
    reply = build_artpollreply(ip, args.name, f"{args.name} (fake)", mac=args.mac, universes=args.universes)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.bind(("0.0.0.0", ARTNET_PORT))
    print(f"Fake Art-Net node '{args.name}' at {ip}, universes {args.universes}; listening on {ARTNET_PORT}")

    last: dict[int, bytes] = {}
    while True:
        data, addr = sock.recvfrom(1024)
        if is_artpoll(data):
            sock.sendto(reply, (addr[0], ARTNET_PORT))
            if addr[1] != ARTNET_PORT:
                sock.sendto(reply, addr)
            print(f"ArtPoll from {addr[0]}:{addr[1]} -> replied")
        elif dmx := parse_artdmx(data):
            universe, seq, payload = dmx
            head = payload[: args.channels]
            if last.get(universe) != head:  # only print changes, skip keep-alives
                last[universe] = head
                print(f"U{universe:<3} seq {seq:3}: " + " ".join(f"{b:3}" for b in head))


if __name__ == "__main__":
    main()
