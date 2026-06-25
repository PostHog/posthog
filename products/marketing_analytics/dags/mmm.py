"""Marketing Mix Modeling Dagster job (Phase B of the MMM POC).

Fits a Bayesian marketing mix model for one team and persists the results as Parquet to S3, read back
by the staff-only "Mix model" tab through ClickHouse's ``s3(...)`` table function (see
``products/marketing_analytics/backend/mmm_storage.py``). Nothing is written to the ClickHouse cluster
and there are no result tables in Postgres — this mirrors identity matching
(``products/growth/dags/identity_matching.py``) exactly.

Pipeline:

1. ``prepare_dataset`` — load the team, run the Phase-A dataset builder to get the weekly spend panel +
   outcome series, apply the sufficiency guard. Validates the team gate before any I/O.
2. ``fit_mmm`` — import ``pymc_marketing`` *inside the op* (the heavy, C-compiling dep must never load on
   the code-location import path), build geometric-adstock + logistic-saturation MMM, sample with bounded
   draws/chains, and summarize the posterior into small frames. Applies lift-test calibrations as priors.
3. ``decompose_and_curves`` — assemble the per-week contribution decomposition (incl. the ``__baseline__``
   row) and the per-channel response-curve point tables from the fit summary.
4. ``optimize_budget`` — constrained optimizer equalizing marginal ROI across channels under the current
   total budget → a recommended weekly spend per channel.
5. ``persist_run`` — ``write_dataset`` the four datasets (run_meta, contributions, curves, roi) to S3 under
   ``team_<id>/<job_id>/``.

Environment restrictions mirror identity matching: not registered on Cloud EU; on Cloud US only the
allowed internal teams (team 2) are accepted; local/dev/self-hosted are unrestricted. Trigger is manual
via the Dagster UI for the POC.

The PyMC model specifics (exact ``pymc_marketing`` API, method names, sampling budget) must be validated
against the pinned version in MMM-0b — Phase 2 is gated on that spike.
"""

import datetime
from collections import defaultdict
from dataclasses import dataclass, field, replace
from typing import Any, Optional

import dagster
import pydantic

from posthog.schema import DateRange

from posthog import settings
from posthog.clickhouse.cluster import ClickhouseCluster
from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.dags.common import JobOwners, settings_with_log_comment

from products.marketing_analytics.backend.hogql_queries.marketing_mix_dataset_query_runner import (
    MATERIAL_SPEND_WEEKLY_THRESHOLD,
    STATUS_OK,
    MarketingMixDatasetQueryRunner,
)
from products.marketing_analytics.backend.mmm_storage import (
    BASELINE_CHANNEL,
    MARKETING_MMM_S3_UNCONFIGURED_MESSAGE,
    MMM_CONTRIBUTIONS,
    MMM_CONTRIBUTIONS_STRUCTURE,
    MMM_CURVES,
    MMM_CURVES_STRUCTURE,
    MMM_MODEL_VERSION,
    MMM_ROI,
    MMM_ROI_STRUCTURE,
    MMM_RUN_META,
    MMM_RUN_META_STRUCTURE,
    mmm_s3_unconfigured,
    write_dataset,
)

# Internal-only data-safety guardrails, mirroring identity matching: the team-2 data only exists on
# Cloud US. The job is not registered on Cloud EU; on Cloud US it refuses any other team.
PROD_US_ALLOWED_TEAM_IDS: frozenset[int] = frozenset({2})

# Curve x-axis resolution: how many spend points to evaluate each channel's response curve at.
_CURVE_POINTS = 30

# Persisted when the fit completed but a posterior summary fell back to placeholder values.
STATUS_DEGRADED = "degraded"


def is_mmm_registered() -> bool:
    return settings.CLOUD_DEPLOYMENT != "EU"


