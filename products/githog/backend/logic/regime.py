"""Heuristic to classify a flag / event signal as server-side or client-side.

A "server-side" signal is one captured under a service identity (one or a
few distinct_ids handling many requests) rather than per real end-user.
For these, ``users_affected`` is the count of service identities and is
misleading as a "users" headline — ``call_count`` is the meaningful
production-volume number.

Heuristic: call_count / users_affected. Real humans rarely produce more
than ~50 evaluations or events per signal in a 30-day window; service
identities easily push the ratio into the thousands. The threshold here
is intentionally generous toward "client" so we don't mislabel power
users — only obvious server-side patterns trip the flag.
"""

_RATIO_THRESHOLD = 50
_MIN_CALLS = 100


def is_server_side_signal(users_affected: int, call_count: int) -> bool:
    """Return True when the calls-per-user ratio implies server-side capture.

    Guards against trivially small samples — under ``_MIN_CALLS`` total
    activity we can't draw a confident conclusion either way, so we default
    to "client-side" (the safer label for a small sample).
    """
    if users_affected <= 0 or call_count < _MIN_CALLS:
        return False
    return (call_count / users_affected) >= _RATIO_THRESHOLD
