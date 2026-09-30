import sys
import json
import unicodedata
from datetime import UTC, datetime
from io import StringIO
from typing import TYPE_CHECKING

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.core.management import call_command
from django.db import connection
from django.test import SimpleTestCase, TestCase
from django.test.utils import CaptureQueriesContext

from parameterized import parameterized
from rest_framework import status

from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.workflows.backend.api.hog_flow import _EMAIL_BODY_TEXT_SQL
from products.workflows.backend.api.test.test_hog_flow import _email_step
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow
from products.workflows.backend.models.hog_flow.search_text import (
    SEARCH_TEXT_SEPARATOR,
    email_body_text,
    find_step_matches,
    search_pattern,
    step_regex,
)

if TYPE_CHECKING:
    from rest_framework.response import _MonkeyPatchedResponse

_ExpectedMatches = dict[str, list[tuple[str, str, str]]]

_SEARCH_CASES: list[tuple[str, str, _ExpectedMatches]] = [
    ("name_match_ignores_case", "WELCOME", {"Welcome email": []}),
    ("description_match", "quarterly", {"Digest": []}),
    ("space_matches_separators", "password reset", {"Password_reset": []}),
    ("step_name_match", "monthly invoice", {"Billing": [("email_1", "step_name", "live")]}),
    ("email_subject_match", "for march", {"Billing": [("email_1", "subject", "live")]}),
    ("email_preheader_match", "billing page", {"Billing": [("email_1", "preheader", "live")]}),
    ("email_body_text_match", "is attached", {"Billing": [("email_1", "body", "live")]}),
    ("html_ignored_when_text_export_exists", "footer-links", {}),
    ("email_html_only_body_match", "for your payment", {"Receipts": [("email_1", "body", "live")]}),
    ("email_css_not_searched", "111111", {}),
    ("draft_email_subject_match", "beta access", {"Onboarding": [("email_1", "subject", "draft")]}),
    ("liquid_subject_matches_beside_the_tag", "your seat is ready", {"Nurture": [("email_1", "subject", "live")]}),
    ("regex_characters_match_literally", "[vip] early access", {"Nurture": [("email_3", "subject", "live")]}),
    ("percent_and_parentheses_match_literally", "50% off (today only)!", {"Nurture": [("email_2", "subject", "live")]}),
    ("body_phrase_across_newlines", "upgrade now to keep", {"Nurture": [("email_2", "body", "live")]}),
    (
        "html_with_liquid_in_attribute_still_matches_content",
        "thanks for your order",
        {"Promo": [("email_1", "body", "live")]},
    ),
    ("html_attribute_css_not_searched", "color:#ffffff", {}),
    ("html_script_not_searched", "trackVisit", {}),
    ("unclosed_tag_keeps_its_text", "5 < 6 apples", {"Unclosed": [("email_1", "body", "live")]}),
    ("numeric_subject_matches", "987654", {"Numbers": [("email_1", "subject", "live")]}),
    (
        "name_match_does_not_hide_step_matches",
        "march",
        {"March campaign": [], "Billing": [("email_1", "subject", "live")]},
    ),
    ("term_does_not_span_two_fields", "digest quarterly", {}),
]

# The fallback path reuses the list search's SQL, which the list tests cover. These cases check its wiring.
_FALLBACK_CASES = {
    "name_match_ignores_case",
    "description_match",
    "email_subject_match",
    "name_match_does_not_hide_step_matches",
    "numeric_subject_matches",
}


def _search_url(team_id: int) -> str:
    return f"/api/projects/{team_id}/hog_flows/search/"


