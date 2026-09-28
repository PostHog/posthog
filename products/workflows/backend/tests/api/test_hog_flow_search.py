from datetime import UTC, datetime
from io import StringIO
from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.core.management import call_command
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.workflows.backend.models.hog_flow.hog_flow import HogFlow


def _email_step(step_id: str, name: str, **email_value: Any) -> dict[str, Any]:
    return {
        "id": step_id,
        "name": name,
        "type": "function_email",
        "config": {"template_id": "template-email", "inputs": {"email": {"value": email_value}}},
    }


_ExpectedMatches = dict[str, list[tuple[str, str, str]]]


def _search_cases() -> list[tuple[str, str, _ExpectedMatches, str]]:
    cases: list[tuple[str, str, _ExpectedMatches]] = [
        ("name_match", "welcome", {"Welcome email": []}),
        ("case_insensitive", "WELCOME", {"Welcome email": []}),
        ("description_match", "quarterly", {"Digest": []}),
        ("space_matches_separators", "password reset", {"Password reset": []}),
        ("step_name_match", "monthly invoice", {"Billing": [("email_1", "step_name", "live")]}),
        ("email_subject_match", "for march", {"Billing": [("email_1", "subject", "live")]}),
        ("email_preheader_match", "billing page", {"Billing": [("email_1", "preheader", "live")]}),
        ("email_body_text_match", "is attached", {"Billing": [("email_1", "body", "live")]}),
        ("email_markup_not_searched", "footer-links", {}),
        ("email_html_only_body_match", "for your payment", {"Receipts": [("email_1", "body", "live")]}),
        ("email_css_not_searched", "111111", {}),
        ("draft_email_subject_match", "beta access", {"Onboarding": [("email_1", "subject", "draft")]}),
        ("email_in_later_step_matches", "final reminder", {"Nurture": [("email_3", "subject", "live")]}),
        ("liquid_subject_matches_beside_the_tag", "your seat is ready", {"Nurture": [("email_1", "subject", "live")]}),
        ("liquid_subject_not_matched_by_rendered_wording", "hi jane, your seat", {}),
        ("regex_characters_match_literally", "[vip] early access", {"Nurture": [("email_3", "subject", "live")]}),
        (
            "percent_and_parentheses_match_literally",
            "50% off (today only)!",
            {"Nurture": [("email_2", "subject", "live")]},
        ),
        ("body_phrase_across_newlines", "upgrade now to keep", {"Nurture": [("email_2", "body", "live")]}),
        (
            "shared_subject_returns_every_workflow",
            "seat is confirmed",
            {"Alpha": [("email_1", "subject", "live")], "Beta": [("email_1", "subject", "live")]},
        ),
        (
            "html_with_liquid_in_attribute_still_matches_content",
            "thanks for your order",
            {"Promo": [("email_1", "body", "live")]},
        ),
        ("html_attribute_css_not_searched", "color:#ffffff", {}),
        ("html_script_not_searched", "trackVisit", {}),
        ("unclosed_tag_keeps_its_text", "5 < 6 apples", {"Unclosed": [("email_1", "body", "live")]}),
        (
            "name_match_does_not_hide_step_matches",
            "march",
            {"March campaign": [], "Billing": [("email_1", "subject", "live")]},
        ),
        ("term_does_not_span_two_fields", "digest quarterly", {}),
        ("no_match", "nonexistent", {}),
    ]
    return [
        (f"{name}_{mode}", query, expected, mode) for name, query, expected in cases for mode in ("stored", "fallback")
    ]


