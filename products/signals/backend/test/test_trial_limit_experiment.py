from uuid import uuid4

import pytest
from unittest.mock import patch

from products.signals.backend.trial.experiment import TRIAL_REPORT_LIMIT_EXPERIMENT, resolve_trial_limits
from products.signals.backend.trial.limits import STANDARD_TRIAL_LIMITS, TrialLimits


@pytest.mark.parametrize(
    "response,limits,reports,variant",
    [
        ("control", STANDARD_TRIAL_LIMITS, 5, "control"),
        ("test", STANDARD_TRIAL_LIMITS, 10, "test"),
        (False, STANDARD_TRIAL_LIMITS, 5, None),
        (None, STANDARD_TRIAL_LIMITS, 5, None),
        (TimeoutError(), STANDARD_TRIAL_LIMITS, 5, None),
        ("test", TrialLimits(allowance_microusd=20_000_000), 5, None),
        ("test", TrialLimits(report_limit=7), 7, None),
    ],
)
def test_resolve_trial_limits(
    response: str | bool | Exception | None, limits: TrialLimits, reports: int, variant: str | None
) -> None:
    org = uuid4()
    with patch("products.signals.backend.trial.experiment.posthoganalytics.get_feature_flag") as flag:
        if isinstance(response, Exception):
            flag.side_effect = response
        else:
            flag.return_value = response
        resolved, assignment = resolve_trial_limits(org, limits)
    assert resolved == TrialLimits(allowance_microusd=limits.allowance_microusd, report_limit=reports)
    assert assignment == variant
    if limits == STANDARD_TRIAL_LIMITS:
        flag.assert_called_once_with(
            TRIAL_REPORT_LIMIT_EXPERIMENT,
            str(org),
            groups={"organization": str(org)},
            group_properties={"organization": {"id": str(org)}},
            send_feature_flag_events=False,
        )
    else:
        flag.assert_not_called()