class TestHogFlowSearchMatching(APIBaseTest):
    @classmethod
    def setUpTestData(cls) -> None:
        super().setUpTestData()
        HogFlow.objects.create(team=cls.team, name="Welcome email", created_by=cls.user)
        HogFlow.objects.create(team=cls.team, name="Password_reset", created_by=cls.user)
        HogFlow.objects.create(team=cls.team, name="Digest", description="quarterly summary", created_by=cls.user)
        HogFlow.objects.create(team=cls.team, name="March campaign", status=HogFlow.State.ACTIVE, created_by=cls.user)
        HogFlow.objects.create(
            team=cls.team,
            name="Billing",
            created_by=cls.user,
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
            team=cls.team,
            name="Receipts",
            created_by=cls.user,
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
            team=cls.team,
            name="Promo",
            created_by=cls.user,
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
            team=cls.team,
            name="Unclosed",
            created_by=cls.user,
            actions=[_email_step("email_1", "Fruit email", subject="Fruit", html="<p>We have 5 < 6 apples today")],
        )
        HogFlow.objects.create(
            team=cls.team,
            name="Numbers",
            created_by=cls.user,
            actions=[_email_step("email_1", "Code email", subject=987654)],
        )
        HogFlow.objects.create(
            team=cls.team,
            name="Nurture",
            status=HogFlow.State.ACTIVE,
            created_by=cls.user,
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
                _email_step("email_3", "Day 10", subject="[VIP] early access: final reminder"),
                {"id": "exit_node", "name": "Exit", "type": "exit", "config": {}},
            ],
        )
        HogFlow.objects.create(
            team=cls.team,
            name="Onboarding",
            status=HogFlow.State.ACTIVE,
            created_by=cls.user,
            draft={"actions": [_email_step("email_1", "Access email", subject="Your beta access starts today")]},
        )

    @parameterized.expand(
        [(f"{name}_stored", query, expected, False) for name, query, expected in _SEARCH_CASES]
        + [
            (f"{name}_fallback", query, expected, True)
            for name, query, expected in _SEARCH_CASES
            if name in _FALLBACK_CASES
        ]
    )
    def test_search_matches_name_description_and_step_content(
        self, _name: str, query: str, expected: _ExpectedMatches, fallback: bool
    ) -> None:
        if fallback:
            HogFlow.objects.filter(team=self.team).update(search_text=None)

        response = self.client.get(
            _search_url(self.team.id), {"q": query, "output": "matches", "max_matched_steps": 10}
        )

        assert response.status_code == status.HTTP_200_OK, response.json()
        results = {
            row["name"]: [(step["action_id"], step["field"], step["matched_in"]) for step in row["matched_steps"]]
            for row in response.json()["results"]
        }
        assert results == expected


