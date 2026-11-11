import json
import hashlib
from datetime import timedelta
from typing import cast

from django.core.cache import cache
from django.db import models
from django.utils import timezone

from posthog.schema import SurveyMatchType

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import Workload
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries, tags_context
from posthog.dataclasses import frozen
from posthog.errors import ExposedCHQueryError
from posthog.models import Team, User
from posthog.session_recordings.models.session_recording import SessionRecording

from products.access_control.backend.facade.api import (
    get_restricted_properties_with_group_type_index_for_team,
    split_restricted_property_names,
)
from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.exports.backend.facade.api import (
    EXPORT_WORKFLOW_TIMEOUT,
    ExportedAsset,
    create_export_asset_async,
    is_export_failure_final,
)
from products.surveys.backend.models import Survey

SNAPSHOT_WINDOW = timedelta(days=7)
LONGEST_RECORDING = timedelta(days=1)
NO_SNAPSHOT_TTL = timedelta(minutes=10)
RENDER_CLAIM_TTL = timedelta(minutes=1)
# The first pageview often fires before the recorder sends its first snapshot.
RECORDER_START_DELAY_SECONDS = 60
# The image exporter's own size caps. The viewport comes from ingested events, so a larger one is not rendered.
MAX_EXPORT_WIDTH = 4000
MAX_EXPORT_HEIGHT = 5000
PAINT_DELAY_SECONDS = 3


class SnapshotDevice(models.TextChoices):
    DESKTOP = "desktop", "Desktop"
    MOBILE = "mobile", "Mobile"


class SnapshotStatus(models.TextChoices):
    UNAVAILABLE = "unavailable", "unavailable"
    RENDERING = "rendering", "rendering"
    READY = "ready", "ready"


@frozen
class ViewportWidths:
    min_width: int
    max_width: int


DEVICE_VIEWPORTS: dict[SnapshotDevice, ViewportWidths] = {
    SnapshotDevice.DESKTOP: ViewportWidths(min_width=1024, max_width=MAX_EXPORT_WIDTH),
    SnapshotDevice.MOBILE: ViewportWidths(min_width=1, max_width=767),
}

URL_MATCH_TEMPLATES: dict[SurveyMatchType, str] = {
    SurveyMatchType.REGEX: "match({url}, {value})",
    SurveyMatchType.NOT_REGEX: "not(match({url}, {value}))",
    SurveyMatchType.EXACT: "{url} = {value}",
    SurveyMatchType.IS_NOT: "{url} != {value}",
    SurveyMatchType.ICONTAINS: "positionCaseInsensitive({url}, {value}) > 0",
    SurveyMatchType.NOT_ICONTAINS: "positionCaseInsensitive({url}, {value}) = 0",
}


@frozen
class SnapshotMoment:
    session_id: str
    offset_seconds: int
    page_url: str
    viewport_width: int
    viewport_height: int


@frozen
class SiteSnapshot:
    status: SnapshotStatus
    exported_asset_id: int | None = None
    page_url: str | None = None
    viewport_width: int | None = None


UNAVAILABLE = SiteSnapshot(status=SnapshotStatus.UNAVAILABLE)


def _url_condition(survey: Survey, url_field: ast.Expr) -> ast.Expr:
    conditions = survey.conditions or {}
    url = conditions.get("url")
    if not url:
        return ast.Constant(value=True)
    match_type = SurveyMatchType(conditions.get("urlMatchType") or SurveyMatchType.ICONTAINS)
    return parse_expr(
        URL_MATCH_TEMPLATES[match_type],
        placeholders={"url": url_field, "value": ast.Constant(value=url)},
    )


