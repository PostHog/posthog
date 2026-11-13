from posthog.dataclasses import frozen

MAX_TRIAL_GRANTS_PER_ORGANIZATION = 1
# Held against the allowance for each research run in flight, because a run books most of its cost when it ends.
TRIAL_RESEARCH_RESERVE_MICROUSD = 1_700_000
TRIAL_OPEN_SIGNAL_LIMIT = 10
TRIAL_FIRST_SYNC_RECORD_LIMIT = 3


@frozen
class TrialLimits:
    allowance_microusd: int = 10_000_000
    report_limit: int = 5

    def __post_init__(self) -> None:
        if type(self.allowance_microusd) is not int or self.allowance_microusd <= 0:
            raise ValueError("Trial allowance must be a positive integer in micro-USD")
        if type(self.report_limit) is not int or self.report_limit <= 0:
            raise ValueError("Trial report limit must be a positive integer")


STANDARD_TRIAL_LIMITS = TrialLimits()
