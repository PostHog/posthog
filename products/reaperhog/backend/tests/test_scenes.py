from datetime import UTC, datetime
from pathlib import Path

import pytest

from products.reaperhog.backend.facade.enums import SCOPE_ALL
from products.reaperhog.backend.logic.repo import RepoIndex
from products.reaperhog.backend.logic.scouts.base import ScoutContext, ScoutIncomplete
from products.reaperhog.backend.logic.scouts.scenes import (
    PRODUCT_ROUTES_PATH,
    PRODUCT_SCENES_PATH,
    PageviewScan,
    SceneRoutes,
    ScenesScout,
    classify_scene,
    normalize_pathname,
    parse_product_routes,
    views_per_scene,
)

ROUTES = """
export const productRoutes: Record<string, [string, string]> = {
    '/data-management/actions': ['Actions', 'actions'],
    '/data-management/actions/:id': ['Action', 'action'],
    '/data-management/actions/:id/:tab': [
        'Action',
        'actionTab',
    ],
    '/data-management/actions/new/': ['NewAction', 'actionNew'],
    '/surveys/*': ['Surveys', 'surveys'],
    [CLUSTER_URL_PATTERN]: ['Clusters', 'clusters'],
    '/clusters/all': ['Clusters', 'clustersAll'],
}
"""
SCENES = """
export const productScenes: Record<string, () => Promise<any>> = {
    Actions: () => import('../../products/actions/frontend/pages/Actions'),
    Action: () =>
        import('../../products/actions/frontend/pages/Action'),
    Surveys: () => import('../../products/surveys/frontend/Surveys'),
    Clusters: () => import('../../products/clusters/frontend/Clusters'),
}
"""


def test_parse_product_routes_groups_routes_by_scene_and_resolves_files() -> None:
    scenes = {scene.scene: scene for scene in parse_product_routes(ROUTES, SCENES)}

    assert scenes["Actions"] == SceneRoutes(
        scene="Actions", routes=("/data-management/actions",), file="products/actions/frontend/pages/Actions"
    )
    assert scenes["NewAction"].file is None
    assert scenes["Surveys"].routes == ("/surveys/*",)
    assert scenes["Action"] == SceneRoutes(
        scene="Action",
        routes=("/data-management/actions/:id", "/data-management/actions/:id/:tab"),
        file="products/actions/frontend/pages/Action",
    )
    assert "Clusters" not in scenes


@pytest.mark.parametrize(
    "pathname,expected",
    [
        ("/project/123/data-management/actions/", "/data-management/actions"),
        ("/organization/abc/settings", "/settings"),
        ("/data-management/actions/42", "/data-management/actions/42"),
        ("/project/1", "/"),
    ],
)
def test_normalize_pathname(pathname: str, expected: str) -> None:
    assert normalize_pathname(pathname) == expected


def test_views_match_param_and_wildcard_routes() -> None:
    scenes = parse_product_routes(ROUTES, SCENES)
    pageviews = {
        "/project/1/data-management/actions/42": 3,
        "/project/1/data-management/actions/42/": 1,
        "/project/1/data-management/actions/42/history": 2,
        "/project/2/surveys/abc/results": 5,
        "/project/2/data-management/actions/new/": 0,
    }

    views = views_per_scene(scenes, pageviews)

    assert views["Action"] == {"/data-management/actions/:id": 4, "/data-management/actions/:id/:tab": 2}
    assert views["Actions"] == {"/data-management/actions": 0}
    assert views["Surveys"] == {"/surveys/*": 5}
    assert views["NewAction"] == {"/data-management/actions/new/": 0}


@pytest.mark.parametrize(
    "views,file,expect_hit",
    [
        ({"/a": 0, "/a/:id": 0}, "products/a/frontend/A", True),
        ({"/a": 0, "/a/:id": 2}, "products/a/frontend/A", False),
        ({"/a": 0}, None, False),
    ],
)
def test_classify_scene_only_flags_scenes_with_no_traffic_on_any_route(views, file, expect_hit) -> None:
    scene = SceneRoutes(scene="A", routes=tuple(views), file=file)

    hit = classify_scene(scene, views)

    assert (hit is not None) is expect_hit
    if hit is not None:
        assert hit.files == [file]
        assert hit.evidence["routes"] == ", ".join(views)


def _scenes_context(tmp_path: Path) -> ScoutContext:
    (tmp_path / PRODUCT_ROUTES_PATH).parent.mkdir(parents=True)
    (tmp_path / PRODUCT_ROUTES_PATH).write_text(ROUTES)
    (tmp_path / PRODUCT_SCENES_PATH).write_text(SCENES)
    return ScoutContext(team_id=1, repo=RepoIndex(tmp_path), scope=SCOPE_ALL, now=datetime(2026, 8, 30, tzinfo=UTC))


def test_scenes_scout_reports_every_untravelled_scene(tmp_path: Path) -> None:
    scout = ScenesScout(pageviews=lambda team_id: PageviewScan(counts={}, truncated=False))

    assert len(scout.run(_scenes_context(tmp_path))) == 3


def test_scenes_scout_reports_a_truncated_pageview_scan_as_incomplete(tmp_path: Path) -> None:
    scout = ScenesScout(pageviews=lambda team_id: PageviewScan(counts={}, truncated=True))

    with pytest.raises(ScoutIncomplete):
        scout.run(_scenes_context(tmp_path))