class TestHogFlowSearchAPI(APIBaseTest):
    def _search(self, query: str, **params: str | int) -> "_MonkeyPatchedResponse":
        query_params: dict[str, str | int] = {"q": query, **params}
        return self.client.get(_search_url(self.team.id), query_params)

    def test_search_returns_an_excerpt_around_a_body_match(self) -> None:
        body = " ".join(["Filler words before the part that matters."] * 5)
        body += " Your renewal date moved to the first of the month. "
        body += " ".join(["Filler words after the part that matters."] * 5)
        HogFlow.objects.create(
            team=self.team, name="Renewals", created_by=self.user, actions=[_email_step("email_1", "Notice", text=body)]
        )

        (row,) = self._search("renewal date", output="matches").json()["results"]

        (step,) = row["matched_steps"]
        assert step["excerpt"] == "…the part that matters. Your renewal date moved to the first of the month.…"

    @parameterized.expand(
        [
            ("names", None, None, None, None),
            ("counts", ["name"], 3, None, None),
            ("matches", ["name"], 3, [("email_1", "subject", "")], True),
        ]
    )
    def test_output_mode_sets_how_much_a_row_says_about_the_match(
        self,
        output: str,
        fields: list[str] | None,
        step_count: int | None,
        steps: list[tuple[str, str, str]] | None,
        truncated: bool | None,
    ) -> None:
        HogFlow.objects.create(
            team=self.team,
            name="Seat reminders",
            created_by=self.user,
            actions=[
                _email_step(f"email_{index}", f"Email {index}", subject="Your seat is saved") for index in (1, 2, 3)
            ],
        )

        with CaptureQueriesContext(connection) as queries:
            response = self._search("seat", output=output, max_matched_steps=1, excerpt_chars=0)

        assert response.status_code == status.HTTP_200_OK, response.json()
        (row,) = response.json()["results"]
        assert row["matched_fields"] == fields
        assert row["matched_step_count"] == step_count
        matched_steps = row["matched_steps"]
        assert matched_steps == (
            None
            if steps is None
            else [{"action_id": a, "field": f, "matched_in": "live", "excerpt": e} for a, f, e in steps]
        )
        assert row["matched_steps_truncated"] == truncated
        (page_query,) = [q["sql"] for q in queries.captured_queries if 'FROM "posthog_hogflow"' in q["sql"]]
        selected_columns = page_query.split(' FROM "posthog_hogflow"')[0]
        assert ('"posthog_hogflow"."actions"' in selected_columns) is (output != "names")

    def test_search_pages_in_list_order_with_list_filters_in_one_query(self) -> None:
        for day, name in ((3, "Latest seat"), (2, "Recent seat"), (1, "Stale seat")):
            flow = HogFlow.objects.create(team=self.team, name=name, created_by=self.user, status=HogFlow.State.DRAFT)
            HogFlow.objects.filter(id=flow.id).update(updated_at=datetime(2026, 1, day, tzinfo=UTC))
        HogFlow.objects.create(
            team=self.team, name="Archived seat", created_by=self.user, status=HogFlow.State.ARCHIVED
        )
        HogFlow.objects.create(team=self.team, name="Unrelated", created_by=self.user, status=HogFlow.State.DRAFT)

        with CaptureQueriesContext(connection) as queries:
            response = self._search("seat", limit=2, status="draft")

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert [row["name"] for row in response.json()["results"]] == ["Latest seat", "Recent seat"]
        assert response.json()["count"] == 3
        assert response.json()["next"] is not None
        hog_flow_reads = [
            query["sql"] for query in queries.captured_queries if 'FROM "posthog_hogflow"' in query["sql"]
        ]
        assert len(hog_flow_reads) == 1, hog_flow_reads

    def test_search_counts_matches_when_the_page_is_past_the_end(self) -> None:
        HogFlow.objects.create(team=self.team, name="Seat reminder", created_by=self.user)

        response = self._search("seat", offset=5)

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json()["count"] == 1
        assert response.json()["results"] == []

    @parameterized.expand(
        [
            ("draft_only", "draft", ["draft", "draft_updated_at"], "beta access", False),
            ("name_only", "name", ["name"], "renamed onboarding", True),
        ]
    )
    def test_partial_save_refreshes_search_text(
        self, _name: str, changed: str, update_fields: list[str], query: str, expect_reload: bool
    ) -> None:
        created = HogFlow.objects.create(team=self.team, name="Onboarding", status=HogFlow.State.ACTIVE)
        flow = HogFlow.objects.get(id=created.id)
        # Another save changes the live steps after `flow` was loaded, so `flow` holds stale actions.
        created.actions = [_email_step("email_1", "Invoice email", subject="Your invoice for March")]
        created.save()
        flow.description = "Unsaved note"
        if changed == "name":
            flow.name = "Renamed onboarding"
        else:
            flow.draft = {"actions": [_email_step("email_2", "Access email", subject="Your beta access starts today")]}
            flow.draft_updated_at = datetime(2026, 1, 1, tzinfo=UTC)

        with patch("products.workflows.backend.models.hog_flow.hog_flow.reload_hog_flows_on_workers") as reload:
            flow.save(update_fields=update_fields)

        assert reload.called is expect_reload
        assert [row["id"] for row in self._search(query).json()["results"]] == [str(flow.id)]
        assert [row["id"] for row in self._search("invoice for march").json()["results"]] == [str(flow.id)]
        assert self._search("unsaved note").json()["results"] == []

    def test_save_of_a_deferred_instance_writes_only_its_loaded_fields(self) -> None:
        flow = HogFlow.objects.create(team=self.team, name="Seat reminder", description="Kept as stored")
        partial = HogFlow.objects.only("id", "name").get(id=flow.id)
        partial.name = "Seat waitlist"

        with CaptureQueriesContext(connection) as queries:
            partial.save()

        (update,) = [query["sql"] for query in queries.captured_queries if query["sql"].startswith("UPDATE")]
        assert '"description" =' not in update
        assert '"actions" =' not in update
        assert [row["name"] for row in self._search("seat waitlist").json()["results"]] == ["Seat waitlist"]
        assert [row["name"] for row in self._search("kept as stored").json()["results"]] == ["Seat waitlist"]

    @parameterized.expand([("write", False), ("dry_run", True)])
    def test_rebuild_command_fills_missing_and_stale_search_text(self, _name: str, dry_run: bool) -> None:
        missing = HogFlow.objects.create(team=self.team, name="Seat reminder", created_by=self.user)
        stale = HogFlow.objects.create(team=self.team, name="Old name", created_by=self.user)
        HogFlow.objects.filter(id=missing.id).update(search_text=None)
        HogFlow.objects.filter(id=stale.id).update(name="Seat waitlist")

        call_command("rebuild_hog_flow_search_text", page_size=1, dry_run=dry_run, stdout=StringIO())

        stored = dict(HogFlow.objects.filter(id__in=[missing.id, stale.id]).values_list("name", "search_text"))
        if dry_run:
            assert stored == {"Seat reminder": None, "Seat waitlist": "Old name"}
        else:
            assert stored == {"Seat reminder": "Seat reminder", "Seat waitlist": "Seat waitlist"}

    def test_personal_api_key_with_read_scope_can_search(self) -> None:
        HogFlow.objects.create(team=self.team, name="Seat reminder", created_by=self.user)
        key = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="hog_flow read", user=self.user, secure_value=hash_key_value(key), scopes=["hog_flow:read"]
        )
        self.client.logout()

        response = self.client.get(_search_url(self.team.id), {"q": "seat"}, headers={"authorization": f"Bearer {key}"})

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert [row["name"] for row in response.json()["results"]] == ["Seat reminder"]

    @parameterized.expand(
        [
            ("missing", None),
            ("blank", "   "),
            ("too_long", "a" * 201),
            ("separator", f"a{SEARCH_TEXT_SEPARATOR}b"),
        ]
    )
    def test_search_rejects_unusable_terms(self, _name: str, query: str | None) -> None:
        params = {} if query is None else {"q": query}

        response = self.client.get(_search_url(self.team.id), params)

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()


