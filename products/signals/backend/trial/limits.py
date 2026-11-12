from posthog.dataclasses import frozen

MAX_TRIAL_GRANTS_PER_ORGANIZATION = 1


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
