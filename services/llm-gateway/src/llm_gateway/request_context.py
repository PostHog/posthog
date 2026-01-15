from contextvars import ContextVar

request_id_var: ContextVar[str] = ContextVar("request_id", default="")


def get_request_id() -> str:
    return request_id_var.get()


def set_request_id(request_id: str) -> None:
    request_id_var.set(request_id)