def validate_team_allowed(team_id: int) -> None:
    if settings.CLOUD_DEPLOYMENT == "EU":
        raise dagster.Failure("Marketing mix modeling does not run on PostHog Cloud EU")
    if settings.CLOUD_DEPLOYMENT == "US" and team_id not in PROD_US_ALLOWED_TEAM_IDS:
        raise dagster.Failure(
            f"On PostHog Cloud US marketing mix modeling may only process teams "
            f"{sorted(PROD_US_ALLOWED_TEAM_IDS)}, got team {team_id}"
        )


class MmmConfig(dagster.Config):
    team_id: int = pydantic.Field(description="Team whose marketing data is modeled.")
    date_from: Optional[str] = pydantic.Field(
        default=None, description="Modeling window start (YYYY-MM-DD). Defaults to ~18 months before today."
    )
    date_to: Optional[str] = pydantic.Field(
        default=None, description="Modeling window end (YYYY-MM-DD). Defaults to today."
    )
    outcome_index: int = pydantic.Field(
        default=0, ge=0, description="Index into the team's conversion goals selecting the outcome to model."
    )
    draws: int = pydantic.Field(default=1000, gt=0, description="Posterior draws per chain (kept small for the POC).")
    tune: int = pydantic.Field(default=1000, gt=0, description="NUTS tuning steps per chain.")
    chains: int = pydantic.Field(default=2, gt=0, description="Number of MCMC chains.")
    target_accept: float = pydantic.Field(default=0.9, gt=0, lt=1, description="NUTS target acceptance probability.")
    adstock_max_lag: int = pydantic.Field(default=8, gt=0, description="Geometric adstock max lag in weeks.")

    def date_range(self) -> Optional[DateRange]:
        if self.date_from and self.date_to:
            return DateRange(date_from=self.date_from, date_to=self.date_to)
        return None


@dataclass
class MmmRun:
    """Run state threaded through the ops: job_id + config plus the small result frames each op adds.

    Deliberately small and plain-Python (no PyMC ``idata`` / posterior arrays) so it serializes cheaply
    across op boundaries — only summarized contributions / curves / roi flow through.
    """

    job_id: str
    config: MmmConfig
    date_from: datetime.date
    date_to: datetime.date
    window_weeks: int
    outcome_kind: str
    outcome_ref: str
    channels: list[str]
    # week ISO string -> {channel: spend}; controls keyed by week ISO string.
    weekly_spend: dict[str, dict[str, float]]
    weekly_outcome: dict[str, float]
    weekly_controls: dict[str, dict[str, float]]
    current_spend: dict[str, float]
    total_budget: float
    # Added by fit_mmm / decompose_and_curves / optimize_budget:
    contributions: list[tuple[Any, ...]] = field(default_factory=list)
    curves: list[tuple[Any, ...]] = field(default_factory=list)
    roi: list[dict[str, Any]] = field(default_factory=list)
    diagnostics: dict[str, float] = field(default_factory=dict)
    calibrated_channels: set[str] = field(default_factory=set)
    # Names of posterior summaries that fell back to placeholder/zeroed values (curves, diagnostics,
    # calibrations). Non-empty → the run is persisted as "degraded" so consumers don't trust it.
    degraded_sections: set[str] = field(default_factory=set)

    @property
    def status(self) -> str:
        return STATUS_DEGRADED if self.degraded_sections else STATUS_OK

    @property
    def team_id(self) -> int:
        return self.config.team_id


