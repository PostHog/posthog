"""Read-only API for the Marketing Mix Modeling (MMM) POC.

These actions hang off `MarketingAnalyticsViewSet` (via `MmmActionsMixin`) but are isolated here
because MMM is a self-contained, staff-gated POC. There are two kinds:

- `mmm_dataset` runs the Phase-A dataset builder live (it does not touch S3) and returns the weekly
  modeling panel, with an optional `?format=csv` export — the "bring your own model" path.
- `mmm_runs` / `mmm_run` read the four Parquet datasets a completed MMM Dagster run wrote to S3,
  back through ClickHouse's `s3(...)` table function (see mmm_storage). They persist nothing and
  degrade to an empty result when the team has no runs yet.

Everything is staff-gated while in development (mirroring the identity matching read API). The
`MARKETING_ANALYTICS_MMM` feature flag gates the UI tab; staff is the server-side security boundary.
"""

import csv
from typing import Any, cast

from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import StreamingHttpResponse

import structlog
from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_serializer
from rest_framework import serializers, status
from rest_framework.decorators import action
from rest_framework.exceptions import (
    APIException,
    PermissionDenied,
    ValidationError as DRFValidationError,
)
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.schema import DateRange

from posthog.api.mixins import validated_request
from posthog.models.user import User

from .hogql_queries.marketing_mix_dataset_query_runner import (
    MarketingMixDataset,
    MarketingMixDatasetQueryRunner,
    default_window,
)
from .mmm_storage import (
    ALL_RUNS,
    MARKETING_MMM_S3_UNCONFIGURED_MESSAGE,
    MMM_CONTRIBUTIONS,
    MMM_CONTRIBUTIONS_STRUCTURE,
    MMM_CURVES,
    MMM_CURVES_STRUCTURE,
    MMM_ROI,
    MMM_ROI_STRUCTURE,
    MMM_RUN_META,
    MMM_RUN_META_STRUCTURE,
    MMM_RUN_STATUSES,
    mmm_s3_unconfigured,
    read_dataset,
)

logger = structlog.get_logger(__name__)

MAX_RUNS_LISTED = 50
DEFAULT_PANEL_LIMIT = 500

# run_meta columns in their stored order, reused for the runs list and single-run reads.
_RUN_META_COLUMNS = [
    "job_id",
    "status",
    "model_version",
    "outcome_kind",
    "outcome_ref",
    "date_from",
    "date_to",
    "window_weeks",
    "channels",
    "r_squared",
    "mape",
    "divergences",
    "total_budget",
    "computed_at",
]


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------


class MmmDatasetQuerySerializer(serializers.Serializer):
    date_from = serializers.CharField(
        required=False,
        help_text="Modeling window start (inclusive), YYYY-MM-DD. Defaults to ~18 months before today.",
    )
    date_to = serializers.CharField(
        required=False, help_text="Modeling window end (inclusive), YYYY-MM-DD. Defaults to today."
    )
    outcome_index = serializers.IntegerField(
        required=False,
        default=0,
        min_value=0,
        help_text="Zero-based index into the project's configured conversion goals selecting the outcome to model.",
    )
    limit = serializers.IntegerField(
        required=False,
        default=DEFAULT_PANEL_LIMIT,
        min_value=1,
        max_value=2000,
        help_text="Page size for the week×channel spend panel (the outcome series is always returned in full).",
    )
    offset = serializers.IntegerField(
        required=False, default=0, min_value=0, help_text="Pagination offset into the spend panel."
    )


class MmmSpendPanelRowSerializer(serializers.Serializer):
    week = serializers.DateField(help_text="Start of the week the spend falls in (ClickHouse toStartOfWeek).")
    channel = serializers.CharField(help_text="Ad platform the spend belongs to (the source's normalized name).")
    spend = serializers.FloatField(help_text="Total spend in the team's base currency for this channel-week.")
    impressions = serializers.FloatField(help_text="Total impressions for this channel-week.")
    clicks = serializers.FloatField(help_text="Total clicks for this channel-week.")


