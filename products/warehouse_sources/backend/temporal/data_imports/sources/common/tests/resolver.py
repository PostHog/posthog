import re
import socket
import ipaddress
from collections.abc import Callable

_HOSTNAME = re.compile(r"[A-Za-z0-9.-]+")


# nosemgrep: semgrep.rules.devex.tuple-return-prefer-dataclass -- mirrors socket.getaddrinfo's positional result
def addrinfo(port: int, *addresses: str) -> list[tuple[int, int, int, str, tuple[str, int]]]:
    return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (address, port)) for address in addresses]


# A stand-in for `socket.getaddrinfo` that answers `addresses` for any IP address or hostname. It
# fails any other string, such as a bracketed IPv6 address, the way the system resolver does, so a
# test can tell whether the host reached the lookup in a form the resolver accepts.
def resolver(*addresses: str) -> Callable[..., list[tuple[int, int, int, str, tuple[str, int]]]]:
    def getaddrinfo(host: str, *_args: object, **_kwargs: object) -> list[tuple[int, int, int, str, tuple[str, int]]]:
        try:
            ipaddress.ip_address(host)
        except ValueError:
            if not _HOSTNAME.fullmatch(host):
                raise socket.gaierror(socket.EAI_NONAME, "Name or service not known")
        return addrinfo(0, *addresses)

    return getaddrinfo