@dagster.op
def prepare_dataset(context: dagster.OpExecutionContext, config: MmmConfig) -> MmmRun:
    """Validate the team gate, build the weekly modeling dataset, and apply the sufficiency guard."""
    validate_team_allowed(config.team_id)
    # Fail before any S3 I/O if the scratch bucket env is missing (mirrors identity matching).
    if mmm_s3_unconfigured():
        raise dagster.Failure(MARKETING_MMM_S3_UNCONFIGURED_MESSAGE)

    from posthog.models.team import Team  # noqa: PLC0415 — Django model import kept out of the module import path

    team = Team.objects.get(pk=config.team_id)
    runner = MarketingMixDatasetQueryRunner(
        team=team, date_range=config.date_range(), outcome_index=config.outcome_index
    )
    dataset = runner.run()
    if dataset.status != STATUS_OK:
        raise dagster.Failure(f"Dataset not modelable: {dataset.message}")

    weekly_spend: dict[str, dict[str, float]] = defaultdict(dict)
    spend_by_channel: dict[str, float] = defaultdict(float)
    weeks_by_channel: dict[str, int] = defaultdict(int)
    for row in dataset.spend_panel:
        week = row.week.isoformat()
        weekly_spend[week][row.channel] = row.spend
        spend_by_channel[row.channel] += row.spend
        weeks_by_channel[row.channel] += 1  # spend panel is grouped by (week, channel): one row per channel-week

    weekly_outcome = {row.week.isoformat(): row.outcome for row in dataset.outcome_series}
    weekly_controls = {
        row.week.isoformat(): {
            "control_weekofyear": float(row.control_weekofyear),
            "is_holiday_week": float(row.is_holiday_week),
        }
        for row in dataset.outcome_series
    }
    # Average each channel's spend over the weeks IT actually had spend (not the outcome-week count),
    # so a channel active in only part of the window isn't diluted by unrelated weeks.
    current_spend = {channel: total / max(1, weeks_by_channel[channel]) for channel, total in spend_by_channel.items()}
    total_budget = float(sum(spend_by_channel.values()))

    context.add_output_metadata(
        {
            "channels": dagster.MetadataValue.json(dataset.channels),
            "weeks": dagster.MetadataValue.int(len(weekly_outcome)),
            "total_budget": dagster.MetadataValue.float(round(total_budget, 2)),
        }
    )
    return MmmRun(
        job_id=context.run.run_id,
        config=config,
        date_from=dataset.date_from,
        date_to=dataset.date_to,
        window_weeks=dataset.window_weeks,
        outcome_kind=dataset.outcome_kind,
        outcome_ref=dataset.outcome_ref,
        channels=dataset.channels,
        weekly_spend=dict(weekly_spend),
        weekly_outcome=weekly_outcome,
        weekly_controls=weekly_controls,
        current_spend=current_spend,
        total_budget=total_budget,
    )


