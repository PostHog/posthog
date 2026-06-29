"""Per-strategy scheduling policy.

`projected_state.py` owns *what* a slot validates against; this package owns *when* slots in a
partition may trial concurrently.
"""

from products.merge_queue.backend.engine.strategies import optimistic, serial
from products.merge_queue.backend.models import Strategy

_CONCURRENT: dict[Strategy, bool] = {
    Strategy.OPTIMISTIC: optimistic.CONCURRENT,
    Strategy.SERIAL: serial.CONCURRENT,
}


def is_concurrent(strategy: Strategy) -> bool:
    """Whether multiple slots in one partition may be in trial at the same time."""
    try:
        return _CONCURRENT[strategy]
    except KeyError:
        raise ValueError(f"strategy not currently supported: {strategy}")
