from enum import StrEnum

from botocore.exceptions import ClientError, EndpointConnectionError, ReadTimeoutError

AWS_ENDPOINT = "https://email.us-east-1.amazonaws.com"


class AwsFault(StrEnum):
    THROTTLING = "throttling"
    ACCESS_DENIED = "access_denied"
    INVALID_PARAMETER = "invalid_parameter"
    ENDPOINT_UNREACHABLE = "endpoint_unreachable"
    READ_TIMEOUT = "read_timeout"

    def error(self, operation: str) -> Exception:
        match self:
            case AwsFault.THROTTLING:
                return _client_error("Throttling", operation)
            case AwsFault.ACCESS_DENIED:
                return _client_error("AccessDenied", operation)
            case AwsFault.INVALID_PARAMETER:
                return _client_error("InvalidParameterValue", operation)
            case AwsFault.ENDPOINT_UNREACHABLE:
                return EndpointConnectionError(endpoint_url=AWS_ENDPOINT)
            case AwsFault.READ_TIMEOUT:
                return ReadTimeoutError(endpoint_url=AWS_ENDPOINT)


class DnsFault(StrEnum):
    TIMEOUT = "timeout"
    SERVFAIL = "servfail"
    NXDOMAIN = "nxdomain"


class HttpFault(StrEnum):
    SERVER_ERROR = "server_error"
    RATE_LIMITED = "rate_limited"
    TIMEOUT = "timeout"
    MALFORMED_JSON = "malformed_json"
    MISSING_URL_SYNC_UX = "missing_url_sync_ux"


Fault = AwsFault | DnsFault | HttpFault


class FaultInjector:
    """Faults keyed by operation, such as `ses.get_identity_dkim_attributes`, `dns:zone:_dmarc.example.com/TXT`
    or `http.get:settings`. A fault holds until it is cleared, so retries inside a client see it too."""

    def __init__(self) -> None:
        self._faults: dict[str, Fault] = {}

    def inject(self, operation: str, fault: Fault) -> None:
        self._faults[operation] = fault

    def clear(self) -> None:
        self._faults.clear()

    def fault_for(self, *operations: str) -> Fault | None:
        return next((self._faults[operation] for operation in operations if operation in self._faults), None)


def _client_error(code: str, operation: str) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": f"Injected {code}"}}, operation)