@dagster.op
def fit_mmm(context: dagster.OpExecutionContext, run: MmmRun) -> MmmRun:
    """Fit the Bayesian MMM and summarize the posterior into small frames.

    ``pymc_marketing`` (and its heavy ``pytensor`` dependency) are imported here so they never load on
    the Dagster code-location import path — only this op pulls them, mirroring sklearn in identity
    matching's ``train_logreg_and_score``.
    """
    # Heavy ML deps, deferred to keep them off the code-location import path; only this op pulls them.
    # They live in the `mmm` dependency group (pyproject.toml), which is NOT in the main image's
    # `uv sync --no-dev` — the Dagster code-location image must install it (`uv sync ... --group mmm`,
    # mirroring how Dockerfile.llm-analytics installs the `sentiment` group). Fail with that guidance
    # rather than a raw ModuleNotFoundError if the group is missing.
    try:
        import numpy as np  # noqa: PLC0415
        import pandas as pd  # noqa: PLC0415
        from pymc_marketing.mmm import MMM, GeometricAdstock, LogisticSaturation  # noqa: PLC0415
        from pymc_marketing.prior import Prior  # noqa: PLC0415
    except ImportError as error:
        raise dagster.Failure(
            "pymc-marketing is not installed. The MMM job needs the `mmm` dependency group; the Dagster "
            "code-location image must run `uv sync --locked --no-dev --group mmm` (see "
            "Dockerfile.llm-analytics for the `sentiment` group precedent)."
        ) from error

    weeks = sorted(set(run.weekly_outcome) & set(run.weekly_spend))
    if len(weeks) < 2:
        raise dagster.Failure("Not enough overlapping weeks between spend and outcome to fit a model")

    frame = pd.DataFrame(
        {
            "week": pd.to_datetime(weeks),
            **{
                channel: [run.weekly_spend.get(week, {}).get(channel, 0.0) for week in weeks]
                for channel in run.channels
            },
            "control_weekofyear": [run.weekly_controls.get(week, {}).get("control_weekofyear", 0.0) for week in weeks],
            "is_holiday_week": [run.weekly_controls.get(week, {}).get("is_holiday_week", 0.0) for week in weeks],
            "outcome": [run.weekly_outcome.get(week, 0.0) for week in weeks],
        }
    )

    degraded: set[str] = set()
    calibrations = _team_calibrations(run.config.team_id)
    # Phase C: calibrations apply as informative saturation-beta priors (the effective path — see
    # _calibration_channel_priors). A channel with a calibration is flagged for the ROI table. The
    # MMM.add_lift_test_measurements likelihood path is deferred to MMM-0b: it must be added before
    # fit() to influence the posterior, and its exact API is version-sensitive — applying it after a
    # fit with no re-fit (as a prior draft did) is a no-op, so it is intentionally not used here.
    channel_priors = _calibration_channel_priors(calibrations, run.channels, Prior)
    calibrated_channels = {channel for channel in run.channels if channel in calibrations}

    model = MMM(
        date_column="week",
        channel_columns=run.channels,
        control_columns=["control_weekofyear", "is_holiday_week"],
        adstock=GeometricAdstock(l_max=run.config.adstock_max_lag),
        saturation=LogisticSaturation(),
        model_config={"saturation_beta": channel_priors} if channel_priors else None,
    )

    x = frame.drop(columns=["outcome"])
    y = frame["outcome"]
    model.fit(
        x,
        y,
        draws=run.config.draws,
        tune=run.config.tune,
        chains=run.config.chains,
        target_accept=run.config.target_accept,
        progressbar=False,
    )

    contributions = _summarize_contributions(model, run, weeks, np)
    curves = _summarize_curves(context, model, run, np, degraded)
    roi = _summarize_roi(model, run, np)
    diagnostics = _diagnostics(context, model, frame, np, degraded)

    if degraded:
        context.log.warning(f"MMM run will be persisted as degraded; placeholder sections: {sorted(degraded)}")
    context.add_output_metadata(
        {
            "r_squared": dagster.MetadataValue.float(round(diagnostics.get("r_squared", 0.0), 4)),
            "mape": dagster.MetadataValue.float(round(diagnostics.get("mape", 0.0), 4)),
            "divergences": dagster.MetadataValue.int(int(diagnostics.get("divergences", 0))),
            "calibrated_channels": dagster.MetadataValue.json(sorted(calibrated_channels)),
            "degraded_sections": dagster.MetadataValue.json(sorted(degraded)),
        }
    )
    return replace(
        run,
        contributions=contributions,
        curves=curves,
        roi=roi,
        diagnostics=diagnostics,
        calibrated_channels=calibrated_channels,
        degraded_sections=degraded,
    )


@dagster.op
def decompose_and_curves(context: dagster.OpExecutionContext, run: MmmRun) -> MmmRun:
    """Assemble the final contribution rows (adding the ``__baseline__`` row per week) and curve rows.

    ``fit_mmm`` already produced per-channel contributions and curve points; this op adds the baseline
    decomposition row (observed outcome minus the sum of channel contributions) and stamps the run/team
    id onto every row so the rows are ready for ``write_dataset``.
    """
    job_id, team_id = run.job_id, run.team_id

    # Baseline per week = observed outcome minus the summed channel contributions (intercept + controls).
    contribution_by_week: dict[str, float] = defaultdict(float)
    spend_present: list[tuple[Any, ...]] = []
    for week, channel, spend, contribution, lower, upper in run.contributions:
        contribution_by_week[week] += contribution
        spend_present.append((job_id, team_id, week, channel, spend, contribution, lower, upper))

    baseline_rows: list[tuple[Any, ...]] = []
    for week_str, outcome in run.weekly_outcome.items():
        week = datetime.date.fromisoformat(week_str)
        # Keep the baseline unclamped so the decomposition stays additive (channels + baseline =
        # outcome). A negative baseline is a real signal that the model over-attributed that week;
        # clamping it to 0 would hide that and break the stacked decomposition's identity.
        baseline = outcome - contribution_by_week.get(week_str, 0.0)
        baseline_rows.append((job_id, team_id, week, BASELINE_CHANNEL, 0.0, baseline, baseline, baseline))

    contributions = [
        (job_id, team_id, _as_date(week), channel, spend, contribution, lower, upper)
        for (job_id, team_id, week, channel, spend, contribution, lower, upper) in spend_present
    ] + baseline_rows

    curves = [(job_id, team_id, channel, sp, inc, lo, hi) for (channel, sp, inc, lo, hi) in run.curves]

    context.add_output_metadata({"contribution_rows": dagster.MetadataValue.int(len(contributions))})
    return replace(run, contributions=contributions, curves=curves)


