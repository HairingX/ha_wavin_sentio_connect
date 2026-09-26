"""Send one DHCP request as a Sentio controller would, to try discovery without restarting one.

    python3 scripts/announce_dhcp.py <controller-ip> [host name]

Run it where Home Assistant runs, such as in the dev container, while Home Assistant is running:
its DHCP discovery sees the request, and offers the controller at <controller-ip> when one
answers there. The request carries a made-up hardware address and is broadcast from port 68, so
it needs root, and no DHCP client may hold that port.
"""

import ipaddress
import os
import socket
import sys

DEFAULT_HOST_NAME = "Wavin Sentio CCU#0000"
"""The manual: "Wavin Sentio CCU#" and the last four digits of the serial number."""

HARDWARE_ADDRESS = bytes.fromhex("020000000001")
"""Locally administered, so it can be no real device's."""


def request(ip: str, host_name: str) -> bytes:
    """A DHCP REQUEST (RFC 2131) for `ip`, with `host_name` as option 12."""
    header = (
        bytes([1, 1, 6, 0])                     # BOOTREQUEST, Ethernet, 6-byte address, 0 hops
        + os.urandom(4)                         # transaction id
        + bytes(2) + (0x8000).to_bytes(2)       # seconds; broadcast flag
        + bytes(16)                             # ciaddr, yiaddr, siaddr, giaddr
        + HARDWARE_ADDRESS.ljust(16, b"\0")     # chaddr
        + bytes(64 + 128)                       # sname, file
        + bytes([99, 130, 83, 99])              # magic cookie
    )
    name = host_name.encode()
    options = (
        bytes([53, 1, 3])                                   # message type: REQUEST
        + bytes([50, 4]) + ipaddress.IPv4Address(ip).packed  # requested address
        + bytes([12, len(name)]) + name                     # host name
        + bytes([255])
    )
    return header + options


def main() -> None:
    if len(sys.argv) not in (2, 3):
        sys.exit(__doc__)
    ip = sys.argv[1]
    host_name = sys.argv[2] if len(sys.argv) == 3 else DEFAULT_HOST_NAME
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.bind(("0.0.0.0", 68))
        sock.sendto(request(ip, host_name), ("255.255.255.255", 67))
    print(f"Sent a DHCP request for {ip} as {host_name!r}")


if __name__ == "__main__":
    main()
