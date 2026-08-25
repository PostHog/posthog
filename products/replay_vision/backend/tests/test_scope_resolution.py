from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import Mock, patch

from django.utils import timezone

from parameterized import parameterized

from posthog.models import EventDefinition, Team
from posthog.session_recordings.models.session_recording_playlist import SessionRecordingPlaylist

from products.actions.backend.models.action import Action
from products.replay_vision.backend.queries.scanner_volume_estimate import ScannerVolumeEstimate
from products.replay_vision.backend.queries.top_visited_paths import RankedPath
from products.replay_vision.backend.scope_resolution import resolve_scope

_MODULE = "products.replay_vision.backend.scope_resolution"
# Each source's isolation seam, keyed by the name it reports in `degraded_sources`.
_SOURCE_FETCHERS = {
    "pages": "_page_surfaces",
    "playlists": "_playlist_matches",
    "actions": "_action_surfaces",
    "events": "_event_surfaces",
}
_KIND_BY_SOURCE = {"pages": "page", "playlists": "playlist", "actions": "action", "events": "event"}


def _paths(*pairs: tuple[str, int]) -> tuple[RankedPath, ...]:
    return tuple(RankedPath(pathname=pathname, sessions=sessions) for pathname, sessions in pairs)


def _visited_page_values(query: dict[str, Any] | None) -> list[str]:
    properties = (query or {}).get("properties") or []
    assert len(properties) == 1, f"expected exactly one property, got {properties}"
    return list(properties[0]["value"])