@dagster.op
def optimize_budget(context: dagster.OpExecutionContext, run: MmmRun) -> MmmRun:
    """Constrained optimizer equalizing marginal ROI across channels under the current total budget.

    Produces a recommended weekly spend per channel. Greedy water-filling on the per-channel marginal
    ROI (derived from each response curve) under the fixed total current budget — advisory only.
    """
    total_weekly_budget = sum(run.current_spend.values())
    recommended = _equalize_marginal_roi(run, total_weekly_budget)

    roi_rows: list[dict[str, Any]] = []
    for entry in run.roi:
        channel = entry["channel"]
        roi_rows.append(
            {
                **entry,
                "current_spend": run.current_spend.get(channel, 0.0),
                "recommended_spend": recommended.get(channel, run.current_spend.get(channel, 0.0)),
                "calibrated": 1 if channel in run.calibrated_channels else 0,
            }
        )
    context.add_output_metadata({"channels_optimized": dagster.MetadataValue.int(len(roi_rows))})
    return replace(run, roi=roi_rows)


@dagster.op
def persist_run(
    context: dagster.OpExecutionContext, cluster: dagster.ResourceParam[ClickhouseCluster], run: MmmRun
) -> None:
    """Write the four datasets to S3 as Parquet via the ClickHouse cluster (no boto3)."""
    computed_at = datetime.datetime.now()
    team_id, job_id = run.team_id, run.job_id

    run_meta_row = (
        job_id,
        team_id,
        run.status,  # "ok" or "degraded" depending on whether any posterior summary fell back
        MMM_MODEL_VERSION,
        run.outcome_kind,
        run.outcome_ref,
        run.date_from,
        run.date_to,
        run.window_weeks,
        run.channels,
        float(run.diagnostics.get("r_squared", 0.0)),
        float(run.diagnostics.get("mape", 0.0)),
        int(run.diagnostics.get("divergences", 0)),
        run.total_budget,
        computed_at,
    )
    roi_rows = [
        (
            job_id,
            team_id,
            entry["channel"],
            float(entry.get("roi", 0.0)),
            float(entry.get("roi_lower", 0.0)),
            float(entry.get("roi_upper", 0.0)),
            float(entry.get("marginal_roi", 0.0)),
            float(entry.get("current_spend", 0.0)),
            float(entry.get("recommended_spend", 0.0)),
            int(entry.get("calibrated", 0)),
        )
        for entry in run.roi
    ]

    # Tag the cluster INSERTs: the cluster path can't read thread-local query tags, so snapshot the
    # active tags_context (product/feature) into a log_comment via settings_with_log_comment and pass
    # it through — matching how identity matching attributes its Dagster writes.
    # Write run_meta LAST: a run becomes discoverable (mmm_runs globs run_meta, mmm_run keys off it)
    # only once its detail datasets exist, so a partial write can't surface a run with empty details.
    with tags_context(product=Product.MARKETING_ANALYTICS, feature=Feature.QUERY):
        write_settings = settings_with_log_comment(context)
        write_dataset(
            cluster, team_id, job_id, MMM_CONTRIBUTIONS, MMM_CONTRIBUTIONS_STRUCTURE, run.contributions, write_settings
        )
        write_dataset(cluster, team_id, job_id, MMM_CURVES, MMM_CURVES_STRUCTURE, run.curves, write_settings)
        write_dataset(cluster, team_id, job_id, MMM_ROI, MMM_ROI_STRUCTURE, roi_rows, write_settings)
        write_dataset(cluster, team_id, job_id, MMM_RUN_META, MMM_RUN_META_STRUCTURE, [run_meta_row], write_settings)

    context.add_output_metadata(
        {
            "job_id": dagster.MetadataValue.text(job_id),
            "contributions": dagster.MetadataValue.int(len(run.contributions)),
            "curves": dagster.MetadataValue.int(len(run.curves)),
            "roi": dagster.MetadataValue.int(len(roi_rows)),
        }
    )