class MmmOutcomeRowSerializer(serializers.Serializer):
    week = serializers.DateField(help_text="Start of the week the outcome falls in (ClickHouse toStartOfWeek).")
    outcome = serializers.FloatField(help_text="Conversion-goal outcome value for the week (count or summed value).")
    control_weekofyear = serializers.IntegerField(help_text="ISO week-of-year, a seasonality control for the model.")
    is_holiday_week = serializers.BooleanField(help_text="Whether the week overlaps a known holiday-heavy period.")


@extend_schema_serializer(many=False)
class MmmDatasetResponseSerializer(serializers.Serializer):
    status = serializers.CharField(
        help_text=f"Dataset readiness: one of {MMM_RUN_STATUSES}. 'insufficient_history' means the "
        "sufficiency guard or a missing conversion goal blocked modeling — see `message`."
    )
    message = serializers.CharField(allow_blank=True, help_text="Human-readable explanation when status is not 'ok'.")
    date_from = serializers.DateField(help_text="Resolved modeling window start.")
    date_to = serializers.DateField(help_text="Resolved modeling window end.")
    window_weeks = serializers.IntegerField(help_text="Number of weeks spanned by the window.")
    outcome_kind = serializers.CharField(
        allow_blank=True, help_text="Node kind of the selected conversion goal (EventsNode / ActionsNode / ...)."
    )
    outcome_ref = serializers.CharField(allow_blank=True, help_text="Name of the selected conversion goal.")
    channels = serializers.ListField(
        child=serializers.CharField(), help_text="Distinct ad channels present in the spend panel."
    )
    spend_panel = MmmSpendPanelRowSerializer(many=True, help_text="Paginated week×channel spend rows.")
    spend_panel_count = serializers.IntegerField(help_text="Total spend-panel rows before pagination.")
    outcome_series = MmmOutcomeRowSerializer(many=True, help_text="Weekly outcome series with calendar controls.")


class MmmRunSerializer(serializers.Serializer):
    job_id = serializers.UUIDField(help_text="MMM run identifier (the Dagster run ID).")
    status = serializers.CharField(help_text=f"Run status: one of {MMM_RUN_STATUSES}.")
    model_version = serializers.CharField(help_text="MMM model version that produced the run, e.g. 'mmm_v1'.")
    outcome_kind = serializers.CharField(allow_blank=True, help_text="Node kind of the modeled conversion goal.")
    outcome_ref = serializers.CharField(allow_blank=True, help_text="Name of the modeled conversion goal.")
    date_from = serializers.DateField(help_text="Modeling window start used for the run.")
    date_to = serializers.DateField(help_text="Modeling window end used for the run.")
    window_weeks = serializers.IntegerField(help_text="Number of weeks in the run's window.")
    channels = serializers.ListField(child=serializers.CharField(), help_text="Channels modeled in the run.")
    r_squared = serializers.FloatField(help_text="In-sample R² of the fitted model (diagnostics).")
    mape = serializers.FloatField(help_text="Mean absolute percentage error of the fit (diagnostics).")
    divergences = serializers.IntegerField(help_text="Number of NUTS divergences during sampling (diagnostics).")
    total_budget = serializers.FloatField(help_text="Total spend across all channels over the window.")
    computed_at = serializers.DateTimeField(help_text="When the run wrote its results (UTC).")


@extend_schema_serializer(many=False)
class MmmRunsResponseSerializer(serializers.Serializer):
    results = MmmRunSerializer(many=True, help_text="Runs ordered by recency, most recent first.")


class MmmRunQuerySerializer(serializers.Serializer):
    job_id = serializers.UUIDField(
        required=False, help_text="MMM run to read. Defaults to the project's most recent run."
    )


class MmmContributionRowSerializer(serializers.Serializer):
    week = serializers.DateField(help_text="Week the contribution is attributed to.")
    channel = serializers.CharField(help_text="Channel, or '__baseline__' for the model's always-on baseline.")
    spend = serializers.FloatField(help_text="Spend for the channel-week (0 for the baseline row).")
    contribution = serializers.FloatField(help_text="Posterior-mean outcome contributed by this channel that week.")
    contribution_lower = serializers.FloatField(help_text="Lower credible-interval bound of the contribution.")
    contribution_upper = serializers.FloatField(help_text="Upper credible-interval bound of the contribution.")


