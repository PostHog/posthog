"""A real frame of the customer's site, for the draft survey preview.

The frame comes from a recent session replay of a page the survey's URL condition matches. It is rendered once as a
PNG export and reused for every later preview of the same survey, device and URL condition.
"""

from datetime import timedelta
from typing import cast

from django.db import models
from django.utils import timezone

from posthog.schema import SurveyMatchType

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import Workload
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries, tags_context
from posthog.dataclasses import frozen
from posthog.models import Team, User
from posthog.session_recordings.models.session_recording import SessionRecording

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.exports.backend.facade.api import ExportedAsset, create_export_asset_async, is_export_failure_final
from products.surveys.backend.models import Survey

SNAPSHOT_WINDOW = timedelta(days=7)
# The pageview fires before the page paints, so the frame is taken a moment later.
PAINT_DELAY_SECONDS = 3


class SnapshotDevice(models.TextChoices):
    DESKTOP = "desktop", "Desktop"
    MOBILE = "mobile", "Mobile"


class SnapshotStatus(models.TextChoices):
    UNAVAILABLE = "unavailable", "unavailable"
    RENDERING = "rendering", "rendering"
    READY = "ready", "ready"


@frozen
class DeviceProfile:
    viewport_filter: str
    export_width: int
    export_height: int


DEVICE_PROFILES: dict[SnapshotDevice, DeviceProfile] = {
    SnapshotDevice.DESKTOP: DeviceProfile(
        viewport_filter="toFloat(e.properties.$viewport_width) >= 1024", export_width=1400, export_height=875
    ),
    SnapshotDevice.MOBILE: DeviceProfile(
        viewport_filter="toFloat(e.properties.$viewport_width) <= 767", export_width=390, export_height=844
    ),
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


@frozen
class SiteSnapshot:
    status: SnapshotStatus
    exported_asset_id: int | None = None
    page_url: str | None = None


UNAVAILABLE = SiteSnapshot(status=SnapshotStatus.UNAVAILABLE)


def _url_condition(survey: Survey) -> ast.Expr:
    conditions = survey.conditions or {}
    url = conditions.get("url")
    if not url:
        return ast.Constant(value=True)
    match_type = SurveyMatchType(conditions.get("urlMatchType") or SurveyMatchType.ICONTAINS)
    return parse_expr(
        URL_MATCH_TEMPLATES[match_type],
        placeholders={"url": ast.Field(chain=["e", "properties", "$current_url"]), "value": ast.Constant(value=url)},
    )


def find_snapshot_moment(team: Team, survey: Survey, device: SnapshotDevice) -> SnapshotMoment | None:
    query = cast(
        ast.SelectQuery,
        parse_select(
            """
            SELECT
                r.session_id,
                least(
                    dateDiff('second', r.started_at, e.timestamp) + {paint_delay},
                    dateDiff('second', r.started_at, r.ended_at)
                ) AS offset_seconds,
                e.properties.$current_url AS page_url
            FROM events AS e
            INNER JOIN (
                SELECT
                    session_id,
                    min(min_first_timestamp) AS started_at,
                    max(max_last_timestamp) AS ended_at
                FROM raw_session_replay_events
                WHERE min_first_timestamp >= {recordings_since}
                GROUP BY session_id
                HAVING max(is_deleted) = 0
            ) AS r ON r.session_id = e.$session_id
            WHERE e.event = '$pageview'
                AND e.timestamp >= {pageviews_since}
                AND e.timestamp >= r.started_at
                AND e.timestamp <= r.ended_at
                AND {url_condition}
                AND {viewport_condition}
            ORDER BY e.timestamp DESC
            LIMIT 1
            """,
            placeholders={
                "paint_delay": ast.Constant(value=PAINT_DELAY_SECONDS),
                # A recording can start up to a day before the pageview it contains.
                "recordings_since": ast.Constant(value=timezone.now() - SNAPSHOT_WINDOW - timedelta(days=1)),
                "pageviews_since": ast.Constant(value=timezone.now() - SNAPSHOT_WINDOW),
                "url_condition": _url_condition(survey),
                "viewport_condition": parse_expr(DEVICE_PROFILES[device].viewport_filter),
            },
        ),
    )
    with tags_context(product=Product.SURVEYS, feature=Feature.QUERY):
        tag_queries(name="survey_site_snapshot_moment")
        response = execute_hogql_query(
            query=query,
            team=team,
            query_type="survey_site_snapshot_moment",
            workload=Workload.ONLINE,
        )
    if not response.results:
        return None
    session_id, offset_seconds, page_url = response.results[0]
    return SnapshotMoment(session_id=session_id, offset_seconds=int(offset_seconds), page_url=page_url)


def _snapshot_key(survey: Survey, device: SnapshotDevice) -> dict[str, str]:
    # The URL condition is part of the key, so editing it never shows a page the survey no longer targets.
    conditions = survey.conditions or {}
    return {
        "survey_id": str(survey.id),
        "device": device.value,
        "url": conditions.get("url") or "",
        "url_match_type": conditions.get("urlMatchType") or "",
    }


def _may_view_recording(user_access_control: UserAccessControl, team: Team, session_id: str) -> bool:
    recording = SessionRecording.objects.filter(team_id=team.id, session_id=session_id).first()
    if recording is not None:
        return user_access_control.check_access_level_for_object(recording, required_level="viewer")
    return user_access_control.check_access_level_for_resource("session_recording", required_level="viewer")


def _snapshot_of(asset: ExportedAsset) -> SiteSnapshot:
    if asset.exception and is_export_failure_final(
        exception_type=asset.exception_type, failure_type=asset.failure_type
    ):
        return UNAVAILABLE
    return SiteSnapshot(
        status=SnapshotStatus.READY if asset.has_content else SnapshotStatus.RENDERING,
        exported_asset_id=asset.id,
        page_url=(asset.export_context or {})["page_url"],
    )


def get_site_snapshot(team: Team, survey: Survey, device: SnapshotDevice, user: User) -> SiteSnapshot:
    user_access_control = UserAccessControl(user, team)
    if not team.session_recording_opt_in or not user_access_control.check_access_level_for_resource(
        "session_recording", required_level="viewer"
    ):
        return UNAVAILABLE

    key = _snapshot_key(survey, device)
    cached = (
        ExportedAsset.objects.filter(
            team_id=team.id,
            export_format=ExportedAsset.ExportFormat.PNG,
            export_context__survey_site_snapshot=key,
            created_at__gte=timezone.now() - SNAPSHOT_WINDOW,
        )
        .order_by("-created_at")
        .first()
    )
    if cached is not None:
        session_id = (cached.export_context or {})["session_recording_id"]
        return _snapshot_of(cached) if _may_view_recording(user_access_control, team, session_id) else UNAVAILABLE

    moment = find_snapshot_moment(team, survey, device)
    if moment is None or not _may_view_recording(user_access_control, team, moment.session_id):
        return UNAVAILABLE
    profile = DEVICE_PROFILES[device]
    asset = create_export_asset_async(
        team=team,
        created_by=user,
        export_format=ExportedAsset.ExportFormat.PNG,
        export_context={
            "session_recording_id": moment.session_id,
            "timestamp": moment.offset_seconds,
            "width": profile.export_width,
            "height": profile.export_height,
            "survey_site_snapshot": key,
            "page_url": moment.page_url,
        },
        expires_after=timezone.now() + SNAPSHOT_WINDOW,
        is_system=True,
    )
    return _snapshot_of(asset)
