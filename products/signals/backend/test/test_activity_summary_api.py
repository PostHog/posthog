import json
import datetime
import dataclasses
from typing import Any

import time_machine
from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import patch

from django.utils import timezone

from parameterized import parameterized

from posthog.api.embedding_worker import EmbeddingResponse
from posthog.clickhouse.client import sync_execute
from posthog.models import Organization, Team, User

from products.signals.backend.activity_summary.config import ActivitySummaryConfig
from products.signals.backend.activity_summary.prompt import (
    EMBEDDING_DOCUMENT_TYPE,
    EMBEDDING_RENDERING,
    EMBEDDING_RENDERING_PROFILE,
    PROMPT_VERSION,
)
from products.signals.backend.activity_summary.render import RENDER_VERSION
from products.signals.backend.activity_summary.search import EMBEDDINGS_TABLE, member_activities, search_summaries
from products.signals.backend.hybrid_search import SearchMode
from products.signals.backend.models import UserActivitySummary, UserActivitySummaryVersion
from products.signals.backend.ranking.features import EMBEDDING_DIMENSIONS
from products.signals.backend.report_embeddings import EMBEDDING_PRODUCT
from products.signals.backend.test.test_scout_harness_api import _authenticate_as_scout

NOW = datetime.datetime(2026, 10, 19, 12, tzinfo=datetime.UTC)
SUMMARY = {
    "profile": "## Funnels\n- Builds the signup funnel.",
    "headline": "Builds the signup funnel.",
    "themes": [
        {"label": "Signup funnel", "mode": "building", "strength": "high", "refs": ["o1"], "last_seen": "2026-10-18"}
    ],
    "modes": ["building"],
    "recent_shift": "Moved from dashboards to funnels.",
}
COMPUTED = {
    "schema_version": 2,
    "owned": [
        {
            "ref": "o1",
            "type": "insight",
            "id": "12",
            "name": "Signup funnel",
            "edit_days": 2,
            "last_at": "2026-10-18",
            "created": True,
        }
    ],
    "watched": [],
    "pages": [{"ref": "p1", "product": "session_replay", "open_days": 2, "last_at": "2026-10-17"}],
    "products": {"works_in": ["product_analytics"], "visits": ["session_replay"]},
    "task_count": 1,
    "tasks": [{"ref": "t1", "last_at": "2026-10-16"}],
    "mcp_sessions": [{"ref": "m1", "last_at": "2026-10-18"}],
}
COMPUTED_V1 = {
    **{key: value for key, value in COMPUTED.items() if key not in ("tasks", "mcp_sessions")},
    "schema_version": 1,
}