# ---------------------------------------------------------------------------
# Calibration → priors (Phase C)
# ---------------------------------------------------------------------------


# 95% two-sided normal quantile (norm.ppf(0.975)); matches the experiments engine's CI convention.
_Z_95 = 1.959963984540054


def _sigma_from_ci(ci_low: float, ci_high: float) -> float:
    """Posterior σ implied by a 95% credible interval: σ = (upper − lower) / (2·z), in lift fraction.

    The interval is expressed in lift percentage points, so divide by 100 to match the lift-fraction
    mean. Floored at a tiny positive value so a zero-width interval still yields a proper prior. This
    is exactly the inverse of how the experiments engine builds its interval (mean ± z·σ).
    """
    return max((float(ci_high) - float(ci_low)) / (2.0 * _Z_95) / 100.0, 1e-6)


def _team_calibrations(team_id: int) -> dict[str, dict[str, Any]]:
    from posthog.models.team import Team  # noqa: PLC0415

    team = Team.objects.get(pk=team_id)
    return team.marketing_analytics_config.mmm_channel_calibrations or {}


def _calibration_channel_priors(calibrations: dict[str, dict[str, Any]], channels: list[str], prior_cls) -> dict:
    """Build per-channel saturation-beta priors from calibrations, the way the experiments engine forms
    a ``GaussianPrior(mean, variance)``: center on the measured lift, set variance from the CI half-width
    (σ = (ci_high − ci_low) / (2·z), z≈1.96 for a 95% interval). Channels without a calibration keep the
    model default.
    """
    if not calibrations:
        return {}
    priors: dict[str, Any] = {}
    for channel in channels:
        config = calibrations.get(channel)
        if not config:
            continue
        mean = float(config["lift_pct"]) / 100.0
        sigma = _sigma_from_ci(config["ci_low"], config["ci_high"])
        priors[channel] = prior_cls("Normal", mu=mean, sigma=sigma)
    return priors


# ---------------------------------------------------------------------------
# Posterior summarization helpers (best-effort; validate exact API in MMM-0b)
# ---------------------------------------------------------------------------


def _hdi_bounds(samples, np) -> tuple[float, float]:
    """5%/95% credible interval of a flat sample array."""
    flat = np.asarray(samples).reshape(-1)
    if flat.size == 0:
        return 0.0, 0.0
    return float(np.quantile(flat, 0.05)), float(np.quantile(flat, 0.95))


def _summarize_contributions(model, run: MmmRun, weeks: list[str], np) -> list[tuple[Any, ...]]:
    """Per (week, channel) posterior-mean contribution with a 90% credible interval.

    Uses ``compute_channel_contribution_original_scale()`` (dims chain, draw, date, channel). Validate
    the accessor name against the pinned pymc-marketing in MMM-0b.
    """
    contributions = model.compute_channel_contribution_original_scale()
    rows: list[tuple[Any, ...]] = []
    for c_index, channel in enumerate(run.channels):
        per_date = contributions.isel(channel=c_index)  # dims: chain, draw, date
        mean_by_date = per_date.mean(dim=["chain", "draw"]).values
        for d_index, week in enumerate(weeks):
            samples = per_date.isel(date=d_index).values
            lower, upper = _hdi_bounds(samples, np)
            spend = run.weekly_spend.get(week, {}).get(channel, 0.0)
            rows.append((week, channel, float(spend), float(mean_by_date[d_index]), lower, upper))
    return rows


