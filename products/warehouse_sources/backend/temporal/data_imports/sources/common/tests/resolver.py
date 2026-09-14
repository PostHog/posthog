import socket


# nosemgrep: semgrep.rules.devex.tuple-return-prefer-dataclass -- mirrors socket.getaddrinfo's positional result
def addrinfo(port: int, *addresses: str) -> list[tuple[int, int, int, str, tuple[str, int]]]:
    return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (address, port)) for address in addresses]
