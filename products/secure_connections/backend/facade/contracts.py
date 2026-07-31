from dataclasses import dataclass
from enum import StrEnum


class SecureConnectionState(StrEnum):
    NOT_CONFIGURED = "not_configured"
    WAITING = "waiting"
    CONNECTED = "connected"


@dataclass(frozen=True)
class SecureConnection:
    id: str
    name: str
    connection_type: str
    connection_status: str
    selector_kind: str
    selector: str


@dataclass(frozen=True)
class SecureConnectionStatus:
    connection_state: SecureConnectionState
    connections: tuple[SecureConnection, ...]


@dataclass(frozen=True)
class SecureConnectionEnrollment:
    enrollment_key: str
    advertisement_token: str
    tenant_id: str
    control_url: str
