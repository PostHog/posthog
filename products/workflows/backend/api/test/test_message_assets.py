from datetime import UTC, datetime, timedelta
from typing import Any, Optional

from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from posthog.clickhouse.client.execute import sync_execute
from posthog.models.message_assets.sql import INSERT_MESSAGE_ASSET_SQL
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value
from posthog.test.persons import create_person

from products.workflows.backend.models.hog_flow.hog_flow import HogFlow


def create_message_asset(
    team_id: int,
    function_id: str,
    invocation_id: str,
    *,
    action_id: str = "email-step",
    function_kind: str = "hog_flow",
    parent_run_id: str = "",
    kind: str = "email",
    distinct_id: str = "user-1",
    person_id: str = "person-1",
    recipient: str = "person@example.com",
    subject: str = "Welcome",
    html: str = "<html><body>Hello</body></html>",
    asset_status: str = "sent",
    sent_at: Optional[datetime] = None,
    version: int = 1,
    is_deleted: int = 0,
) -> None:
    sent = sent_at or datetime.now(tz=UTC)
    params: dict[str, Any] = {
        "team_id": team_id,
        "function_kind": function_kind,
        "function_id": function_id,
        "parent_run_id": parent_run_id,
        "invocation_id": invocation_id,
        "action_id": action_id,
        "kind": kind,
        "distinct_id": distinct_id,
        "person_id": person_id,
        "recipient": recipient,
        "subject": subject,
        "html": html,
        "status": asset_status,
        "sent_at": sent,
        "version": version,
        "is_deleted": is_deleted,
    }
    sync_execute(INSERT_MESSAGE_ASSET_SQL, params)