def _summarize_curves(
    context: dagster.OpExecutionContext, model, run: MmmRun, np, degraded: set[str]
) -> list[tuple[Any, ...]]:
    """Per-channel response curve: incremental outcome over a spend grid from 0 to ~2× current spend.

    If the response-curve sampler isn't available in the pinned pymc-marketing, falls back to a
    placeholder curve, logs the failure, and records "curves" in ``degraded`` so the run is persisted
    as degraded rather than silently serving a fabricated curve as if it were a fitted one.
    """
    rows: list[tuple[Any, ...]] = []
    for channel in run.channels:
        max_spend = max(run.current_spend.get(channel, 0.0) * 2.0, 1.0)
        grid = np.linspace(0.0, max_spend, _CURVE_POINTS)
        # The saturation transform maps spend → diminishing incremental outcome; sample it across the
        # posterior to get a mean + 90% band per grid point. Exact API validated in MMM-0b.
        try:
            curve = model.sample_response_distribution(channel=channel, spend_grid=grid)
            mean = np.asarray(curve).mean(axis=0)
            lower = np.quantile(np.asarray(curve), 0.05, axis=0)
            upper = np.quantile(np.asarray(curve), 0.95, axis=0)
        except Exception:
            context.log.exception(f"MMM response-curve sampler failed for channel {channel!r}; using placeholder")
            degraded.add("curves")
            # Placeholder so the dataset stays well-formed; the degraded status warns it isn't real.
            mean = grid / (grid + max_spend / 2.0)
            lower = mean * 0.8
            upper = mean * 1.2
        for i, spend_point in enumerate(grid):
            rows.append((channel, float(spend_point), float(mean[i]), float(lower[i]), float(upper[i])))
    return rows


def _summarize_roi(model, run: MmmRun, np) -> list[dict[str, Any]]:
    """Per-channel ROI (incremental outcome per unit spend) with a 90% credible interval + marginal ROI."""
    contributions = model.compute_channel_contribution_original_scale()
    rows: list[dict[str, Any]] = []
    for c_index, channel in enumerate(run.channels):
        total_spend = sum(week.get(channel, 0.0) for week in run.weekly_spend.values())
        # Don't compute ROI for a channel whose total spend is below one week's material threshold:
        # dividing a real contribution by a near-zero spend yields an arbitrarily large ROI that would
        # dominate the table and skew the optimizer. Report zeros instead of a divide-by-tiny artifact.
        if total_spend < MATERIAL_SPEND_WEEKLY_THRESHOLD:
            rows.append({"channel": channel, "roi": 0.0, "roi_lower": 0.0, "roi_upper": 0.0, "marginal_roi": 0.0})
            continue
        per_draw_total = contributions.isel(channel=c_index).sum(dim="date")  # dims chain, draw
        roi_samples = np.asarray(per_draw_total.values).reshape(-1) / total_spend
        roi_mean = float(np.mean(roi_samples)) if roi_samples.size else 0.0
        roi_lower, roi_upper = _hdi_bounds(roi_samples, np)
        rows.append(
            {
                "channel": channel,
                "roi": roi_mean,
                "roi_lower": roi_lower,
                "roi_upper": roi_upper,
                # Marginal ROI at current spend ≈ average ROI scaled by the saturation slope; the
                # optimizer refines this. Start with the mean ROI as a conservative proxy.
                "marginal_roi": roi_mean,
            }
        )
    return rows


