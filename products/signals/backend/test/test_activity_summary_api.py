import datetime
import dataclasses
from typing import Any

import time_machine
from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.models import User

from products.signals.backend.activity_summary.config import ActivitySummaryConfig
from products.signals.backend.activity_summary.prompt import PROMPT_VERSION
from products.signals.backend.activity_summary.render import RENDER_VERSION
from products.signals.backend.models import UserActivitySummary, UserActivitySummaryVersion

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
    "schema_version": 1,
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
    "task_count": 0,
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

    def _summary(self, user: User | None = None, *, summary: dict[str, Any] | None = None, version: int = 1) -> None:
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
            computed=COMPUTED,
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

    def test_read_access_does_not_follow_the_generation_check(self) -> None:
        self._versions(1)
        self.config = dataclasses.replace(self.config, skip_team_ids=(self.team.id,))

        with patch(
            "products.signals.backend.activity_summary.queue.is_team_enrolled_for_generation", return_value=True
        ):
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