@time_machine.travel(NOW, tick=False)
class TestActivitySummaryAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()
        self.config = ActivitySummaryConfig(enabled=True, organization_ids=(str(self.organization.id),))
        read_config = patch(
            "products.signals.backend.activity_summary.read.read_config", side_effect=lambda: self.config
        )
        read_config.start()
        self.addCleanup(read_config.stop)

    def _summary(
        self,
        user: User | None = None,
        *,
        summary: dict[str, Any] | None = None,
        version: int = 1,
        computed: dict[str, Any] = COMPUTED,
    ) -> None:
        UserActivitySummary.objects.for_team(self.team.id).create(
            team=self.team,
            user=user or self.user,
            status=UserActivitySummary.Status.OK,
            summary=SUMMARY if summary is None else summary,
            summary_text="text",
            generated_at=NOW,
            prompt_version=PROMPT_VERSION,
            render_version=RENDER_VERSION,
            version=version,
            computed=computed,
        )

    def _versions(self, count: int) -> None:
        self._summary(version=count)
        row = UserActivitySummary.objects.for_team(self.team.id).get(user=self.user)
        for number in range(1, count + 1):
            UserActivitySummaryVersion.objects.for_team(self.team.id).create(
                team=self.team,
                summary_row=row,
                version=number,
                summary={**SUMMARY, "headline": f"Version {number}"},
                summary_text="text",
                generated_at=NOW - datetime.timedelta(days=count - number),
                model="model",
                prompt_version=PROMPT_VERSION,
                render_version=RENDER_VERSION,
                input_watermark=NOW,
                computed=COMPUTED,
            )

    def _get(self, path: str = "") -> Any:
        return self.client.get(f"/api/projects/{self.team.id}/signals/activity_summary/{path}")

    @parameterized.expand(
        [
            ("disabled", {"enabled": False}, False, True),
            ("organization_not_listed", {"organization_ids": ("00000000-0000-0000-0000-000000000001",)}, False, True),
            ("team_skipped", {}, True, True),
            ("ai_processing_not_approved", {}, False, False),
        ]
    )
    def test_both_endpoints_return_404_outside_enrolled_teams(
        self, _name: str, overrides: dict[str, Any], skip_own_team: bool, approved: bool
    ) -> None:
        self._versions(1)
        self.config = dataclasses.replace(
            self.config, skip_team_ids=(self.team.id,) if skip_own_team else (), **overrides
        )
        self.organization.is_ai_data_processing_approved = approved
        self.organization.save()

        assert self._get().status_code == 404
        assert self._get("versions/").status_code == 404

    def test_enroll_all_approved_enrolls_an_unlisted_organization(self) -> None:
        self.config = ActivitySummaryConfig(enabled=True, enroll_all_approved=True)
        self._summary()

        response = self._get()

        assert response.status_code == 200
        assert response.json()["status"] == "ready"

    @parameterized.expand(
        [
            ("no_row", None, {"status": "not_ready", "headline": None, "profile": None, "computed": None}),
            (
                "current_row",
                SUMMARY,
                {
                    "status": "ready",
                    "headline": "Builds the signup funnel.",
                    "profile": SUMMARY["profile"],
                    "themes": SUMMARY["themes"],
                    "modes": ["building"],
                    "computed": COMPUTED,
                },
            ),
            (
                "pre_profile_row",
                {"summary": "Builds funnels.", "focus_areas": [], "products": []},
                {"status": "ready", "headline": "Builds funnels.", "profile": None},
            ),
            (
                "pre_theme_row",
                {
                    **SUMMARY,
                    "themes": None,
                    "focus_areas": [{"topic": "funnels", "strength": "high", "last_seen": None}],
                },
                {
                    "status": "ready",
                    "themes": [{"label": "funnels", "mode": None, "strength": "high", "refs": [], "last_seen": None}],
                },
            ),
        ]
    )
    def test_get_returns_the_summary_of_the_calling_user(
        self, _name: str, summary: dict[str, Any] | None, expected: dict[str, Any]
    ) -> None:
        other = User.objects.create_and_join(self.organization, "other@example.com", "password")
        self._summary(other, summary={**SUMMARY, "headline": "Someone else's work."})
        if summary is not None:
            self._summary(summary=summary)

        with patch("products.signals.backend.presentation.activity_summary.report_user_action") as capture:
            response = self._get()

        assert response.status_code == 200
        assert {key: response.json()[key] for key in expected} == expected
        properties = capture.call_args.kwargs["properties"]
        assert properties["status"] == expected["status"]
        assert not any(isinstance(value, str) and "funnel" in value.lower() for value in properties.values())

    @parameterized.expand(
        [
            ("current", COMPUTED, COMPUTED),
            ("version_1", COMPUTED_V1, {**COMPUTED_V1, "tasks": [], "mcp_sessions": []}),
            ("unknown_version", {**COMPUTED, "schema_version": 99}, None),
        ]
    )
    def test_get_reads_the_computed_fields_of_older_schema_versions(
        self, _name: str, computed: dict[str, Any], expected: dict[str, Any] | None
    ) -> None:
        self._summary(computed=computed)

        response = self._get()

        assert response.status_code == 200
        assert response.json()["computed"] == expected

    def test_versions_come_newest_first_and_the_limit_is_capped(self) -> None:
        self.config = ActivitySummaryConfig(enabled=True, organization_ids=(str(self.organization.id),), max_versions=3)
        self._versions(5)

        response = self._get("versions/?limit=10")

        assert response.status_code == 200
        assert [item["version"] for item in response.json()] == [5, 4, 3]
        assert all(item["profile"] is None and item["computed"] is None for item in response.json())

    @parameterized.expand([("existing", 2, 200), ("missing", 9, 404)])
    def test_one_version_returns_its_profile(self, _name: str, version: int, status_code: int) -> None:
        self._versions(3)

        response = self._get(f"versions/?version={version}")

        assert response.status_code == status_code
        if status_code == 200:
            assert response.json() == [
                {
                    "version": 2,
                    "generated_at": "2026-10-18T12:00:00Z",
                    "prompt_version": PROMPT_VERSION,
                    "headline": "Version 2",
                    "recent_shift": SUMMARY["recent_shift"],
                    "themes": SUMMARY["themes"],
                    "modes": SUMMARY["modes"],
                    "profile": SUMMARY["profile"],
                    "computed": COMPUTED,
                }
            ]