class TestMessageAssets(ClickhouseTestMixin, APIBaseTest):
    def setUp(self):
        super().setUp()
        self.hog_flow = HogFlow.objects.create(team=self.team, name="Test Flow")
        ff_patcher = patch(
            "products.workflows.backend.api.message_assets.posthoganalytics.feature_enabled",
            return_value=True,
        )
        self.feature_enabled_mock = ff_patcher.start()
        self.addCleanup(ff_patcher.stop)

    def _base(self) -> str:
        return f"/api/projects/{self.team.id}/hog_flows/{self.hog_flow.id}"

    def _list(self, params=None):
        return self.client.get(f"{self._base()}/assets/", params)

    def _seed(self, invocation_id: str, **kwargs):
        create_message_asset(
            team_id=self.team.pk, function_id=str(self.hog_flow.pk), invocation_id=invocation_id, **kwargs
        )

    def test_returns_empty_when_no_assets(self):
        res = self._list()
        assert res.status_code == status.HTTP_200_OK
        assert res.json() == []

    def test_listing_returns_metadata_without_html(self):
        self._seed("inv-1", recipient="bob@example.com", subject="Hi Bob", distinct_id="user-7")
        results = self._list().json()
        assert len(results) == 1
        row = results[0]
        assert row["invocation_id"] == "inv-1"
        assert row["recipient"] == "bob@example.com"
        assert row["subject"] == "Hi Bob"
        assert row["distinct_id"] == "user-7"
        assert "html" not in row

    def test_collapses_to_latest_version(self):
        self._seed("inv-1", subject="first", version=1)
        self._seed("inv-1", subject="second", version=2)
        results = self._list().json()
        assert len(results) == 1
        assert results[0]["subject"] == "second"

    def test_excludes_deleted_assets(self):
        self._seed("inv-1", version=1)
        self._seed("inv-1", version=2, is_deleted=1)
        assert self._list().json() == []

    def test_filters_by_parent_run_id(self):
        self._seed("inv-batch", parent_run_id="batch-1")
        self._seed("inv-continuous", parent_run_id="")
        batch = self._list({"parent_run_id": "batch-1"}).json()
        assert {r["invocation_id"] for r in batch} == {"inv-batch"}
        continuous = self._list({"parent_run_id": ""}).json()
        assert {r["invocation_id"] for r in continuous} == {"inv-continuous"}

    def test_filters_by_action_id(self):
        self._seed("inv-1", action_id="step-a")
        self._seed("inv-2", action_id="step-b")
        results = self._list({"action_id": "step-a"}).json()
        assert {r["invocation_id"] for r in results} == {"inv-1"}

    def test_filters_by_invocation_id(self):
        self._seed("inv-1")
        self._seed("inv-2")
        results = self._list({"invocation_id": "inv-1"}).json()
        assert {r["invocation_id"] for r in results} == {"inv-1"}

    def test_invocation_id_filter_returns_empty_when_no_asset_was_captured(self):
        self._seed("inv-1")
        results = self._list({"invocation_id": "inv-nonexistent"}).json()
        assert results == []

    def test_filters_by_distinct_id(self):
        self._seed("inv-1", distinct_id="user-a")
        self._seed("inv-2", distinct_id="user-b")
        results = self._list({"distinct_id": "user-a"}).json()
        assert {r["invocation_id"] for r in results} == {"inv-1"}

    @parameterized.expand(
        [
            ("bob", {"inv-1"}),
            ("Newsletter", {"inv-2"}),
            ("example.com", {"inv-1", "inv-2"}),
        ]
    )
    def test_search_matches_recipient_or_subject(self, term: str, expected_ids: set):
        self._seed("inv-1", recipient="bob@example.com", subject="Welcome")
        self._seed("inv-2", recipient="alice@example.com", subject="Newsletter")
        results = self._list({"search": term}).json()
        assert {r["invocation_id"] for r in results} == expected_ids

    def test_isolated_from_other_flow_and_function_kind(self):
        self._seed("inv-mine")
        create_message_asset(
            team_id=self.team.pk,
            function_id=str(self.hog_flow.pk),
            invocation_id="inv-fn",
            function_kind="hog_function",
        )
        create_message_asset(team_id=self.team.pk, function_id="other-flow", invocation_id="inv-other")
        results = self._list().json()
        assert {r["invocation_id"] for r in results} == {"inv-mine"}

    def test_default_window_excludes_rows_older_than_30d(self):
        now = datetime.now(tz=UTC)
        self._seed("recent", sent_at=now - timedelta(days=2))
        self._seed("old", sent_at=now - timedelta(days=45))
        results = self._list().json()
        assert {r["invocation_id"] for r in results} == {"recent"}

    def test_respects_limit_and_offset(self):
        for i in range(5):
            self._seed(f"inv-{i}")
        assert len(self._list({"limit": 2}).json()) == 2
        assert len(self._list({"limit": 2, "offset": 4}).json()) == 1

    def test_content_returns_html_bytes_inline(self):
        self._seed("inv-1", action_id="step-a", html="<html><body>Hello Bob</body></html>")
        res = self.client.get(f"{self._base()}/assets/content/?invocation_id=inv-1&action_id=step-a")
        assert res.status_code == status.HTTP_200_OK
        assert res["Content-Type"] == "text/html; charset=utf-8"
        assert res.content == b"<html><body>Hello Bob</body></html>"
        # Sandbox at the response layer so direct navigation to this URL still can't
        # run scripts as the viewer — the iframe's `sandbox=""` alone doesn't protect
        # someone who opens the asset URL in a new tab. Regressing this reintroduces
        # stored-XSS in captured email HTML.
        assert "sandbox" in res["Content-Security-Policy"]
        assert res["X-Content-Type-Options"] == "nosniff"

    def test_content_returns_latest_version_html(self):
        self._seed("inv-1", action_id="step-a", html="<p>old</p>", version=1)
        self._seed("inv-1", action_id="step-a", html="<p>new</p>", version=2)
        res = self.client.get(f"{self._base()}/assets/content/?invocation_id=inv-1&action_id=step-a")
        assert res.status_code == status.HTTP_200_OK
        assert res.content == b"<p>new</p>"

    def test_content_404_for_unknown_asset(self):
        res = self.client.get(f"{self._base()}/assets/content/?invocation_id=nope&action_id=step-a")
        assert res.status_code == status.HTTP_404_NOT_FOUND

    def test_content_404_for_deleted_asset(self):
        self._seed("inv-1", action_id="step-a", version=1)
        self._seed("inv-1", action_id="step-a", version=2, is_deleted=1)
        res = self.client.get(f"{self._base()}/assets/content/?invocation_id=inv-1&action_id=step-a")
        assert res.status_code == status.HTTP_404_NOT_FOUND

    @parameterized.expand(
        [
            "assets/",
            "assets/content/?invocation_id=inv-1&action_id=step-a",
        ]
    )
    def test_personal_api_key_requires_person_read_scope(self, path: str):
        self._seed("inv-1", action_id="step-a")
        key = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="hog_flow only", user=self.user, secure_value=hash_key_value(key), scopes=["hog_flow:read"]
        )
        res = self.client.get(f"{self._base()}/{path}", headers={"authorization": f"Bearer {key}"})
        assert res.status_code == 403, res.json()
        assert "person:read" in res.json().get("detail", "")

    @parameterized.expand(
        [
            "assets/",
            "assets/content/?invocation_id=inv-1&action_id=step-a",
        ]
    )
    def test_404_when_ui_flag_disabled(self, path: str):
        self._seed("inv-1", action_id="step-a")
        self.feature_enabled_mock.return_value = False
        res = self.client.get(f"{self._base()}/{path}")
        assert res.status_code == status.HTTP_404_NOT_FOUND