class MmmCurveRowSerializer(serializers.Serializer):
    channel = serializers.CharField(help_text="Channel the response curve belongs to.")
    spend_point = serializers.FloatField(help_text="Weekly spend level on the response curve's x-axis.")
    incremental_outcome = serializers.FloatField(help_text="Posterior-mean incremental outcome at this spend level.")
    incremental_lower = serializers.FloatField(help_text="Lower credible-interval bound of the incremental outcome.")
    incremental_upper = serializers.FloatField(help_text="Upper credible-interval bound of the incremental outcome.")


class MmmRoiRowSerializer(serializers.Serializer):
    channel = serializers.CharField(help_text="Channel the ROI estimate belongs to.")
    roi = serializers.FloatField(help_text="Posterior-mean return on investment (incremental outcome per unit spend).")
    roi_lower = serializers.FloatField(help_text="Lower credible-interval bound of ROI.")
    roi_upper = serializers.FloatField(help_text="Upper credible-interval bound of ROI.")
    marginal_roi = serializers.FloatField(help_text="Marginal ROI at current spend (slope of the response curve).")
    current_spend = serializers.FloatField(help_text="Current weekly spend for the channel.")
    recommended_spend = serializers.FloatField(
        help_text="Optimizer's recommended weekly spend (advisory — nothing is auto-applied)."
    )
    calibrated = serializers.BooleanField(help_text="Whether a lift-test calibration prior was applied to the channel.")


@extend_schema_serializer(many=False)
class MmmRunDetailResponseSerializer(serializers.Serializer):
    run = MmmRunSerializer(allow_null=True, help_text="Run metadata, or null when the project has no runs yet.")
    contributions = MmmContributionRowSerializer(
        many=True, help_text="Per-channel weekly contribution decomposition with credible intervals."
    )
    curves = MmmCurveRowSerializer(many=True, help_text="Per-channel saturation response curves with credible bands.")
    roi = MmmRoiRowSerializer(many=True, help_text="Per-channel ROI, marginal ROI, and budget recommendation.")


class MmmCalibrationSerializer(serializers.Serializer):
    channel = serializers.CharField(help_text="Ad channel the calibration applies to (must match a spend channel).")
    lift_pct = serializers.FloatField(
        help_text="Measured incremental lift as a percentage (e.g. 12.5 for a +12.5% lift)."
    )
    ci_low = serializers.FloatField(help_text="Lower bound of the lift confidence interval, same units as lift_pct.")
    ci_high = serializers.FloatField(help_text="Upper bound of the lift confidence interval, same units as lift_pct.")
    source = serializers.CharField(  # type: ignore[assignment]  # field named `source` shadows DRF Field.source
        required=False, default="manual", help_text="Origin of the calibration: 'manual' or 'experiment'."
    )
    experiment_id = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        help_text="Source experiment ID when the calibration came from a PostHog experiment, else null.",
    )

    def validate(self, data: dict[str, Any]) -> dict[str, Any]:
        if data["ci_low"] > data["ci_high"]:
            raise serializers.ValidationError("ci_low must be less than or equal to ci_high")
        if data.get("source", "manual") not in ("manual", "experiment"):
            raise serializers.ValidationError("source must be 'manual' or 'experiment'")
        return data


@extend_schema_serializer(many=False)
class MmmCalibrationsResponseSerializer(serializers.Serializer):
    calibrations = MmmCalibrationSerializer(many=True, help_text="Per-channel lift-test calibrations.")


class MmmCalibrationsRequestSerializer(serializers.Serializer):
    calibrations = MmmCalibrationSerializer(
        many=True, help_text="Full set of per-channel calibrations to persist (replaces the existing set)."
    )


class MmmErrorSerializer(serializers.Serializer):
    detail = serializers.CharField(help_text="Human-readable explanation of why the request could not be served.")


