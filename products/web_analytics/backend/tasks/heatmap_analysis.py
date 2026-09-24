import time
from contextlib import suppress
from datetime import timedelta
from io import BytesIO
from urllib.parse import urlencode

from django.conf import settings
from django.utils import timezone

import structlog
from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded
from PIL import Image
from playwright.sync_api import (
    Error as PlaywrightError,
    Page,
    sync_playwright,
)
from prometheus_client import Counter, Histogram

from posthog.schema import RecordingsQuery

from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.models.scoping import with_team_scope
from posthog.query_creator_access import creator_access_revoked
from posthog.session_recordings.models.session_recording import SessionRecording
from posthog.session_recordings.queries.session_recording_list_from_query import SessionRecordingListFromQuery
from posthog.tasks.utils import CeleryQueue
from posthog.utils import absolute_uri

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.exports.backend.models.exported_asset import ExportedAsset, get_render_access_token, save_content
from products.exports.backend.tasks.image_exporter import build_cdp_endpoint
from products.web_analytics.backend.heatmap_analysis import (
    MAX_RECORDINGS,
    MAX_STATES,
    MAX_VARIANTS,
    PageState,
    RecordingAnalysis,
    group_page_states,
)
from products.web_analytics.backend.models.heatmap_analysis import HeatmapAnalysis, HeatmapAnalysisRecording

logger = structlog.get_logger(__name__)
ANALYSIS_SECONDS = Histogram(
    "heatmap_analysis_seconds", "Historical heatmap analysis duration", buckets=(10, 30, 60, 120, 300, 600)
)
ANALYSIS_RECORDINGS = Counter("heatmap_analysis_recordings_total", "Historical heatmap recording outcomes", ["outcome"])
SAMPLE_BUCKETS = 20
ANALYSIS_BUDGET_SECONDS = 480
MAX_RECORDING_BYTES = 16_000_000
MAX_RECORDING_EVENTS = 100_000
MAX_IMAGE_BYTES = 10_000_000
MAX_IMAGE_PIXELS = 32_000_000


def assert_analysis_access(analysis: HeatmapAnalysis) -> UserAccessControl:
    user = analysis.created_by
    if (
        not analysis.team.session_recording_opt_in
        or analysis.heatmap.deleted
        or creator_access_revoked(user, analysis.team)
        or user is None
    ):
        raise PermissionError("Project access is no longer available.")
    access = UserAccessControl(user, team=analysis.team)
    if not access.check_access_level_for_resource("heatmap", "viewer") or not access.check_access_level_for_resource(
        "session_recording", "viewer"
    ):
        raise PermissionError("Heatmap and Session replay access are required.")
    if not access.check_access_level_for_object(analysis.heatmap, "viewer"):
        raise PermissionError("Heatmap access is no longer available.")
    return access


def create_asset(
    analysis: HeatmapAnalysis, recording: SessionRecording, export_format: ExportedAsset.ExportFormat
) -> ExportedAsset:
    return ExportedAsset.objects.create(
        team=analysis.team,
        created_by=analysis.created_by,
        is_system=True,
        export_format=export_format,
        expires_after=recording.expiry_time,
        export_context={"session_recording_id": recording.session_id, "historical_heatmap": True},
        source_authentication=ExportedAsset.SourceAuthentication.SESSION,
    )


def capture_state(page: Page, state: PageState) -> bytes | None:
    if state.width * state.height > MAX_IMAGE_PIXELS:
        return None
    rendered = page.evaluate(
        "state => window.historicalHeatmap.render(state.window_id, state.timestamp, state.signature, state.height)",
        state.model_dump(exclude={"clicks", "image"}),
    )
    if not rendered:
        return None
    iframe = page.locator("#historical-heatmap-renderer iframe")
    bounds = iframe.bounding_box()
    if not bounds or round(bounds["width"]) != state.width:
        return None
    viewport_height = round(bounds["height"])
    if viewport_height <= 0:
        return None
    canvas = Image.new("RGB", (state.width, state.height), "white")
    for offset in range(0, state.height, viewport_height):
        actual_offset = round(page.evaluate("y => window.historicalHeatmap.scroll(y)", offset))
        tile = Image.open(BytesIO(iframe.screenshot(type="png", timeout=10_000)))
        canvas.paste(tile, (0, actual_offset))
    output = BytesIO()
    canvas.save(output, format="PNG")
    return output.getvalue()