_TRICKY_EMAILS: list[tuple[str, dict[str, object]]] = [
    ("text_export_wins", {"text": "Plain text", "html": "<p>Html</p>"}),
    ("empty_text_uses_html", {"text": "", "html": "<p>Html <b>body</b></p>"}),
    ("boolean_text", {"text": False, "html": "<p>Html</p>"}),
    ("zero_text", {"text": 0, "html": "<p>Html</p>"}),
    ("unclosed_tag", {"html": "<p>5 < 6 and 7 > 3"}),
    ("quoted_gt_in_attribute", {"html": '<td title="a > b">cell</td> after'}),
    ("stray_quotes_in_text", {"html": "<p>It's \"quoted\" text</p><br>tail's"}),
    ("unclosed_style", {"html": "<style>.a{color:red} <p>kept</p>"}),
    ("uppercase_blocks", {"html": "<STYLE>.a{}</STYLE><SCRIPT>x()</SCRIPT><P>shown</P>"}),
    ("style_prefix_tag", {"html": "<styles>not a style</styles> tail"}),
    ("script_without_gt", {"html": "<script src='a.js' text"}),
    ("nested_style_opening", {"html": "<style><style>a</style>b</style>c"}),
    ("liquid_in_attribute", {"html": '<td style="{% if x > 1 %}color:red{% endif %}">Order</td>'}),
    ("unicode", {"html": "<p>Grüße, 東京 – ok</p>"}),
    ("no_body", {"subject": "Only a subject"}),
]


class TestEmailBodyTextMatchesSql(TestCase):
    @parameterized.expand(_TRICKY_EMAILS)
    def test_email_body_text_matches_the_sql_rule(self, _name: str, email: dict[str, object]) -> None:
        action = {"config": {"inputs": {"email": {"value": email}}}}
        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT {_EMAIL_BODY_TEXT_SQL} FROM (SELECT %s::jsonb AS action) AS step", [json.dumps(action)]
            )
            (expected,) = cursor.fetchone()

        assert email_body_text(email) == expected


class TestStepMatchSpaceMatchesSql(TestCase):
    def test_step_matcher_counts_the_same_characters_as_space_as_postgres(self) -> None:
        spaces = [
            chr(point)
            for point in range(sys.maxunicode + 1)
            if chr(point).isspace() or unicodedata.category(chr(point)).startswith("Z")
        ]
        texts = [f"seat{space}reminder" for space in spaces]
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT text ~* %s FROM unnest(%s::text[]) WITH ORDINALITY AS t(text, position) ORDER BY position",
                [search_pattern("seat reminder"), texts],
            )
            postgres = [matched for (matched,) in cursor.fetchall()]

        regex = step_regex("seat reminder")
        disagreeing = [
            f"U+{ord(space):04X}"
            for space, text, matched in zip(spaces, texts, postgres)
            if (regex.search(text) is not None) != matched
        ]
        assert disagreeing == []


class TestFindStepMatches(SimpleTestCase):
    def test_term_of_many_separators_matches_without_backtracking(self) -> None:
        target = "e" + " -" * 14 + " q"
        body = "e" + " -" * 40 + " x. Then the " + target + " line."
        actions = [_email_step("email_1", "Notice", text=body)]

        (match,) = find_step_matches(actions, None, step_regex(target), max_steps=1, excerpt_chars=80).steps

        assert match.excerpt.endswith(f"{target} line.")

    @parameterized.expand(
        [
            ("around_the_match", "renewal date", 30, "…Your renewal date moved…"),
            ("match_longer_than_budget", "renewal date moved to the first", 10, "…renewal da…"),
            ("no_text", "renewal date", 0, ""),
        ]
    )
    def test_excerpt_stays_within_the_character_budget(
        self, _name: str, term: str, excerpt_chars: int, expected: str
    ) -> None:
        body = "Filler words before it. Your renewal date moved to the first of the month. Filler words after it."
        actions = [_email_step("email_1", "Notice", text=body)]

        (match,) = find_step_matches(actions, None, step_regex(term), max_steps=1, excerpt_chars=excerpt_chars).steps

        assert match.excerpt == expected