class MmmStorageUnavailable(APIException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_code = "mmm_storage_unavailable"
    default_detail = MARKETING_MMM_S3_UNCONFIGURED_MESSAGE


_STORAGE_UNAVAILABLE_RESPONSE = OpenApiResponse(
    response=MmmErrorSerializer, description="The MMM scratch bucket is not configured on this deployment."
)


# ---------------------------------------------------------------------------
# Mixin
# ---------------------------------------------------------------------------


class MmmActionsMixin:
    """MMM read-only actions, mixed into `MarketingAnalyticsViewSet`. Relies on the host viewset for
    `self.team` and the request/permission machinery."""

    def dangerously_get_required_scopes(self, request: Request, view: Any) -> list[str] | None:
        # `mmm_calibrations` is one endpoint serving GET (read the calibration set) and POST (replace it).
        # An @action's `required_scopes` can't vary by method, so derive it here: the POST write path must
        # require `marketing_analytics:write`, otherwise a token scoped only to `marketing_analytics:read`
        # could overwrite the calibration priors. The other actions set their own `required_scopes`, so they
        # short-circuit before reaching this hook; returning None lets them fall through unchanged.
        if getattr(view, "action", None) == "mmm_calibrations":
            return ["marketing_analytics:write"] if request.method == "POST" else ["marketing_analytics:read"]
        super_method = getattr(super(), "dangerously_get_required_scopes", None)
        return super_method(request, view) if super_method else None

    def _assert_mmm_access(self, request: Request) -> None:
        """Staff-only while MMM is under development (the security boundary; the feature flag gates UI)."""
        if not getattr(request.user, "is_staff", False):
            raise PermissionDenied("Marketing mix modeling is limited to staff while in development.")

    def _assert_storage_configured(self) -> None:
        if mmm_s3_unconfigured():
            raise MmmStorageUnavailable()

    @validated_request(
        query_serializer=MmmDatasetQuerySerializer,
        responses={200: OpenApiResponse(response=MmmDatasetResponseSerializer, description="MMM modeling dataset")},
        summary="Build the MMM modeling dataset",
        description="Run the marketing mix modeling dataset builder live: a weekly week×channel spend panel plus a "
        "weekly outcome series with calendar controls, for the selected conversion goal. Supports `?format=csv` for "
        "a wide weekly modeling matrix (bring-your-own-model export). Staff only.",
    )
    @action(methods=["GET"], detail=False, url_path="mmm_dataset", required_scopes=["marketing_analytics:read"])
    def mmm_dataset(self, request: Request, *args: Any, **kwargs: Any) -> Response | StreamingHttpResponse:
        self._assert_mmm_access(request)
        params = request.validated_query_data
        date_from = params.get("date_from")
        date_to = params.get("date_to")
        date_range = DateRange(date_from=date_from, date_to=date_to) if (date_from and date_to) else default_window()

        try:
            runner = MarketingMixDatasetQueryRunner(
                team=self.team,  # type: ignore[attr-defined]
                date_range=date_range,
                outcome_index=params["outcome_index"],
                user=cast(User, request.user),
            )
            dataset = runner.run()
        except Exception:
            # A stale conversion goal (e.g. an ActionsNode pointing at a deleted action) or a query
            # failure would otherwise surface as an opaque 500; match the other actions in this file.
            logger.exception("mmm_dataset_failed", team_id=self.team.pk)  # type: ignore[attr-defined]
            return Response(
                {"detail": "Failed to build the marketing mix modeling dataset. Check server logs for details."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        if request.query_params.get("format") == "csv":
            return _stream_dataset_csv(dataset)

        offset, limit = params["offset"], params["limit"]
        page = dataset.spend_panel[offset : offset + limit]
        payload = {
            "status": dataset.status,
            "message": dataset.message,
            "date_from": dataset.date_from,
            "date_to": dataset.date_to,
            "window_weeks": dataset.window_weeks,
            "outcome_kind": dataset.outcome_kind,
            "outcome_ref": dataset.outcome_ref,
            "channels": dataset.channels,
            "spend_panel": [vars(row) for row in page],
            "spend_panel_count": len(dataset.spend_panel),
            "outcome_series": [vars(row) for row in dataset.outcome_series],
        }
        return Response(MmmDatasetResponseSerializer(payload).data)

    @extend_schema(
        responses={200: MmmRunsResponseSerializer, 503: _STORAGE_UNAVAILABLE_RESPONSE},
        summary="List MMM runs",
        description="Recent marketing mix modeling runs for this project with their window, channels, and fit "
        "diagnostics, most recent first. Empty until the MMM Dagster job has run. Staff only.",
    )
    @action(methods=["GET"], detail=False, url_path="mmm_runs", required_scopes=["marketing_analytics:read"])
    def mmm_runs(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        self._assert_mmm_access(request)
        self._assert_storage_configured()
        rows = read_dataset(
            self.team.pk,  # type: ignore[attr-defined]
            ALL_RUNS,
            MMM_RUN_META,
            MMM_RUN_META_STRUCTURE,
            columns=_RUN_META_COLUMNS,
            where="ORDER BY computed_at DESC LIMIT %(limit)s",
            params={"limit": MAX_RUNS_LISTED},
        )
        results = [_run_meta_row_to_dict(row) for row in rows]
        return Response(MmmRunsResponseSerializer({"results": results}).data)

    @extend_schema(
        parameters=[MmmRunQuerySerializer],
        responses={200: MmmRunDetailResponseSerializer, 503: _STORAGE_UNAVAILABLE_RESPONSE},
        summary="Read one MMM run",
        description="Full results for a single marketing mix modeling run: contribution decomposition, response "
        "curves, and the ROI / budget-recommendation table. Defaults to the most recent run. Staff only.",
    )
    @action(methods=["GET"], detail=False, url_path="mmm_run", required_scopes=["marketing_analytics:read"])
    def mmm_run(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        self._assert_mmm_access(request)
        self._assert_storage_configured()
        filters = MmmRunQuerySerializer(data=request.query_params)
        filters.is_valid(raise_exception=True)
        team_id = self.team.pk  # type: ignore[attr-defined]

        job_id = (
            str(filters.validated_data["job_id"]) if filters.validated_data.get("job_id") else self._latest_job_id()
        )
        if job_id is None:
            return Response(
                MmmRunDetailResponseSerializer({"run": None, "contributions": [], "curves": [], "roi": []}).data
            )

        run_rows = read_dataset(team_id, job_id, MMM_RUN_META, MMM_RUN_META_STRUCTURE, columns=_RUN_META_COLUMNS)
        run = _run_meta_row_to_dict(run_rows[0]) if run_rows else None
        contributions = read_dataset(
            team_id,
            job_id,
            MMM_CONTRIBUTIONS,
            MMM_CONTRIBUTIONS_STRUCTURE,
            columns=["week", "channel", "spend", "contribution", "contribution_lower", "contribution_upper"],
            where="ORDER BY week, channel",
        )
        curves = read_dataset(
            team_id,
            job_id,
            MMM_CURVES,
            MMM_CURVES_STRUCTURE,
            columns=["channel", "spend_point", "incremental_outcome", "incremental_lower", "incremental_upper"],
            where="ORDER BY channel, spend_point",
        )
        roi = read_dataset(
            team_id,
            job_id,
            MMM_ROI,
            MMM_ROI_STRUCTURE,
            columns=[
                "channel",
                "roi",
                "roi_lower",
                "roi_upper",
                "marginal_roi",
                "current_spend",
                "recommended_spend",
                "calibrated",
            ],
            where="ORDER BY channel",
        )
        payload = {
            "run": run,
            "contributions": [
                dict(zip(["week", "channel", "spend", "contribution", "contribution_lower", "contribution_upper"], r))
                for r in contributions
            ],
            "curves": [
                dict(
                    zip(["channel", "spend_point", "incremental_outcome", "incremental_lower", "incremental_upper"], r)
                )
                for r in curves
            ],
            "roi": [
                dict(
                    zip(
                        [
                            "channel",
                            "roi",
                            "roi_lower",
                            "roi_upper",
                            "marginal_roi",
                            "current_spend",
                            "recommended_spend",
                            "calibrated",
                        ],
                        r,
                    )
                )
                for r in roi
            ],
        }
        return Response(MmmRunDetailResponseSerializer(payload).data)

    def _latest_job_id(self) -> str | None:
        rows = read_dataset(
            self.team.pk,  # type: ignore[attr-defined]
            ALL_RUNS,
            MMM_RUN_META,
            MMM_RUN_META_STRUCTURE,
            columns=["job_id"],
            where="ORDER BY computed_at DESC LIMIT 1",
        )
        return str(rows[0][0]) if rows else None

    @extend_schema(
        methods=["GET"],
        responses={200: MmmCalibrationsResponseSerializer},
        summary="Read MMM channel calibrations",
        description="The stored per-channel lift-test calibrations used to derive Bayesian priors for the MMM fit. "
        "Staff only.",
    )
    @extend_schema(
        methods=["POST"],
        request=MmmCalibrationsRequestSerializer,
        responses={200: MmmCalibrationsResponseSerializer},
        summary="Replace MMM channel calibrations",
        description="Validate and persist the full set of per-channel lift-test calibrations (replaces the existing "
        "set). The only write endpoint in the MMM POC. Staff only.",
    )
    @action(methods=["GET", "POST"], detail=False, url_path="mmm_calibrations")
    def mmm_calibrations(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        self._assert_mmm_access(request)
        config = self.team.marketing_analytics_config  # type: ignore[attr-defined]

        if request.method == "POST":
            body = MmmCalibrationsRequestSerializer(data=request.data)
            body.is_valid(raise_exception=True)
            calibrations = {
                item["channel"]: {
                    "lift_pct": item["lift_pct"],
                    "ci_low": item["ci_low"],
                    "ci_high": item["ci_high"],
                    "source": item.get("source", "manual"),
                    "experiment_id": item.get("experiment_id"),
                }
                for item in body.validated_data["calibrations"]
            }
            try:
                config.mmm_channel_calibrations = calibrations  # setter validates
                config.save()
            except DjangoValidationError as error:
                raise DRFValidationError({"calibrations": error.messages})

        return Response(
            MmmCalibrationsResponseSerializer(
                {"calibrations": _calibrations_to_list(config.mmm_channel_calibrations)}
            ).data
        )


def _run_meta_row_to_dict(row: tuple[Any, ...]) -> dict[str, Any]:
    return dict(zip(_RUN_META_COLUMNS, row))


def _calibrations_to_list(calibrations: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Flatten the stored channel→config map into the list shape the serializer expects."""
    return [{"channel": channel, **config} for channel, config in sorted(calibrations.items())]


def _stream_dataset_csv(dataset: MarketingMixDataset) -> StreamingHttpResponse:
    """Stream a wide weekly modeling matrix: one row per week, a spend column per channel, then the
    outcome and calendar controls — the matrix a bring-your-own-model workflow feeds into MMM."""
    channels = dataset.channels
    spend_by_week_channel: dict[Any, dict[str, float]] = {}
    for row in dataset.spend_panel:
        spend_by_week_channel.setdefault(row.week, {})[row.channel] = row.spend
    outcomes = {row.week: row for row in dataset.outcome_series}
    weeks = sorted(set(spend_by_week_channel) | set(outcomes))

    header = [
        "week",
        *[f"spend__{channel}" for channel in channels],
        "outcome",
        "control_weekofyear",
        "is_holiday_week",
    ]

    def rows():
        writer = csv.writer(_Echo())
        yield writer.writerow(header)
        for week in weeks:
            spends = spend_by_week_channel.get(week, {})
            outcome_row = outcomes.get(week)
            yield writer.writerow(
                [
                    week.isoformat(),
                    *[spends.get(channel, 0.0) for channel in channels],
                    outcome_row.outcome if outcome_row else "",
                    outcome_row.control_weekofyear if outcome_row else "",
                    outcome_row.is_holiday_week if outcome_row else "",
                ]
            )

    response = StreamingHttpResponse(rows(), content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="mmm_dataset.csv"'
    return response


class _Echo:
    """A file-like object whose `write` returns the value, so `csv.writer` can stream rows."""

    def write(self, value: str) -> str:
        return value