def find_snapshot_moment(team: Team, survey: Survey, device: SnapshotDevice) -> SnapshotMoment | None:
    pageviews_since = timezone.now() - SNAPSHOT_WINDOW
    viewport = DEVICE_VIEWPORTS[device]

    def matches(url: str, width: str, height: str) -> ast.Expr:
        return parse_expr(
            "{width} BETWEEN {min_width} AND {max_width} AND {height} BETWEEN 1 AND {max_height} AND {url_condition}",
            placeholders={
                "width": parse_expr(width),
                "height": parse_expr(height),
                "min_width": ast.Constant(value=viewport.min_width),
                "max_width": ast.Constant(value=viewport.max_width),
                "max_height": ast.Constant(value=MAX_EXPORT_HEIGHT),
                "url_condition": _url_condition(survey, parse_expr(url)),
            },
        )

    # Every pageview of the sessions that have a matching one, so each match knows when its visitor moved on.
    matching_pageviews = parse_select(
        """
        SELECT session_id, timestamp, page_url, viewport_width, viewport_height
        FROM (
            SELECT
                e.$session_id AS session_id,
                e.timestamp AS timestamp,
                e.properties.$current_url AS page_url,
                toInt(e.properties.$viewport_width) AS viewport_width,
                toInt(e.properties.$viewport_height) AS viewport_height,
                leadInFrame(e.timestamp) OVER (
                    PARTITION BY e.$session_id, e.properties.$window_id ORDER BY e.timestamp ASC ROWS BETWEEN CURRENT ROW AND 1 FOLLOWING
                ) AS next_pageview_at
            FROM events AS e
            WHERE e.event = '$pageview'
                AND e.timestamp >= {pageviews_since}
                AND e.$session_id IN (
                    SELECT e.$session_id
                    FROM events AS e
                    WHERE e.event = '$pageview'
                        AND e.timestamp >= {pageviews_since}
                        AND e.$session_id != ''
                        AND {event_matches}
                )
        )
        WHERE {row_matches}
            AND (next_pageview_at <= timestamp OR next_pageview_at >= timestamp + toIntervalSecond({paint_delay}))
        """,
        placeholders={
            "pageviews_since": ast.Constant(value=pageviews_since),
            "paint_delay": ast.Constant(value=PAINT_DELAY_SECONDS),
            "event_matches": matches(
                "e.properties.$current_url",
                "toInt(e.properties.$viewport_width)",
                "toInt(e.properties.$viewport_height)",
            ),
            "row_matches": matches("page_url", "viewport_width", "viewport_height"),
        },
    )
    query = cast(
        ast.SelectQuery,
        parse_select(
            """
            SELECT
                r.session_id,
                least(
                    greatest(dateDiff('second', r.started_at, p.timestamp), 0) + {paint_delay},
                    dateDiff('second', r.started_at, r.ended_at)
                ) AS offset_seconds,
                p.page_url,
                p.viewport_width,
                p.viewport_height
            FROM {matching_pageviews} AS p
            INNER JOIN (
                SELECT
                    session_id,
                    min(min_first_timestamp) AS started_at,
                    max(max_last_timestamp) AS ended_at
                FROM raw_session_replay_events
                WHERE min_first_timestamp >= {recordings_since}
                    AND session_id IN (SELECT session_id FROM {matching_pageviews})
                GROUP BY session_id
                HAVING max(is_deleted) = 0
            ) AS r ON r.session_id = p.session_id
            WHERE p.timestamp >= r.started_at - toIntervalSecond({recorder_start_delay}) AND p.timestamp <= r.ended_at
            ORDER BY p.timestamp DESC
            LIMIT 1
            """,
            placeholders={
                "paint_delay": ast.Constant(value=PAINT_DELAY_SECONDS),
                "recorder_start_delay": ast.Constant(value=RECORDER_START_DELAY_SECONDS),
                "recordings_since": ast.Constant(value=pageviews_since - LONGEST_RECORDING),
                "matching_pageviews": matching_pageviews,
            },
        ),
    )
    with tags_context(product=Product.SURVEYS, feature=Feature.QUERY):
        tag_queries(name="survey_site_snapshot_moment")
        try:
            response = execute_hogql_query(
                query=query,
                team=team,
                query_type="survey_site_snapshot_moment",
                workload=Workload.ONLINE,
            )
        except ExposedCHQueryError:
            # A URL regex that ClickHouse cannot compile matches no page, since posthog-js may still accept it.
            return None
    if not response.results:
        return None
    session_id, offset_seconds, page_url, viewport_width, viewport_height = response.results[0]
    return SnapshotMoment(
        session_id=session_id,
        offset_seconds=int(offset_seconds),
        page_url=page_url,
        viewport_width=viewport_width,
        viewport_height=viewport_height,
    )


def _recording_was_deleted(team: Team, session_id: str) -> bool:
    query = parse_select(
        """
        SELECT max(is_deleted)
        FROM raw_session_replay_events
        WHERE session_id = {session_id} AND min_first_timestamp >= {recordings_since}
        """,
        placeholders={
            "session_id": ast.Constant(value=session_id),
            "recordings_since": ast.Constant(value=timezone.now() - SNAPSHOT_WINDOW - LONGEST_RECORDING),
        },
    )
    with tags_context(product=Product.SURVEYS, feature=Feature.QUERY):
        tag_queries(name="survey_site_snapshot_recording_deleted")
        response = execute_hogql_query(
            query=query,
            team=team,
            query_type="survey_site_snapshot_recording_deleted",
            workload=Workload.ONLINE,
        )
    return bool(response.results and response.results[0][0])


