from typing import Any


class MarketingPrecomputeNotReady(Exception):
    """A precomputable conversion goal has no warm precompute for the requested window.

    Marketing analytics serves exclusively from precompute. Rather than fall back to a live events scan —
    the expensive query this whole path exists to avoid — the read reports not-ready, and the dashboard
    shows a "computing" state until the warmer materializes the window.
    """

    def __init__(self, goal_id: str | None = None) -> None:
        self.goal_id = goal_id
        # The query whose window was missing, stamped by the runner that was building when it raised. In
        # compare mode the previous-period runner carries a shifted date range, so warming the outer
        # runner's query would build a window that was never the one that missed.
        self.query: Any = None
        super().__init__(f"Precompute not ready for conversion goal {goal_id}")
