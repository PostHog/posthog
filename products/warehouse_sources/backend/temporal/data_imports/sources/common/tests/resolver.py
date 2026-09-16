import socket
from collections.abc import Callable


# nosemgrep: semgrep.rules.devex.tuple-return-prefer-dataclass -- mirrors socket.getaddrinfo's positional result
def addrinfo(port: int, *addresses: str) -> list[tuple[int, int, int, str, tuple[str, int]]]:
    return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (address, port)) for address in addresses]


# A stand-in for `socket.getaddrinfo` that answers `addresses` for any name, and fails a bracketed
# IPv6 address the way the system resolver does, so a test can tell whether the brackets came off.
def resolver(*addresses: str) -> Callable[..., list[tuple[int, int, int, str, tuple[str, int]]]]:
    def getaddrinfo(host: str, *_args: object, **_kwargs: object) -> list[tuple[int, int, int, str, tuple[str, int]]]:
        if host.startswith("["):
            raise socket.gaierror(socket.EAI_NONAME, "Name or service not known")
        return addrinfo(0, *addresses)

    return getaddrinfo