class TestPersonEmails(ClickhouseTestMixin, APIBaseTest):
    def setUp(self):
        super().setUp()
        self.person = create_person(team=self.team, distinct_ids=["distinct-1"], properties={"email": "p@example.com"})
        self.hog_flow = HogFlow.objects.create(team=self.team, name="Welcome flow")
        ff_patcher = patch(
            "products.workflows.backend.api.message_assets.posthoganalytics.feature_enabled",
            return_value=True,
        )
        self.feature_enabled_mock = ff_patcher.start()
        self.addCleanup(ff_patcher.stop)

    def _emails(self, params=None):
        return self.client.get(f"/api/projects/{self.team.id}/persons/{self.person.uuid}/emails/", params)

    def _seed(self, invocation_id: str, *, person_id: Optional[str] = None, **kwargs):
        create_message_asset(
            team_id=self.team.pk,
            function_id=str(self.hog_flow.pk),
            invocation_id=invocation_id,
            person_id=person_id or str(self.person.uuid),
            **kwargs,
        )

    def test_returns_empty_when_person_has_no_emails(self):
        res = self._emails()
        assert res.status_code == status.HTTP_200_OK
        assert res.json() == []

    def test_returns_emails_with_function_id_for_navigation(self):
        self._seed("inv-1", subject="Hello", recipient="p@example.com")
        rows = self._emails().json()
        assert len(rows) == 1
        row = rows[0]
        assert row["invocation_id"] == "inv-1"
        assert row["subject"] == "Hello"
        assert row["recipient"] == "p@example.com"
        assert row["function_id"] == str(self.hog_flow.pk)
        assert "html" not in row

    def test_isolated_from_other_persons(self):
        self._seed("mine")
        self._seed("theirs", person_id="00000000-0000-0000-0000-000000000999")
        rows = self._emails().json()
        assert {r["invocation_id"] for r in rows} == {"mine"}

    def test_isolated_from_other_teams(self):
        self._seed("mine")
        create_message_asset(
            team_id=self.team.pk + 9999,
            function_id=str(self.hog_flow.pk),
            invocation_id="other-team",
            person_id=str(self.person.uuid),
        )
        rows = self._emails().json()
        assert {r["invocation_id"] for r in rows} == {"mine"}

    def test_excludes_standalone_hog_function_emails(self):
        self._seed("flow-row")
        self._seed("fn-row", function_kind="hog_function")
        rows = self._emails().json()
        assert {r["invocation_id"] for r in rows} == {"flow-row"}

    def test_collapses_to_latest_version(self):
        self._seed("inv-1", subject="first", version=1)
        self._seed("inv-1", subject="second", version=2)
        rows = self._emails().json()
        assert len(rows) == 1
        assert rows[0]["subject"] == "second"

    def test_excludes_deleted(self):
        self._seed("inv-1", version=1)
        self._seed("inv-1", version=2, is_deleted=1)
        assert self._emails().json() == []

    def test_sorted_newest_first(self):
        now = datetime.now(tz=UTC)
        self._seed("older", sent_at=now - timedelta(hours=2))
        self._seed("newer", sent_at=now - timedelta(minutes=5))
        rows = self._emails().json()
        assert [r["invocation_id"] for r in rows] == ["newer", "older"]

    def test_respects_limit_and_offset(self):
        for i in range(5):
            self._seed(f"inv-{i}")
        assert len(self._emails({"limit": 2}).json()) == 2
        assert len(self._emails({"limit": 2, "offset": 4}).json()) == 1

    def test_personal_api_key_requires_person_read_scope(self):
        self._seed("inv-1")
        key = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="no person scope",
            user=self.user,
            secure_value=hash_key_value(key),
            scopes=["hog_flow:read"],
        )
        res = self.client.get(
            f"/api/projects/{self.team.id}/persons/{self.person.uuid}/emails/",
            headers={"authorization": f"Bearer {key}"},
        )
        assert res.status_code == 403, res.json()
        assert "person:read" in res.json().get("detail", "")

    def test_404_when_ui_flag_disabled(self):
        self._seed("inv-1")
        self.feature_enabled_mock.return_value = False
        assert self._emails().status_code == status.HTTP_404_NOT_FOUND
