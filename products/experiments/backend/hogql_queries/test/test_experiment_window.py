from datetime import UTC, datetime

from unittest import TestCase

from parameterized import parameterized

from posthog.models.team.team import Team

from products.experiments.backend.hogql_queries.base_query_utils import experiment_window, experiment_window_end
from products.experiments.backend.models.experiment import Experiment


def _exp(start: datetime | None, end: datetime | None) -> Experiment:
    # Unsaved instance: the window helpers only read start_date / end_date, no DB access needed.
    return Experiment(start_date=start, end_date=end)


_START = datetime(2026, 1, 1, tzinfo=UTC)
_AS_OF = datetime(2026, 1, 20, tzinfo=UTC)
_PAST_END = datetime(2026, 1, 10, tzinfo=UTC)
_FUTURE_END = datetime(2026, 2, 1, tzinfo=UTC)


class TestExperimentWindow(TestCase):
    @parameterized.expand(
        [
            # The edge is the earlier of as_of and end_date (end_date is +inf when unset). _AS_OF is
            # after _PAST_END but before _FUTURE_END.
            ("running_returns_as_of", None, _AS_OF),
            ("ended_capped_at_end_date", _PAST_END, _PAST_END),
            ("future_end_capped_at_as_of", _FUTURE_END, _AS_OF),
        ]
    )
    def test_window_end(self, _name: str, end_date: datetime | None, expected: datetime) -> None:
        assert experiment_window_end(_exp(_START, end_date), _AS_OF) == expected

    def test_ended_window_is_stable_once_as_of_passes_end_date(self) -> None:
        # Core invariant: once as_of reaches end_date, the window end stays end_date no matter when (or
        # how often) results are recomputed. This is what prevents post-end data from leaking in.
        exp = _exp(_START, _PAST_END)
        for as_of in [
            datetime(2026, 1, 11, tzinfo=UTC),
            datetime(2026, 6, 1, tzinfo=UTC),
            datetime(2027, 1, 1, tzinfo=UTC),
        ]:
            assert experiment_window_end(exp, as_of) == _PAST_END

    def test_as_of_before_end_date_wins(self) -> None:
        # The timeseries case: a per-day backfill point mid-experiment must keep its own as_of so the
        # daily points stay distinct rather than all collapsing onto end_date.
        mid_experiment = datetime(2026, 1, 5, tzinfo=UTC)
        assert experiment_window_end(_exp(_START, _PAST_END), mid_experiment) == mid_experiment

    def test_window_uses_end_date_when_set(self) -> None:
        date_range = experiment_window(_exp(_START, _PAST_END), Team(timezone="UTC"), _AS_OF)
        assert date_range.date_from == _START.isoformat()
        assert date_range.date_to == _PAST_END.isoformat()

    def test_running_window_ends_at_as_of(self) -> None:
        date_range = experiment_window(_exp(_START, None), Team(timezone="UTC"), _AS_OF)
        assert date_range.date_to == _AS_OF.isoformat()

    def test_draft_experiment_has_empty_window(self) -> None:
        date_range = experiment_window(_exp(None, None), Team(timezone="UTC"), _AS_OF)
        assert date_range.date_from is None
        assert date_range.date_to is None