def _diagnostics(context: dagster.OpExecutionContext, model, frame, np, degraded: set[str]) -> dict[str, float]:
    """In-sample R² / MAPE of the posterior-mean fit, plus the sampler divergence count.

    A failure to read any diagnostic is logged and recorded in ``degraded`` so the run is marked
    degraded — otherwise the 0.0 defaults are indistinguishable from a genuinely clean fit (divergences=0
    reads as "healthy sampling" when it may mean "couldn't read the diagnostic").
    """
    diagnostics: dict[str, float] = {"r_squared": 0.0, "mape": 0.0, "divergences": 0.0}
    try:
        idata = model.idata
        diagnostics["divergences"] = float(int(idata.sample_stats["diverging"].values.sum()))
    except Exception:
        context.log.exception("MMM divergence diagnostic unavailable; defaulting to 0 and marking degraded")
        degraded.add("diagnostics")
    try:
        predicted = np.asarray(model.get_target_transformer().inverse_transform(model.posterior_predictive_mean()))
        actual = frame["outcome"].to_numpy()
        ss_res = float(np.sum((actual - predicted) ** 2))
        ss_tot = float(np.sum((actual - actual.mean()) ** 2)) or 1.0
        diagnostics["r_squared"] = 1.0 - ss_res / ss_tot
        nonzero = actual != 0
        if nonzero.any():
            diagnostics["mape"] = float(np.mean(np.abs((actual[nonzero] - predicted[nonzero]) / actual[nonzero])))
    except Exception:
        context.log.exception("MMM fit-quality diagnostics unavailable; defaulting to 0 and marking degraded")
        degraded.add("diagnostics")
    return diagnostics


def _equalize_marginal_roi(run: MmmRun, total_budget: float) -> dict[str, float]:
    """Greedy water-filling: allocate the fixed total budget towards channels with the highest marginal
    ROI until marginal ROIs equalize, using each channel's response curve as the marginal-return source.

    A simple, transparent allocator for the POC — not a full constrained optimizer. Allocates in small
    increments to the channel whose curve currently has the steepest local slope.
    """
    if total_budget <= 0 or not run.channels:
        return dict(run.current_spend)

    # Per-channel curve as (spend_point -> incremental_outcome) for marginal-slope lookups.
    # ``decompose_and_curves`` stamps (job_id, team_id) onto the front of each curve row before this op
    # runs, so unpack the trailing 5 fields — this stays correct whether or not the rows are stamped.
    curve_by_channel: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for *_, channel, spend_point, incremental, _lo, _hi in run.curves:
        curve_by_channel[channel].append((float(spend_point), float(incremental)))
    for points in curve_by_channel.values():
        points.sort()

    allocation = dict.fromkeys(run.channels, 0.0)
    step = total_budget / 200.0 if total_budget else 0.0
    remaining = total_budget
    while remaining > 1e-9 and step > 0:
        best_channel, best_marginal = None, -1.0
        for channel in run.channels:
            marginal = _marginal_return(curve_by_channel.get(channel, []), allocation[channel], step)
            if marginal > best_marginal:
                best_channel, best_marginal = channel, marginal
        if best_channel is None:
            break
        spend_now = min(step, remaining)
        allocation[best_channel] += spend_now
        remaining -= spend_now
    return allocation


def _marginal_return(points: list[tuple[float, float]], current: float, step: float) -> float:
    """Incremental outcome from adding ``step`` spend at ``current`` level, read off the response curve."""
    if not points:
        return 0.0
    return _interp(points, current + step) - _interp(points, current)


def _interp(points: list[tuple[float, float]], x: float) -> float:
    """Linear interpolation of a sorted (spend, outcome) curve at spend ``x``."""
    if not points:
        return 0.0
    if x <= points[0][0]:
        return points[0][1]
    if x >= points[-1][0]:
        return points[-1][1]
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if x0 <= x <= x1:
            span = x1 - x0
            return y0 if span == 0 else y0 + (y1 - y0) * (x - x0) / span
    return points[-1][1]


def _as_date(week: Any) -> datetime.date:
    if isinstance(week, datetime.date):
        return week
    return datetime.date.fromisoformat(str(week))


@dagster.job(tags={"owner": JobOwners.TEAM_WEB_ANALYTICS.value})
def mmm_job():
    run = prepare_dataset()
    run = fit_mmm(run)
    run = decompose_and_curves(run)
    run = optimize_budget(run)
    persist_run(run)
