from time import monotonic

from .types import EngineError

DEFAULT_TIMEOUT_SECONDS = 15 * 60


def run_timeout() -> EngineError:
    return EngineError([{"code": "run_timeout", "message": "This run took too long. Run diff again and retry."}])


def remaining(deadline: float) -> float:
    seconds = deadline - monotonic()
    if seconds <= 0:
        raise run_timeout()
    return seconds
