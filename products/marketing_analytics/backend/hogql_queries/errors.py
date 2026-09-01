class MarketingPrecomputeNotReady(Exception):
    """A precomputable conversion goal has no warm precompute for the requested window.

    Marketing analytics serves exclusively from precompute. Rather than fall back to a live events scan —
    the expensive query this whole path exists to avoid — the read reports not-ready, and the dashboard
    shows a "computing" state until the warmer materializes the window.
    """

    def __init__(self, goal_id: str | None = None) -> None:
        self.goal_id = goal_id
        super().__init__(f"Precompute not ready for conversion goal {goal_id}")
