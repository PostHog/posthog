import re
import logging
from collections.abc import Callable, Mapping

from posthog.hogql.constants import MAX_SELECT_RETURNED_ROWS
from posthog.hogql.query import execute_hogql_query

from posthog.dataclasses import frozen
from posthog.models.team.team import Team

from products.reaperhog.backend.facade.enums import NAMED_SCOPES, SCOPE_ALL, RootKind, ScoutName
from products.reaperhog.backend.logic.artefacts import Hit
from products.reaperhog.backend.logic.constants import SCENE_LOOKBACK_DAYS
from products.reaperhog.backend.logic.scouts.base import ScoutContext

logger = logging.getLogger(__name__)

PRODUCT_ROUTES_PATH = "frontend/src/products.tsx"
PRODUCT_SCENES_PATH = "frontend/src/productScenes.tsx"

# build-products.mjs generates the two files and the formatter wraps the long entries, so a route
# array or a dynamic import can span lines. Match across the whole text rather than line by line: a
# route this parser cannot see reads as a route with no traffic.
_ROUTE = re.compile(r"^[ \t]+'(/[^']*)':\s*\[\s*'([A-Za-z0-9_]+)'", re.MULTILINE)
_COMPUTED_ROUTE = re.compile(r"^[ \t]+\[[^\]]+\]:\s*\[\s*'([A-Za-z0-9_]+)'", re.MULTILINE)
_SCENE = re.compile(r"^[ \t]+([A-Za-z0-9_]+):\s*\(\)\s*=>\s*import\('\.\./\.\./([^']+)'\)", re.MULTILINE)
_PROJECT_PREFIX = re.compile(r"^/(?:project|organization)/[^/]+")
_PARAM = re.compile(r":[A-Za-z0-9_]+")

PageviewCounts = Mapping[str, int]

# The HogQL printer rewrites a top-level limit to min(limit, MAX_SELECT_RETURNED_ROWS), so asking for
# more rows cannot return more. Pathnames carry entity ids, so a busy project has more distinct values
# than this, and a pathname the query drops reads as zero traffic and marks a live scene dead.
PATHNAME_LIMIT = MAX_SELECT_RETURNED_ROWS


@frozen
class PageviewScan:
    counts: PageviewCounts
    truncated: bool


PageviewLoader = Callable[[int], PageviewScan]


@frozen
class SceneRoutes:
    scene: str
    routes: tuple[str, ...]
    file: str | None


def parse_product_routes(routes_text: str, scenes_text: str) -> list[SceneRoutes]:
    routes_by_scene: dict[str, list[str]] = {}
    for route, scene in _ROUTE.findall(routes_text):
        routes_by_scene.setdefault(scene, []).append(route)
    # A computed key holds its path in a constant that this file does not carry. Drop the whole scene,
    # because the pageviews on the route behind that constant cannot be counted.
    for scene in _COMPUTED_ROUTE.findall(routes_text):
        routes_by_scene.pop(scene, None)
    file_by_scene = dict(_SCENE.findall(scenes_text))
    return [
        SceneRoutes(scene=scene, routes=tuple(routes), file=file_by_scene.get(scene))
        for scene, routes in sorted(routes_by_scene.items())
    ]


def route_pattern(route: str) -> re.Pattern[str]:
    escaped = re.escape(route.rstrip("/") or "/")
    escaped = _PARAM.sub(r"[^/]+", escaped.replace(r"\:", ":")).replace(r"\*", ".*")
    return re.compile(f"^{escaped}/?$")


def normalize_pathname(pathname: str) -> str:
    stripped = _PROJECT_PREFIX.sub("", pathname or "")
    return stripped.rstrip("/") or "/"


def views_per_scene(scenes: list[SceneRoutes], pageviews: PageviewCounts) -> dict[str, dict[str, int]]:
    normalized: dict[str, int] = {}
    for pathname, count in pageviews.items():
        key = normalize_pathname(pathname)
        normalized[key] = normalized.get(key, 0) + count
    result: dict[str, dict[str, int]] = {}
    for scene in scenes:
        per_route: dict[str, int] = {}
        for route in scene.routes:
            pattern = route_pattern(route)
            per_route[route] = sum(count for path, count in normalized.items() if pattern.match(path))
        result[scene.scene] = per_route
    return result


def classify_scene(scene: SceneRoutes, views: dict[str, int]) -> Hit | None:
    if any(views.values()) or scene.file is None:
        return None
    return Hit(
        scout=ScoutName.SCENES,
        root_kind=RootKind.SCENE,
        root=scene.scene,
        files=[scene.file],
        summary=f"No pageviews on {len(scene.routes)} route(s) in {SCENE_LOOKBACK_DAYS} days",
        evidence={
            "routes": ", ".join(scene.routes),
            "lookback_days": SCENE_LOOKBACK_DAYS,
            "pageviews": 0,
        },
    )


def load_pageviews(team_id: int) -> PageviewScan:
    team = Team.objects.get(id=team_id)
    response = execute_hogql_query(
        query=(
            "SELECT properties.$pathname AS pathname, count() AS views FROM events "
            f"WHERE event = '$pageview' AND timestamp > now() - INTERVAL {SCENE_LOOKBACK_DAYS} DAY "
            f"GROUP BY pathname LIMIT {PATHNAME_LIMIT}"
        ),
        team=team,
        query_type="reaperhog_pageviews",
    )
    rows = response.results or []
    return PageviewScan(
        counts={str(row[0]): int(row[1]) for row in rows if row[0]},
        truncated=len(rows) >= PATHNAME_LIMIT,
    )


class ScenesScout:
    name = ScoutName.SCENES

    def __init__(self, pageviews: PageviewLoader = load_pageviews) -> None:
        self._pageviews = pageviews

    def applies_to(self, scope: str) -> bool:
        return scope == SCOPE_ALL or scope not in NAMED_SCOPES

    def run(self, context: ScoutContext) -> list[Hit]:
        pageviews = self._pageviews(context.team_id)
        if pageviews.truncated:
            logger.warning(
                "Pageview scan for team %s returned a full page of pathnames, so a pathname that is absent "
                "cannot be read as zero traffic; the scenes scout reports nothing for this run",
                context.team_id,
            )
            return []
        routes_text = (context.repo.root / PRODUCT_ROUTES_PATH).read_text()
        scenes_text = (context.repo.root / PRODUCT_SCENES_PATH).read_text()
        scenes = parse_product_routes(routes_text, scenes_text)
        views = views_per_scene(scenes, pageviews.counts)
        hits: list[Hit] = []
        for scene in scenes:
            hit = classify_scene(scene, views[scene.scene])
            if hit is not None and context.in_scope(hit.files):
                hits.append(hit)
        return hits