class TestScopeResolution(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.paths = self._patch(f"{_MODULE}.fetch_top_visited_paths", return_value=())
        # Counting is ClickHouse's job with its own tests; these assert what gets counted.
        self.estimate = self._patch(
            f"{_MODULE}.estimate_scanner_session_volume",
            return_value=ScannerVolumeEstimate(matched_sessions=42, effective_window_days=7),
        )

    def _patch(self, target: str, **kwargs: Any) -> Mock:
        patcher = patch(target, **kwargs)
        mock = patcher.start()
        self.addCleanup(patcher.stop)
        return mock

    def _resolve(self, scope: str, **kwargs: Any):
        return resolve_scope(team=self.team, scope=scope, **kwargs)

    def _playlist(self, **kwargs: Any) -> SessionRecordingPlaylist:
        kwargs.setdefault("type", SessionRecordingPlaylist.PlaylistType.FILTERS)
        kwargs.setdefault("filters", {"filter_group": {"type": "AND", "values": []}})
        return SessionRecordingPlaylist.objects.create(team=self.team, **kwargs)

    def test_matched_pages_become_one_multi_value_property(self) -> None:
        self.paths.return_value = _paths(("/billing", 900), ("/settings/billing", 300), ("/billing-history", 100))

        resolution = self._resolve("billing")

        assert resolution.query is not None
        assert _visited_page_values(resolution.query) == ["/billing", "/settings/billing", "/billing-history"]
        assert resolution.query["properties"][0]["operator"] == "icontains"
        assert resolution.query["properties"][0]["key"] == "visited_page"

    @parameterized.expand(
        [
            ("exact", "billing", ["/billing", "/settings/billing"]),
            ("stopwords_ignored", "checkout flow", ["/checkout"]),
            ("shared_stem", "bill", ["/billing", "/settings/billing"]),
            ("short_token_is_not_a_stem", "id", []),
            ("no_match", "zzzqq", []),
        ]
    )
    def test_page_matching(self, _name: str, scope: str, expected: list[str]) -> None:
        self.paths.return_value = _paths(
            ("/billing", 900), ("/settings/billing", 300), ("/checkout", 500), ("/identity", 200)
        )

        resolution = self._resolve(scope)

        assert [s.key for s in resolution.surfaces if s.kind == "page"] == expected

    def test_short_paths_never_ground_a_filter(self) -> None:
        # "/es" outranks the real match on volume, and `icontains` on it matches nearly every URL.
        self.paths.return_value = _paths(("/es", 5000), ("/es/checkout", 100))

        resolution = self._resolve("es")

        assert [s.key for s in resolution.surfaces if s.kind == "page"] == ["/es", "/es/checkout"]
        assert _visited_page_values(resolution.query) == ["/es/checkout"]

    def test_ranking_breaks_score_ties_on_volume_and_caps_the_filter(self) -> None:
        self.paths.return_value = _paths(*[(f"/billing-{i}", i) for i in range(10)])

        resolution = self._resolve("billing")

        assert [s.key for s in resolution.surfaces if s.kind == "page"] == [f"/billing-{i}" for i in range(9, 1, -1)]
        assert _visited_page_values(resolution.query) == [f"/billing-{i}" for i in range(9, 4, -1)]

    @parameterized.expand([("only_stopwords", "the flow"), ("nothing_matches", "zzzqq")])
    def test_no_usable_match_returns_no_filter_and_skips_the_count(self, _name: str, scope: str) -> None:
        self.paths.return_value = _paths(("/billing", 900))

        resolution = self._resolve(scope)

        assert resolution.query is None
        assert resolution.matched_sessions is None
        assert self.estimate.call_count == 0

    def test_playlist_reuses_saved_filters_without_dates(self) -> None:
        playlist = self._playlist(
            name="Billing rage clicks",
            filters={
                "filter_group": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "AND",
                            "values": [
                                {"type": "recording", "key": "snapshot_source", "value": ["web"], "operator": "exact"}
                            ],
                        }
                    ],
                },
                "date_from": "-30d",
                "date_to": "-7d",
            },
        )

        resolution = self._resolve("billing playlist")

        assert resolution.query is not None
        assert resolution.query["kind"] == "RecordingsQuery"
        assert "date_from" not in resolution.query
        assert "date_to" not in resolution.query
        assert [s.key for s in resolution.surfaces if s.kind == "playlist"] == [playlist.short_id]

    def test_playlist_conversion_does_not_persist(self) -> None:
        # Legacy shape (no filter_group), so a conversion runs and the default would save it back.
        legacy = {
            "events": [],
            "session_recording_duration": {"type": "recording", "key": "duration", "value": 60, "operator": "gt"},
        }
        playlist = self._playlist(name="Billing", filters=legacy)

        self._resolve("billing playlist")

        playlist.refresh_from_db()
        assert playlist.filters == legacy

    def test_unconvertible_playlist_falls_through_to_the_pages(self) -> None:
        self.paths.return_value = _paths(("/billing", 900))
        # A saved shape that no longer converts: the duration filter is missing its operator.
        self._playlist(
            name="Billing",
            filters={"session_recording_duration": {"type": "recording", "key": "duration", "value": 60}},
        )

        resolution = self._resolve("billing playlist")

        assert _visited_page_values(resolution.query) == ["/billing"]

    def test_a_playlist_is_ignored_unless_the_scope_asks_for_one(self) -> None:
        # The dead-scanner case: a playlist saved with its filters cleared constrains nothing, so
        # adopting it for a scope that merely shares a word would scan the team's whole replay volume.
        self.paths.return_value = _paths(("/billing", 900))
        self._playlist(name="Billing deep dive", filters={"filter_group": {"type": "AND", "values": []}})

        resolution = self._resolve("billing")

        assert _visited_page_values(resolution.query) == ["/billing"]
        assert [s for s in resolution.surfaces if s.kind == "playlist"] == []

    @parameterized.expand([("playlist",), ("saved filter",), ("collection",)])
    def test_a_requested_playlist_supplies_the_filter_however_wide(self, marker: str) -> None:
        # Asking for a playlist by name is asking for its filters as saved. Wide is what was asked for.
        self.paths.return_value = _paths(("/billing", 900))
        self._playlist(name="Billing deep dive", filters={"filter_group": {"type": "AND", "values": []}})

        resolution = self._resolve(f"billing {marker}")

        assert resolution.query is not None
        assert not [p for p in resolution.query.get("properties") or [] if p.get("key") == "visited_page"]
        # Still offered, so a caller can swap the playlist out for the pages.
        assert [s.key for s in resolution.surfaces if s.kind == "page"] == ["/billing"]

    def test_playlist_denied_to_the_caller_is_excluded(self) -> None:
        self.paths.return_value = _paths(("/billing", 900))
        self._playlist(name="Billing secrets")
        denying = Mock(filter_queryset_by_access_level=lambda queryset, resource=None: queryset.none())

        resolution = self._resolve("billing playlist", user_access_control=denying)

        assert [s.kind for s in resolution.surfaces] == ["page"]
        assert _visited_page_values(resolution.query) == ["/billing"]

    @parameterized.expand(
        [
            ("deleted", {"deleted": True}),
            ("collection", {"type": SessionRecordingPlaylist.PlaylistType.COLLECTION}),
        ]
    )
    def test_unusable_playlists_are_excluded(self, _name: str, overrides: dict[str, Any]) -> None:
        self._playlist(name="Billing", **overrides)

        resolution = self._resolve("billing playlist")

        assert [s for s in resolution.surfaces if s.kind == "playlist"] == []

    def test_actions_resolve_from_the_parent_team(self) -> None:
        Action.objects.create(team=self.team, name="Billing upgrade clicked")
        child = Team.objects.create(organization=self.organization, parent_team=self.team, name="Child environment")

        resolution = resolve_scope(team=child, scope="billing")

        assert [s.name for s in resolution.surfaces if s.kind == "action"] == ["Billing upgrade clicked"]

    def test_action_denied_to_the_caller_is_excluded(self) -> None:
        # Actions are access-controlled, so a scope phrase must not confirm the name of one the
        # caller cannot read — the endpoint would otherwise enumerate the team's action catalog.
        Action.objects.create(team=self.team, name="Billing plan cancelled", description="secret")
        denying = Mock(
            check_access_level_for_resource=lambda *a, **k: True,
            has_any_specific_access_for_resource=lambda *a, **k: True,
            filter_queryset_by_access_level=lambda queryset, resource=None: queryset.none(),
        )

        resolution = resolve_scope(team=self.team, scope="billing", user_access_control=denying)

        assert [s for s in resolution.surfaces if s.kind == "action"] == []

    def test_no_action_resource_access_drops_the_whole_source(self) -> None:
        # filter_queryset_by_access_level passes the queryset through when there is neither resource
        # access nor an object grant; in a viewset has_permission refuses, but here nothing would.
        Action.objects.create(team=self.team, name="Billing plan cancelled")
        denying = Mock(
            check_access_level_for_resource=lambda *a, **k: False,
            has_any_specific_access_for_resource=lambda *a, **k: False,
            filter_queryset_by_access_level=lambda queryset, resource=None: queryset,
        )

        resolution = resolve_scope(team=self.team, scope="billing", user_access_control=denying)

        assert [s for s in resolution.surfaces if s.kind == "action"] == []

    def test_events_resolve_project_wide_not_just_this_environment(self) -> None:
        # A definition recorded against the project rather than this environment: a literal team_id
        # filter misses it, and the events source then looks empty in every non-root environment.
        sibling = Team.objects.create(organization=self.organization, name="Sibling environment")
        EventDefinition.objects.create(
            team=sibling, project_id=self.team.project_id, name="billing_upgraded", last_seen_at=timezone.now()
        )

        resolution = self._resolve("billing")

        assert [s.key for s in resolution.surfaces if s.kind == "event"] == ["billing_upgraded"]

    def test_deleted_actions_are_excluded(self) -> None:
        Action.objects.create(team=self.team, name="Billing upgrade clicked", deleted=True)

        resolution = self._resolve("billing")

        assert [s for s in resolution.surfaces if s.kind == "action"] == []

    def test_custom_events_surface_but_posthog_internals_do_not(self) -> None:
        EventDefinition.objects.create(team=self.team, name="billing_upgraded", last_seen_at=timezone.now())
        EventDefinition.objects.create(team=self.team, name="$billing_internal", last_seen_at=timezone.now())

        resolution = self._resolve("billing")

        assert [s.key for s in resolution.surfaces if s.kind == "event"] == ["billing_upgraded"]

    @parameterized.expand([("pages",), ("playlists",), ("actions",), ("events",)])
    def test_one_failing_source_degrades_rather_than_fails(self, source: str) -> None:
        self.paths.return_value = _paths(("/billing", 900))
        self._playlist(name="Billing list")
        Action.objects.create(team=self.team, name="Billing clicked")
        EventDefinition.objects.create(team=self.team, name="billing_upgraded", last_seen_at=timezone.now())
        self._patch(f"{_MODULE}.{_SOURCE_FETCHERS[source]}", side_effect=RuntimeError("source down"))

        # Asks for a playlist so all four sources run and every one can be the failing one.
        resolution = self._resolve("billing playlist")

        assert resolution.degraded_sources == (source,)
        assert {s.kind for s in resolution.surfaces} == set(_KIND_BY_SOURCE.values()) - {_KIND_BY_SOURCE[source]}

    def test_estimate_failure_keeps_the_filter(self) -> None:
        self.paths.return_value = _paths(("/billing", 900))
        self.estimate.side_effect = RuntimeError("clickhouse down")

        resolution = self._resolve("billing")

        assert _visited_page_values(resolution.query) == ["/billing"]
        assert resolution.matched_sessions is None
        assert resolution.window_days is None
        assert resolution.degraded_sources == ("estimate",)