SEARCH = "products.signals.backend.activity_summary.search"
SCOUT_VIEWS = "products.signals.backend.scout_harness.views"


@time_machine.travel(NOW, tick=False)
class TestActivitySummarySearchAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()
        self.config = ActivitySummaryConfig(enabled=True, organization_ids=(str(self.organization.id),))
        for target, kwargs in (
            ("products.signals.backend.activity_summary.read.read_config", {"side_effect": lambda: self.config}),
            (f"{SEARCH}.feature_enabled_or_false", {"return_value": True}),
            ("posthog.api.embedding_worker.generate_embedding", {"return_value": EmbeddingResponse([0.1], 1, False)}),
        ):
            patcher = patch(target, **kwargs)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.sync_execute = patch(f"{SEARCH}.sync_execute", return_value=[]).start()
        self.addCleanup(patch.stopall)
        self.reader = User.objects.create_and_join(self.organization, "reader@example.com", None, first_name="Reader")
        _authenticate_as_scout(self)

    def _summary(
        self,
        user: User,
        headline: str,
        watched: str = "",
        *,
        summary: dict[str, Any] | None = None,
        computed: dict[str, Any] | None = None,
        generated_at: datetime.datetime = NOW,
    ) -> None:
        UserActivitySummary.objects.for_team(self.team.id).create(
            team=self.team,
            user=user,
            status=UserActivitySummary.Status.OK,
            summary={**SUMMARY, "headline": headline, "profile": f"## Work\n- {headline}", **(summary or {})},
            summary_text=headline,
            generated_at=generated_at,
            prompt_version=PROMPT_VERSION,
            render_version=RENDER_VERSION,
            version=1,
            computed={
                **COMPUTED,
                "watched": [
                    {
                        "ref": "o21",
                        "type": "dashboard",
                        "id": "7",
                        "name": watched,
                        "open_days": 9,
                        "last_at": "2026-10-18",
                        "not_theirs": True,
                    }
                ]
                if watched
                else [],
                **(computed or {}),
            },
        )

    def _search(self, **params: Any) -> Any:
        return self.client.get(f"/api/projects/{self.team.id}/signals/activity_summary_members/search/", params)

    def test_keyword_search_finds_a_reader_and_keeps_out_people_without_access(self) -> None:
        self._summary(self.user, "Builds the billing dashboards.")
        self._summary(self.reader, "Plans the roadmap.", watched="Onboarding drop-off")
        outsider = User.objects.create_and_join(Organization.objects.create(name="Other"), "out@example.com", None)
        self._summary(outsider, "Studies onboarding drop-off.")
        User.objects.create_and_join(self.organization, "quiet@example.com", None)

        response = self._search(query="onboarding drop-off", search_mode="keyword")

        assert response.status_code == 200, response.content
        body = response.json()
        assert [hit["user_uuid"] for hit in body["results"]] == [str(self.reader.uuid)]
        assert body["results"][0]["matched_on"] == [{"kind": "watched", "snippet": "Onboarding drop-off"}]
        assert body["results"][0]["profile"] is None
        assert body["semantic_used"] is False
        assert body["not_ready_count"] == 1
        self.sync_execute.assert_not_called()

    def test_hybrid_ranks_a_member_found_both_ways_first(self) -> None:
        self._summary(self.user, "Builds onboarding funnels.")
        self._summary(self.reader, "Watches activation.")
        self.sync_execute.return_value = [(str(self.reader.id), 0.2), (str(self.user.id), 0.3)]

        response = self._search(query="onboarding", include_profile="true")

        body = response.json()
        assert [hit["user_uuid"] for hit in body["results"]] == [str(self.user.uuid), str(self.reader.uuid)]
        assert [match["kind"] for match in body["results"][0]["matched_on"]] == ["semantic", "headline", "profile"]
        assert body["results"][0]["profile"] == "## Work\n- Builds onboarding funnels."
        assert body["semantic_used"] is True

    @parameterized.expand([("hybrid", 200), ("semantic", 503)])
    def test_a_failed_vector_read_degrades_only_a_hybrid_search(self, mode: str, expected_status: int) -> None:
        self._summary(self.reader, "Watches onboarding.")
        self.sync_execute.side_effect = RuntimeError("clickhouse down")

        response = self._search(query="onboarding", search_mode=mode)

        assert response.status_code == expected_status, response.content
        if expected_status == 200:
            assert response.json()["semantic_used"] is False
            assert [hit["user_uuid"] for hit in response.json()["results"]] == [str(self.reader.uuid)]

    @parameterized.expand([("repeated_params", False), ("mcp_json_array", True)])
    def test_excluded_members_and_other_products_drop_out(self, _name: str, json_encoded: bool) -> None:
        self._summary(self.user, "Builds onboarding funnels.")
        self._summary(self.reader, "Watches onboarding.")
        excluded = [str(self.user.uuid)]
        exclude_user_uuids = json.dumps(excluded) if json_encoded else excluded

        response = self._search(
            query="onboarding", search_mode="keyword", exclude_user_uuids=exclude_user_uuids, product="surveys"
        )
        assert response.json()["results"] == []
        response = self._search(query="onboarding", search_mode="keyword", exclude_user_uuids=exclude_user_uuids)
        assert response.status_code == 200, response.content
        assert [hit["user_uuid"] for hit in response.json()["results"]] == [str(self.reader.uuid)]

    @parameterized.expand(
        [
            ("watched_object", {"object_type": "dashboard", "object_id": "7"}, [("reader", "watched", "7")]),
            ("watched_object_as_owner", {"object_type": "dashboard", "object_id": "7", "object_relation": "owned"}, []),
            (
                "owned_insight_by_short_id",
                {"object_type": "insight", "object_id": "aBc123Xy"},
                [("user", "owned", "aBc123Xy")],
            ),
            (
                "file_system_type_suffix",
                {"object_type": "hog_function", "object_id": "3"},
                [("reader", "watched", "3")],
            ),
        ]
    )
    def test_object_filter_finds_people_who_change_or_open_an_object(
        self, _name: str, params: dict[str, str], expected: list[tuple[str, str, str]]
    ) -> None:
        owned = {"ref": "o1", "type": "insight", "id": "aBc123Xy", "name": "Signup funnel", "edit_days": 2}
        self._summary(self.user, "Builds the signup funnel.", computed={"owned": [owned]})
        watched = {"ref": "o22", "name": "Slack alerts", "open_days": 4, "last_at": "2026-10-18", "not_theirs": True}
        self._summary(
            self.reader,
            "Plans the roadmap.",
            computed={
                "owned": [],
                "watched": [
                    {**watched, "type": "dashboard", "id": "7", "name": "Onboarding drop-off"},
                    {**watched, "type": "hog_function/destination", "id": "3"},
                ],
            },
        )
        users = {"user": self.user, "reader": self.reader}

        response = self._search(**params)

        assert response.status_code == 200, response.content
        assert [
            (hit["user_uuid"], [(obj["relation"], obj["id"]) for obj in hit["objects"]])
            for hit in response.json()["results"]
        ] == [(str(users[who].uuid), [(relation, object_id)]) for who, relation, object_id in expected]

    @parameterized.expand(
        [
            ("overall_mode", {"mode": "monitoring"}, ["reader"], 1),
            ("theme_mode", {"mode": "investigating"}, ["reader"], 1),
            ("recent_activity", {"active_since_days": 7}, ["user"], 1),
            ("listed_members", {"user_uuids": "reader"}, ["reader"], 1),
            ("filters_combine_with_and", {"product": "product_analytics", "mode": "monitoring"}, [], 0),
            ("second_page", {"offset": 1, "limit": 1}, ["reader"], 2),
        ]
    )
    def test_filters_narrow_the_members_listed(
        self, _name: str, params: dict[str, Any], expected: list[str], total: int
    ) -> None:
        self._summary(self.user, "Builds the signup funnel.")
        self._summary(
            self.reader,
            "Watches retention.",
            summary={
                "modes": ["monitoring"],
                "themes": [
                    {
                        "label": "Retention",
                        "mode": "investigating",
                        "strength": "high",
                        "refs": [],
                        "last_seen": "2026-08-01",
                    }
                ],
            },
            computed={"owned": [], "products": {"works_in": ["session_replay"], "visits": []}},
            generated_at=NOW - datetime.timedelta(days=1),
        )
        users = {"user": self.user, "reader": self.reader}
        if "user_uuids" in params:
            params = {**params, "user_uuids": [str(users[params["user_uuids"]].uuid)]}

        response = self._search(**params)

        assert response.status_code == 200, response.content
        body = response.json()
        assert [hit["user_uuid"] for hit in body["results"]] == [str(users[who].uuid) for who in expected]
        assert body["total"] == total

    @parameterized.expand([("flag_off", True), ("not_enrolled", False)])
    def test_returns_404_when_search_is_off(self, _name: str, flag_off: bool) -> None:
        if flag_off:
            patch(f"{SEARCH}.feature_enabled_or_false", return_value=False).start()
        else:
            self.config = dataclasses.replace(self.config, enabled=False)

        assert self._search(query="onboarding").status_code == 404

    def test_session_auth_cannot_search(self) -> None:
        self.client.credentials()
        self.client.force_login(self.user)

        assert self._search(query="onboarding").status_code == 403

    def _members(self, **params: Any) -> Any:
        return self.client.get(f"/api/projects/{self.team.id}/signals/scout/members/", params)

    def test_a_narrowed_member_roster_carries_each_members_activity(self) -> None:
        self._summary(self.reader, "Plans the roadmap.", watched="Onboarding drop-off")
        User.objects.create_and_join(self.organization, "rest@example.com", None, first_name="Restless")

        response = self._members(search="re")

        assert response.status_code == 200, response.content
        by_email = {row["email"]: row for row in response.json()}
        assert by_email["rest@example.com"]["activity"] is None
        activity = by_email["reader@example.com"]["activity"]
        assert activity["headline"] == "Plans the roadmap."
        assert activity["themes"] == ["Signup funnel"]
        assert activity["owned"] == [{"type": "insight", "name": "Signup funnel"}]
        assert activity["watched"] == [{"type": "dashboard", "name": "Onboarding drop-off"}]
        assert activity["stale"] is False

    @parameterized.expand(
        [
            ("no_narrowing", False),
            ("over_row_limit", False),
            ("flag_off", True),
            ("not_enrolled", True),
            ("read_fails", True),
        ]
    )
    def test_member_roster_falls_back_to_no_activity(self, case: str, reads_activity: bool) -> None:
        self._summary(self.reader, "Plans the roadmap.")
        params = {} if case == "no_narrowing" else {"search": "reader"}
        if case == "over_row_limit":
            patch(f"{SCOUT_VIEWS}.MAX_MEMBERS_WITH_ACTIVITY", 0).start()
        if case == "flag_off":
            patch(f"{SEARCH}.feature_enabled_or_false", return_value=False).start()
        if case == "not_enrolled":
            self.config = dataclasses.replace(self.config, enabled=False)
        if case == "read_fails":
            patch(f"{SEARCH}.ready_view", side_effect=RuntimeError("bad row")).start()

        with patch(f"{SCOUT_VIEWS}.member_activities", wraps=member_activities) as read:
            response = self._members(**params)

        assert response.status_code == 200, response.content
        rows = response.json()
        assert str(self.reader.uuid) in {row["user_uuid"] for row in rows}
        assert all(row["activity"] is None for row in rows)
        assert read.called is reads_activity


