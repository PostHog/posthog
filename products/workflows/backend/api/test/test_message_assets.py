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

from products.workflows.backend.api.assets_storage import BrowserlessUnavailable
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow

_STORAGE_PATH = "products.workflows.backend.api.hog_flow"


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
    s3_key: str = "message_assets/team-1/flow/inv/email-step.html",
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
        "s3_key": s3_key,
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

    def test_returns_asset_without_leaking_storage_key(self):
        # The storage key is resolved server-side for serving; it must not appear in the list response.
        self._seed("inv-1", recipient="bob@example.com", subject="Hi Bob", distinct_id="user-7")
        results = self._list().json()
        assert len(results) == 1
        row = results[0]
        assert row["invocation_id"] == "inv-1"
        assert row["recipient"] == "bob@example.com"
        assert row["subject"] == "Hi Bob"
        assert row["distinct_id"] == "user-7"
        assert "s3_key" not in row

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
        # Batch grouping: a workflow's assets split by the batch run they belong to.
        self._seed("inv-batch", parent_run_id="batch-1")
        self._seed("inv-continuous", parent_run_id="")
        batch = self._list({"parent_run_id": "batch-1"}).json()
        assert {r["invocation_id"] for r in batch} == {"inv-batch"}
        # An explicit empty string returns only event-triggered (non-batch) assets.
        continuous = self._list({"parent_run_id": ""}).json()
        assert {r["invocation_id"] for r in continuous} == {"inv-continuous"}

    def test_filters_by_action_id(self):
        # Drill-down from a single email step's metric.
        self._seed("inv-1", action_id="step-a")
        self._seed("inv-2", action_id="step-b")
        results = self._list({"action_id": "step-a"}).json()
        assert {r["invocation_id"] for r in results} == {"inv-1"}

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
        # offset past the first page still returns rows
        assert len(self._list({"limit": 2, "offset": 4}).json()) == 1

    def test_content_redirects_to_presigned_url(self):
        self._seed("inv-1", action_id="step-a", s3_key="message_assets/team/flow/inv-1/step-a.html")
        with patch(f"{_STORAGE_PATH}.presigned_content_url", return_value="https://s3.example/presigned") as mock_url:
            res = self.client.get(f"{self._base()}/assets/content/?invocation_id=inv-1&action_id=step-a")
        assert res.status_code == status.HTTP_302_FOUND
        assert res.url == "https://s3.example/presigned"
        mock_url.assert_called_once_with("message_assets/team/flow/inv-1/step-a.html")

    def test_content_404_for_unknown_asset(self):
        res = self.client.get(f"{self._base()}/assets/content/?invocation_id=nope&action_id=step-a")
        assert res.status_code == status.HTTP_404_NOT_FOUND

    def test_pdf_returns_pdf_bytes(self):
        self._seed("inv-1", action_id="step-a")
        with (
            patch(f"{_STORAGE_PATH}.read_html", return_value=b"<html></html>"),
            patch(f"{_STORAGE_PATH}.render_html_to_pdf", return_value=b"%PDF-1.4 fake") as mock_render,
        ):
            res = self.client.get(f"{self._base()}/assets/pdf/?invocation_id=inv-1&action_id=step-a")
        assert res.status_code == status.HTTP_200_OK
        assert res["Content-Type"] == "application/pdf"
        assert res.content == b"%PDF-1.4 fake"
        mock_render.assert_called_once_with(b"<html></html>")

    def test_pdf_503_when_browserless_unavailable(self):
        self._seed("inv-1", action_id="step-a")
        with (
            patch(f"{_STORAGE_PATH}.read_html", return_value=b"<html></html>"),
            patch(f"{_STORAGE_PATH}.render_html_to_pdf", side_effect=BrowserlessUnavailable("no browserless")),
        ):
            res = self.client.get(f"{self._base()}/assets/pdf/?invocation_id=inv-1&action_id=step-a")
        assert res.status_code == status.HTTP_503_SERVICE_UNAVAILABLE

    def test_pdf_404_when_content_missing(self):
        self._seed("inv-1", action_id="step-a")
        with patch(f"{_STORAGE_PATH}.read_html", return_value=None):
            res = self.client.get(f"{self._base()}/assets/pdf/?invocation_id=inv-1&action_id=step-a")
        assert res.status_code == status.HTTP_404_NOT_FOUND

    @parameterized.expand(
        [
            "assets/",
            "assets/content/?invocation_id=inv-1&action_id=step-a",
            "assets/pdf/?invocation_id=inv-1&action_id=step-a",
        ]
    )
    def test_personal_api_key_requires_person_read_scope(self, path: str):
        # Assets expose recipient/distinct_id/person_id and the message a person received, so a
        # hog_flow:read-only token must not reach them — person:read is also required.
        self._seed("inv-1", action_id="step-a")
        key = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="hog_flow only", user=self.user, secure_value=hash_key_value(key), scopes=["hog_flow:read"]
        )
        res = self.client.get(f"{self._base()}/{path}", headers={"authorization": f"Bearer {key}"})
        assert res.status_code == 403, res.json()
        assert "person:read" in res.json().get("detail", "")