def render_recording(analysis: HeatmapAnalysis, recording: SessionRecording, asset: ExportedAsset) -> RecordingAnalysis:
    endpoint = build_cdp_endpoint(
        settings.BROWSERLESS_CDP_URL, settings.BROWSERLESS_TOKEN, settings.BROWSERLESS_SESSION_TIMEOUT_MS
    )
    token = get_render_access_token(asset)
    url = absolute_uri("/exporter?" + urlencode({"token": token, "historical_heatmap": "1"}))
    images: list[tuple[PageState, bytes]] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp(endpoint, timeout=30_000)
        context = browser.new_context(viewport={"width": analysis.viewport_width, "height": 900})
        try:
            page = context.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=40_000)
            page.wait_for_function("() => !!window.historicalHeatmap", timeout=30_000)
            page.evaluate("() => window.historicalHeatmap.load()")
            page.wait_for_function("() => window.historicalHeatmap.ready()", timeout=40_000)
            result = RecordingAnalysis.model_validate(
                page.evaluate(
                    "input => window.historicalHeatmap.analyze(input)",
                    {
                        "url": analysis.url,
                        "date_from": analysis.date_from.timestamp() * 1000,
                        "date_to": analysis.date_to.timestamp() * 1000,
                        "viewport_width": analysis.viewport_width,
                    },
                )
            )
            image_bytes = 0
            for state in result.states:
                if image_bytes >= MAX_IMAGE_BYTES:
                    result.partial = True
                    break
                image = capture_state(page, state)
                if image is None:
                    result.partial = True
                    continue
                if image_bytes + len(image) > MAX_IMAGE_BYTES:
                    result.partial = True
                    break
                images.append((state, image))
                image_bytes += len(image)
        finally:
            with suppress(PlaywrightError):
                browser.close()
    for state, image in images:
        background = create_asset(analysis, recording, ExportedAsset.ExportFormat.PNG)
        save_content(background, image)
        state.image = str(background.id)
    return result