class TestActivitySummarySemanticRanking(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()
        config = ActivitySummaryConfig(enabled=True, organization_ids=(str(self.organization.id),))
        query = [1.0, *([0.0] * (EMBEDDING_DIMENSIONS - 1))]
        for target, kwargs in (
            ("products.signals.backend.activity_summary.read.read_config", {"return_value": config}),
            (f"{SEARCH}.feature_enabled_or_false", {"return_value": True}),
            ("posthog.api.embedding_worker.generate_embedding", {"return_value": EmbeddingResponse(query, 1, False)}),
        ):
            patch(target, **kwargs).start()
        self.addCleanup(patch.stopall)

    def _member(self, email: str) -> User:
        user = User.objects.create_and_join(self.organization, email, None)
        UserActivitySummary.objects.for_team(self.team.id).create(
            team=self.team,
            user=user,
            status=UserActivitySummary.Status.OK,
            summary={**SUMMARY, "headline": email},
            summary_text=email,
            generated_at=timezone.now(),
            prompt_version=PROMPT_VERSION,
            render_version=RENDER_VERSION,
            version=1,
            computed=COMPUTED,
        )
        return user

    def _vectors(self, rows: list[tuple[int, User, str, int, tuple[float, float]]]) -> None:
        # The table drops rows three months after `timestamp` on the real clock, so the days are relative to now.
        now = timezone.now()
        values = []
        for team_id, user, rendering, days_ago, (x, y) in rows:
            at = now - datetime.timedelta(days=days_ago)
            embedding = [x, y, *([0.0] * (EMBEDDING_DIMENSIONS - 2))]
            document_id = f"{user.id}:{at.date().isoformat()}"
            values.append(
                (
                    team_id,
                    EMBEDDING_PRODUCT,
                    EMBEDDING_DOCUMENT_TYPE,
                    rendering,
                    document_id,
                    at,
                    at,
                    "",
                    "{}",
                    embedding,
                    at,
                    0,
                    0,
                )
            )
        sync_execute(
            f"""
            INSERT INTO {EMBEDDINGS_TABLE} (
                team_id, product, document_type, rendering, document_id,
                timestamp, inserted_at, content, metadata, embedding,
                _timestamp, _offset, _partition
            ) VALUES
            """,
            values,
            flush=False,
            team_id=self.team.pk,
        )

    def test_ranks_each_member_by_the_best_vector_of_their_newest_build(self) -> None:
        near, middle, far, farther = (1.0, 0.05), (1.0, 1.0), (0.2, 1.0), (0.0, 1.0)
        other_team = Team.objects.create(organization=self.organization)
        with_profile = self._member("profile@example.com")
        text_only = self._member("text@example.com")
        moved_on = self._member("moved@example.com")
        self._vectors(
            [
                (self.team.pk, with_profile, EMBEDDING_RENDERING, 1, far),
                (self.team.pk, with_profile, EMBEDDING_RENDERING_PROFILE, 1, near),
                (self.team.pk, text_only, EMBEDDING_RENDERING, 1, middle),
                (self.team.pk, moved_on, EMBEDDING_RENDERING, 3, near),
                (self.team.pk, moved_on, EMBEDDING_RENDERING_PROFILE, 3, near),
                (self.team.pk, moved_on, EMBEDDING_RENDERING, 1, farther),
                (other_team.pk, moved_on, EMBEDDING_RENDERING, 0, near),
            ]
        )

        result = search_summaries(self.team, query="onboarding", search_mode=SearchMode.SEMANTIC)

        assert result is not None
        assert result.semantic_used is True
        assert [hit.user_uuid for hit in result.results] == [
            str(with_profile.uuid),
            str(text_only.uuid),
            str(moved_on.uuid),
        ]