def _snapshot_key(survey: Survey, device: SnapshotDevice) -> str:
    # The key is stored on the export, which recording viewers can read, so it hides the survey and its targeting.
    conditions = survey.conditions or {}
    targeting = {
        "survey_id": str(survey.id),
        "device": device.value,
        "url": conditions.get("url") or "",
        "url_match_type": conditions.get("urlMatchType") or "",
    }
    return hashlib.sha256(json.dumps(targeting, sort_keys=True).encode()).hexdigest()


def _may_view_recording(user_access_control: UserAccessControl, team: Team, session_id: str) -> bool:
    recording = SessionRecording.objects.filter(team_id=team.id, session_id=session_id).first()
    if recording is not None:
        return user_access_control.check_access_level_for_object(recording, required_level="viewer")
    return user_access_control.check_access_level_for_resource("session_recording", required_level="viewer")


def _snapshot_cache_key(kind: str, team: Team, key: str) -> str:
    return f"survey_site_snapshot_{kind}:{team.id}:{key}"


def _may_see_page_urls(user: User, team: Team) -> bool:
    restrictions = get_restricted_properties_with_group_type_index_for_team(user=user, team_id=team.id)
    return "$current_url" not in split_restricted_property_names(restrictions).event


def _is_abandoned(asset: ExportedAsset) -> bool:
    return not asset.has_content and asset.created_at < timezone.now() - EXPORT_WORKFLOW_TIMEOUT


def _page_url_cache_key(asset: ExportedAsset) -> str:
    # The exports API returns export_context to anyone who can view the recording, so the page URL, an event
    # property that can be restricted, is kept out of it.
    return f"survey_site_snapshot_page_url:{asset.team_id}:{asset.id}"


def _snapshot_of(asset: ExportedAsset) -> SiteSnapshot:
    if asset.exception and is_export_failure_final(
        exception_type=asset.exception_type, failure_type=asset.failure_type
    ):
        return UNAVAILABLE
    return SiteSnapshot(
        status=SnapshotStatus.READY if asset.has_content else SnapshotStatus.RENDERING,
        exported_asset_id=asset.id,
        page_url=cache.get(_page_url_cache_key(asset)),
        viewport_width=(asset.export_context or {})["width"],
    )


def get_site_snapshot(team: Team, survey: Survey, device: SnapshotDevice, user: User) -> SiteSnapshot:
    user_access_control = UserAccessControl(user, team)
    if not team.session_recording_opt_in or not _may_see_page_urls(user, team):
        return UNAVAILABLE

    key = _snapshot_key(survey, device)
    cached = (
        ExportedAsset.objects.filter(
            team_id=team.id,
            export_format=ExportedAsset.ExportFormat.PNG,
            export_context__survey_site_snapshot=key,
            is_system=True,
            created_at__gte=timezone.now() - SNAPSHOT_WINDOW,
        )
        .order_by("-created_at")
        .first()
    )
    if cached is not None:
        session_id = (cached.export_context or {})["session_recording_id"]
        if not _may_view_recording(user_access_control, team, session_id):
            return UNAVAILABLE
        if not _is_abandoned(cached) and not _recording_was_deleted(team, session_id):
            return _snapshot_of(cached)

    no_snapshot_key = _snapshot_cache_key("none", team, key)
    if cache.get(no_snapshot_key):
        return UNAVAILABLE
    render_claim_key = _snapshot_cache_key("claim", team, key)
    if not cache.add(render_claim_key, True, timeout=RENDER_CLAIM_TTL.total_seconds()):
        return SiteSnapshot(status=SnapshotStatus.RENDERING)
    try:
        return _start_snapshot(team, survey, device, user, user_access_control, key, no_snapshot_key)
    finally:
        cache.delete(render_claim_key)


def _start_snapshot(
    team: Team,
    survey: Survey,
    device: SnapshotDevice,
    user: User,
    user_access_control: UserAccessControl,
    key: str,
    no_snapshot_key: str,
) -> SiteSnapshot:
    moment = find_snapshot_moment(team, survey, device)
    if moment is None:
        cache.set(no_snapshot_key, True, timeout=NO_SNAPSHOT_TTL.total_seconds())
        return UNAVAILABLE
    if not _may_view_recording(user_access_control, team, moment.session_id):
        return UNAVAILABLE
    asset = create_export_asset_async(
        team=team,
        created_by=user,
        export_format=ExportedAsset.ExportFormat.PNG,
        export_context={
            "session_recording_id": moment.session_id,
            "timestamp": moment.offset_seconds,
            "width": moment.viewport_width,
            "height": moment.viewport_height,
            "survey_site_snapshot": key,
        },
        expires_after=timezone.now() + SNAPSHOT_WINDOW,
        is_system=True,
    )
    cache.set(_page_url_cache_key(asset), moment.page_url, timeout=SNAPSHOT_WINDOW.total_seconds())
    return _snapshot_of(asset)