class HeatmapAnalysisRun:
    def __init__(self, analysis: HeatmapAnalysis) -> None:
        self.analysis = analysis
        self.started = time.monotonic()
        self.partial = False
        self.results: dict[str, RecordingAnalysis] = {}
        self.state_count = 0
        self.seen: set[str] = set()
        self.allowed_ids: set[str] = set()

    def over_budget(self) -> bool:
        return time.monotonic() - self.started > ANALYSIS_BUDGET_SECONDS or self.state_count >= MAX_STATES

    def bucket_query(self, bucket: int) -> RecordingsQuery:
        analysis = self.analysis
        step = (analysis.date_to - analysis.date_from) / SAMPLE_BUCKETS
        bucket_start = analysis.date_from + step * bucket
        return RecordingsQuery.model_validate(
            {
                "kind": "RecordingsQuery",
                "date_from": (bucket_start - timedelta(days=1)).isoformat(),
                "date_to": (bucket_start + step).isoformat(),
                "limit": MAX_RECORDINGS // SAMPLE_BUCKETS,
                "properties": [
                    {
                        "type": "recording",
                        "key": "visited_page",
                        "operator": "exact",
                        "value": [analysis.url.rstrip("/"), analysis.url.rstrip("/") + "/"],
                    },
                    *[
                        {"type": "cohort", "key": "id", "operator": "in", "value": cohort_id}
                        for cohort_id in analysis.filters.get("cohort_ids", [])
                    ],
                ],
                "events": analysis.filters.get("events", []),
                "filter_test_accounts": analysis.filters.get("filter_test_accounts", False),
            }
        )

    def load_recording(self, session_id: str) -> SessionRecording:
        access = assert_analysis_access(self.analysis)
        recording = SessionRecording(team=self.analysis.team, session_id=session_id)
        if not recording.load_metadata() or recording.snapshot_source != "web" or not recording.expiry_time:
            raise ValueError("Recording unavailable")
        if (recording.total_size or 0) > MAX_RECORDING_BYTES or (recording.event_count or 0) > MAX_RECORDING_EVENTS:
            raise ValueError("Recording exceeds analysis budget")
        if not access.check_access_level_for_object(recording, "viewer"):
            raise PermissionError("Recording access is unavailable")
        return recording

    def assign_variants(self, session_id: str, result: RecordingAnalysis) -> list[PageState]:
        allowed_ids = set(self.allowed_ids)
        for variant in group_page_states({**self.results, session_id: result}):
            if len(allowed_ids) < MAX_VARIANTS:
                allowed_ids.add(variant.id)
            for member in variant.members:
                if member.session_id != session_id:
                    continue
                member.state.variant_id = variant.id
                if variant.id not in allowed_ids:
                    self.partial = True
                    member.state.image = ""
        kept = [state for state in result.states if state.image][: MAX_STATES - self.state_count]
        kept_ids = {id(state) for state in kept}
        result.excluded_clicks += sum(len(state.clicks) for state in result.states if id(state) not in kept_ids)
        self.partial |= len(kept) < len(result.states)
        return kept

    def analyze_recording(self, session_id: str) -> None:
        analysis = self.analysis
        asset = None
        try:
            recording = self.load_recording(session_id)
            asset = create_asset(analysis, recording, ExportedAsset.ExportFormat.JSON)
            result = render_recording(analysis, recording, asset)
            asset.refresh_from_db(fields=["expires_after"])
            if asset.expires_after is None or asset.expires_after <= timezone.now():
                ExportedAsset.objects.filter(
                    team_id=analysis.team_id,
                    export_context__session_recording_id=session_id,
                    export_context__historical_heatmap=True,
                ).update(expires_after=timezone.now())
                raise ValueError("Recording expired during analysis")
            self.partial |= result.partial
            result.states = self.assign_variants(session_id, result)
            save_content(asset, result.model_dump_json().encode())
            HeatmapAnalysisRecording.objects.for_team(analysis.team_id).create(
                team_id=analysis.team_id,
                analysis=analysis,
                session_id=session_id,
                asset=asset,
            )
            self.results[session_id] = result
            self.state_count += len(result.states)
            self.allowed_ids |= {state.variant_id for state in result.states}
            ANALYSIS_RECORDINGS.labels(outcome="analyzed").inc()
        except (PermissionError, SoftTimeLimitExceeded):
            raise
        except Exception:
            logger.exception(
                "heatmap_recording_analysis_failed", team_id=analysis.team_id, analysis_id=str(analysis.id)
            )
            analysis.excluded_recordings += 1
            ANALYSIS_RECORDINGS.labels(outcome="excluded").inc()
            if asset is not None:
                asset.expires_after = timezone.now()
                asset.save(update_fields=["expires_after"])

    def sample(self) -> None:
        analysis = self.analysis
        for bucket in range(SAMPLE_BUCKETS):
            if self.over_budget():
                self.partial = True
                return
            candidates = SessionRecordingListFromQuery(
                team=analysis.team, query=self.bucket_query(bucket), user=analysis.created_by
            ).run()
            self.partial |= candidates.has_more_recording
            for candidate in candidates.results:
                if self.over_budget():
                    self.partial = True
                    break
                session_id = candidate["session_id"]
                if session_id in self.seen:
                    continue
                self.seen.add(session_id)
                analysis.sampled_recordings += 1
                self.analyze_recording(session_id)
                analysis.save(update_fields=["sampled_recordings", "excluded_recordings", "updated_at"])

    def run(self) -> None:
        analysis = self.analysis
        try:
            assert_analysis_access(analysis)
            if not settings.BROWSERLESS_CDP_URL:
                raise RuntimeError("The recording renderer is not configured.")
            self.sample()
            analysis.status = (
                HeatmapAnalysis.Status.PARTIAL
                if self.partial or analysis.excluded_recordings
                else HeatmapAnalysis.Status.COMPLETED
            )
        except SoftTimeLimitExceeded:
            analysis.status = HeatmapAnalysis.Status.PARTIAL
        except Exception:
            analysis.status = HeatmapAnalysis.Status.FAILED
            analysis.error = "Couldn't analyze these recordings. Try again or choose a shorter date range."
            logger.exception("heatmap_analysis_failed", team_id=analysis.team_id, analysis_id=str(analysis.id))
        finally:
            variants = group_page_states(self.results)
            analysis.representatives = {variant.id: variant.member_id(variant.representative()) for variant in variants}
            ANALYSIS_SECONDS.observe(time.monotonic() - self.started)
            analysis.save(
                update_fields=[
                    "status",
                    "error",
                    "sampled_recordings",
                    "excluded_recordings",
                    "representatives",
                    "updated_at",
                ]
            )


@shared_task(ignore_result=True, soft_time_limit=600, time_limit=630, queue=CeleryQueue.EXPORTS.value)
@with_team_scope()
def analyze_heatmap(team_id: int, analysis_id: str) -> None:
    tag_queries(product=Product.HEATMAPS, feature=Feature.QUERY, team_id=team_id)
    analysis = (
        HeatmapAnalysis.objects.for_team(team_id).select_related("team__organization", "created_by").get(id=analysis_id)
    )
    if (
        not HeatmapAnalysis.objects.for_team(team_id)
        .filter(id=analysis_id, status=HeatmapAnalysis.Status.QUEUED)
        .update(status=HeatmapAnalysis.Status.PROCESSING)
    ):
        return
    HeatmapAnalysisRun(analysis).run()
