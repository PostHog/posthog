import pytest

from parameterized import parameterized

from products.marketing_analytics.dags.mmm import (
    MmmConfig,
    MmmRun,
    _calibration_channel_priors,
    _equalize_marginal_roi,
    _interp,
    _marginal_return,
    _sigma_from_ci,
)


def _run(**overrides) -> MmmRun:
    base: dict = {
        "job_id": "job",
        "config": MmmConfig(team_id=2),
        "date_from": None,
        "date_to": None,
        "window_weeks": 1,
        "outcome_kind": "",
        "outcome_ref": "",
        "channels": [],
        "weekly_spend": {},
        "weekly_outcome": {},
        "weekly_controls": {},
        "current_spend": {},
        "total_budget": 0.0,
    }
    base.update(overrides)
    return MmmRun(**base)


class TestMmmRunStatus:
    def test_clean_run_is_ok(self) -> None:
        assert _run().status == "ok"

    def test_run_with_fallbacks_is_degraded(self) -> None:
        # Guards the data-integrity fix: a fit whose curves/diagnostics fell back to placeholders must
        # NOT be persisted as "ok" — otherwise fabricated results are served as authoritative.
        assert _run(degraded_sections={"curves"}).status == "degraded"


class _StubPrior:
    """Captures the (dist, **params) a Prior would be built with, so we can assert the calibration math
    without importing pymc_marketing."""

    def __init__(self, dist: str, **params: float) -> None:
        self.dist = dist
        self.params = params


class TestCalibrationPriors:
    @parameterized.expand(
        [
            # (ci_low, ci_high, expected_sigma) — σ = (high-low)/(2·1.95996)/100
            ("symmetric_9pt_interval", 8.0, 17.0, 0.0229596),
            ("tight_interval", 11.0, 14.0, 0.0076532),
            ("zero_width_floored", 12.5, 12.5, 1e-6),
        ]
    )
    def test_sigma_from_ci(self, _name: str, ci_low: float, ci_high: float, expected_sigma: float) -> None:
        # Guards the inverse-CI σ derivation: a wrong z, or forgetting the /100 lift-fraction scaling,
        # would silently mis-tighten the calibration prior.
        assert _sigma_from_ci(ci_low, ci_high) == pytest.approx(expected_sigma, rel=1e-3)

    def test_manual_lift_yields_expected_prior(self) -> None:
        priors = _calibration_channel_priors(
            {"google": {"lift_pct": 12.5, "ci_low": 8.0, "ci_high": 17.0, "source": "manual"}},
            channels=["google", "meta"],
            prior_cls=_StubPrior,
        )
        # Only the calibrated channel gets a prior; the other keeps the model default (absent here).
        assert set(priors) == {"google"}
        assert priors["google"].dist == "Normal"
        assert priors["google"].params["mu"] == pytest.approx(0.125)
        assert priors["google"].params["sigma"] == pytest.approx(0.0229596, rel=1e-3)

    def test_no_calibrations_yields_no_priors(self) -> None:
        assert _calibration_channel_priors({}, channels=["google"], prior_cls=_StubPrior) == {}


class TestResponseCurveInterpolation:
    @parameterized.expand(
        [
            ("midpoint_of_first_segment", 5.0, 2.5),
            ("midpoint_of_second_segment", 15.0, 6.0),
            ("below_range_clamps_to_first", -1.0, 0.0),
            ("above_range_clamps_to_last", 99.0, 7.0),
        ]
    )
    def test_interp(self, _name: str, x: float, expected: float) -> None:
        # Guards the budget optimizer's curve reader: a broken interpolation would misstate every
        # channel's marginal return and corrupt the reallocation advice.
        points = [(0.0, 0.0), (10.0, 5.0), (20.0, 7.0)]
        assert _interp(points, x) == pytest.approx(expected)

    def test_marginal_return_is_local_slope(self) -> None:
        # Diminishing returns: the same spend step adds less outcome higher up the curve.
        points = [(0.0, 0.0), (10.0, 5.0), (20.0, 7.0)]
        low = _marginal_return(points, current=0.0, step=10.0)
        high = _marginal_return(points, current=10.0, step=10.0)
        assert low == pytest.approx(5.0)
        assert high == pytest.approx(2.0)
        assert low > high


class TestBudgetOptimizer:
    def test_equalize_marginal_roi_reads_stamped_curves(self) -> None:
        # Regression: decompose_and_curves stamps (job_id, team_id) onto the front of each curve row
        # before optimize_budget runs, so the optimizer reads 7-tuples, not the raw 5-tuples produced by
        # _summarize_curves. Before the fix it unpacked 5 values and raised ValueError on every real run,
        # so optimize_budget (and persist_run after it) never completed. Build the stamped shape here.
        stamped_curves = [
            # (job_id, team_id, channel, spend_point, incremental, lower, upper)
            ("job", 2, "google", 0.0, 0.0, 0.0, 0.0),
            ("job", 2, "google", 50.0, 30.0, 25.0, 35.0),
            ("job", 2, "google", 100.0, 45.0, 40.0, 50.0),
            ("job", 2, "meta", 0.0, 0.0, 0.0, 0.0),
            ("job", 2, "meta", 50.0, 20.0, 15.0, 25.0),
            ("job", 2, "meta", 100.0, 28.0, 24.0, 32.0),
        ]
        run = _run(
            channels=["google", "meta"],
            current_spend={"google": 60.0, "meta": 40.0},
            curves=stamped_curves,
        )
        allocation = _equalize_marginal_roi(run, total_budget=100.0)
        assert set(allocation) == {"google", "meta"}
        assert all(spend >= 0.0 for spend in allocation.values())
        # The fixed total budget is fully water-filled across the channels.
        assert sum(allocation.values()) == pytest.approx(100.0, abs=1.0)