class TestHogFlowSearchAPI(APIBaseTest):
    def _search(self, query: str, **params: Any):
        return self.client.get(f"/api/projects/{self.team.id}/hog_flows/search/", {"q": query, **params})

    def _create_search_fixtures(self) -> None:
        HogFlow.objects.create(team=self.team, name="Welcome email", created_by=self.user)
        HogFlow.objects.create(team=self.team, name="Password reset", created_by=self.user)
        HogFlow.objects.create(team=self.team, name="Digest", description="quarterly summary", created_by=self.user)
        HogFlow.objects.create(team=self.team, name="March campaign", status=HogFlow.State.ACTIVE, created_by=self.user)
        HogFlow.objects.create(
            team=self.team,
            name="Billing",
            created_by=self.user,
            actions=[
                _email_step(
                    "email_1",
                    "Monthly invoice email",
                    subject="Your invoice for March is ready",
                    preheader="Download it from your billing page",
                    text="Your invoice is attached.",
                    html='<table class="footer-links"><tr><td>Your invoice is attached.</td></tr></table>',
                )
            ],
        )
        HogFlow.objects.create(
            team=self.team,
            name="Receipts",
            created_by=self.user,
            actions=[
                _email_step(
                    "email_1",
                    "Receipt email",
                    subject="Your receipt",
                    html='<style type="text/css">.footer { color: #111111; }</style><p>Thanks for your <strong>payment</strong></p>',
                )
            ],
        )
        HogFlow.objects.create(
            team=self.team,
            name="Promo",
            created_by=self.user,
            actions=[
                _email_step(
                    "email_1",
                    "Order email",
                    subject="Order update",
                    html=(
                        "<script>trackVisit()</script>"
                        '<td style="{% if person.properties.orders > 1 %}color:#ffffff{% endif %}">Thanks for your order</td>'
                    ),
                )
            ],
        )
        HogFlow.objects.create(
            team=self.team,
            name="Unclosed",
            created_by=self.user,
            actions=[_email_step("email_1", "Fruit email", subject="Fruit", html="<p>We have 5 < 6 apples today")],
        )
        HogFlow.objects.create(
            team=self.team,
            name="Nurture",
            status=HogFlow.State.ACTIVE,
            created_by=self.user,
            actions=[
                {"id": "trigger_node", "name": "Trigger", "type": "trigger", "config": {"type": "event"}},
                _email_step("email_1", "Day 1", subject="Hi {{ person.properties.first_name }}, your seat is ready"),
                {"id": "delay_1", "name": "Wait 3 days", "type": "delay", "config": {"delay_duration": "3d"}},
                _email_step(
                    "email_2",
                    "Day 4",
                    subject="50% off (today only)! Upgrade before Friday",
                    text="Upgrade now\n\nto keep your dashboards and alerts.",
                ),
                {"id": "branch_1", "name": "Has upgraded?", "type": "conditional_branch", "config": {}},
                _email_step("email_3", "Day 10", subject="[VIP] early access: final reminder"),
                {"id": "exit_node", "name": "Exit", "type": "exit", "config": {}},
            ],
        )
        for name in ("Alpha", "Beta"):
            HogFlow.objects.create(
                team=self.team,
                name=name,
                created_by=self.user,
                actions=[_email_step("email_1", "Confirmation", subject="Your seat is confirmed")],
            )
        HogFlow.objects.create(
            team=self.team,
            name="Onboarding",
            status=HogFlow.State.ACTIVE,
            created_by=self.user,
            draft={"actions": [_email_step("email_1", "Access email", subject="Your beta access starts today")]},
        )

    def _results_by_name(self, response) -> dict[str, list[tuple[str, str, str]]]:
        assert response.status_code == status.HTTP_200_OK, response.json()
        return {
            row["name"]: [(step["action_id"], step["field"], step["source"]) for step in row["matched_steps"]]
            for row in response.json()["results"]
        }

    @parameterized.expand(_search_cases())
    def test_search_matches_name_description_and_step_content(self, _name, query, expected, mode):
        self._create_search_fixtures()
        if mode == "fallback":
            HogFlow.objects.filter(team=self.team).update(search_text=None)

        assert self._results_by_name(self._search(query)) == expected

    def test_search_returns_an_excerpt_around_a_body_match(self):
        body = " ".join(["Filler words before the part that matters."] * 5)
        body += " Your renewal date moved to the first of the month. "
        body += " ".join(["Filler words after the part that matters."] * 5)
        HogFlow.objects.create(
            team=self.team, name="Renewals", created_by=self.user, actions=[_email_step("email_1", "Notice", text=body)]
        )

        (row,) = self._search("renewal date").json()["results"]

        (step,) = row["matched_steps"]
        assert step["excerpt"] == "…before the part that matters. Your renewal date moved to the first of the month.…"

    def test_search_pages_newest_created_first_with_one_search_scan(self):
        for index, name in enumerate(("Oldest seat", "Middle seat", "Newest seat")):
            flow = HogFlow.objects.create(team=self.team, name=name, created_by=self.user)
            HogFlow.objects.filter(id=flow.id).update(created_at=datetime(2026, 1, index + 1, tzinfo=UTC))
        HogFlow.objects.create(team=self.team, name="Unrelated", created_by=self.user)

        with CaptureQueriesContext(connection) as queries:
            response = self._search("seat", limit=2)

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert [row["name"] for row in response.json()["results"]] == ["Newest seat", "Middle seat"]
        assert response.json()["count"] == 3
        assert response.json()["next"] is not None
        search_scans = [query["sql"] for query in queries.captured_queries if "~*" in query["sql"]]
        assert len(search_scans) == 1, search_scans

    def test_search_counts_matches_when_the_page_is_past_the_end(self):
        HogFlow.objects.create(team=self.team, name="Seat reminder", created_by=self.user)

        response = self._search("seat", offset=5)

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json()["count"] == 1
        assert response.json()["results"] == []

    @parameterized.expand(
        [
            ("draft_only", ["draft", "draft_updated_at"], "beta access", False),
            ("name_only", ["name"], "renamed onboarding", True),
        ]
    )
    def test_partial_save_refreshes_search_text(self, _name, update_fields, query, expect_reload):
        flow = HogFlow.objects.create(team=self.team, name="Onboarding", status=HogFlow.State.ACTIVE)
        flow.name = "Renamed onboarding"
        flow.draft = {"actions": [_email_step("email_1", "Access email", subject="Your beta access starts today")]}
        flow.draft_updated_at = timezone.now()

        with patch("products.workflows.backend.models.hog_flow.hog_flow.reload_hog_flows_on_workers") as reload:
            flow.save(update_fields=update_fields)

        assert reload.called is expect_reload
        assert [row["id"] for row in self._search(query).json()["results"]] == [str(flow.id)]

    def test_rebuild_command_fills_missing_and_stale_search_text(self):
        missing = HogFlow.objects.create(team=self.team, name="Seat reminder", created_by=self.user)
        stale = HogFlow.objects.create(team=self.team, name="Seat waitlist", created_by=self.user)
        HogFlow.objects.filter(id=missing.id).update(search_text=None)
        HogFlow.objects.filter(id=stale.id).update(search_text="outdated")

        call_command("rebuild_hog_flow_search_text", page_size=1, stdout=StringIO())

        assert not HogFlow.objects.filter(team=self.team, search_text__isnull=True).exists()
        assert {row["name"] for row in self._search("seat").json()["results"]} == {"Seat reminder", "Seat waitlist"}

    def test_personal_api_key_with_read_scope_can_search(self):
        HogFlow.objects.create(team=self.team, name="Seat reminder", created_by=self.user)
        key = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="hog_flow read", user=self.user, secure_value=hash_key_value(key), scopes=["hog_flow:read"]
        )
        self.client.logout()

        response = self.client.get(
            f"/api/projects/{self.team.id}/hog_flows/search/",
            {"q": "seat"},
            headers={"authorization": f"Bearer {key}"},
        )

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert [row["name"] for row in response.json()["results"]] == ["Seat reminder"]

    @parameterized.expand([("missing", None), ("blank", "   "), ("too_long", "a" * 201)])
    def test_search_rejects_unusable_terms(self, _name, query):
        params = {} if query is None else {"q": query}

        response = self.client.get(f"/api/projects/{self.team.id}/hog_flows/search/", params)

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
