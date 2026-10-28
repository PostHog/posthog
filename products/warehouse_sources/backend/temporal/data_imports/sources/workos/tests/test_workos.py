import json
import dataclasses
from typing import Any

import pytest
from unittest.mock import MagicMock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.workos import WorkOSSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.workos.settings import ENDPOINTS, WORKOS_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.workos.source import WorkOSSource
from products.warehouse_sources.backend.temporal.data_imports.sources.workos.workos import (
    WorkOSPaginator,
    WorkOSResumeConfig,
    create_webhook,
    delete_webhook,
    get_webhook_info,
    sync_webhook_events,
    validate_credentials,
)


class TestWorkOSPaginator:
    def test_get_resume_state_none_on_terminal_page(self) -> None:
        # A terminal page leaves the previous cursor in ``_after``; resume state
        # must still be None so we don't re-fetch an already-processed page.
        paginator = WorkOSPaginator()
        first = MagicMock()
        first.json.return_value = {"data": [{"id": "org_1"}], "list_metadata": {"after": "org_1"}}
        paginator.update_state(first)
        terminal = MagicMock()
        terminal.json.return_value = {"data": [{"id": "org_2"}], "list_metadata": {"after": None}}
        paginator.update_state(terminal)
        assert paginator.has_next_page is False
        assert paginator.get_resume_state() is None


def _page(ids: list[str], after: str | None) -> dict[str, Any]:
    return {"data": [{"id": i} for i in ids], "list_metadata": {"before": None, "after": after}}


class TestWorkOSEndpoints:
    def test_all_endpoints_registered(self) -> None:
        assert set(ENDPOINTS) == set(WORKOS_ENDPOINTS)
        # Every endpoint partitions on the immutable created_at field.
        assert all(cfg.partition_key == "created_at" for cfg in WORKOS_ENDPOINTS.values())


class TestWorkOSSourceResumeBehavior:
    """End-to-end resume behaviour through the shared ``rest_api_resource`` path."""

    @staticmethod
    def _run(script: list[ScriptedResponse], **inputs: Any) -> DriveResult:
        return SourceDriver(WorkOSSource(), WorkOSSourceConfig(api_key="sk_test_123")).run(
            "organizations", script, **inputs
        )

    def test_fresh_run_saves_cursor_after_each_non_terminal_page(self) -> None:
        result = self._run(
            [
                ScriptedResponse(json=_page(["org_1", "org_2"], after="org_2")),
                ScriptedResponse(json=_page(["org_3", "org_4"], after="org_4")),
                ScriptedResponse(json=_page(["org_5"], after=None)),
            ]
        )

        # First request omits the cursor (fresh run); subsequent requests carry it.
        assert result.params("after") == [None, "org_2", "org_4"]
        assert result.saved_states == [WorkOSResumeConfig(after="org_2"), WorkOSResumeConfig(after="org_4")]

    def test_resume_seeds_paginator_with_saved_cursor(self) -> None:
        result = self._run(
            [ScriptedResponse(json=_page(["org_5"], after=None))],
            resume_state=WorkOSResumeConfig(after="org_4"),
        )

        # First request goes out at the resumed cursor, so synced pages are not re-fetched.
        assert result.params("after") == ["org_4"]


class TestWorkOSWaitlistEntriesFanout:
    @staticmethod
    def _run(script: list[ScriptedResponse], **inputs: Any) -> DriveResult:
        return SourceDriver(WorkOSSource(), WorkOSSourceConfig(api_key="sk_test_123")).run(
            "waitlist_entries", script, **inputs
        )

    def test_walks_every_page_of_every_waitlist(self) -> None:
        result = self._run(
            [
                ScriptedResponse(json=_page(["waitlist_a", "waitlist_b"], after=None)),
                ScriptedResponse(json=_page(["wl_user_1"], after="wl_user_1")),
                ScriptedResponse(json=_page(["wl_user_2"], after=None)),
                ScriptedResponse(json=_page(["wl_user_3"], after=None)),
            ]
        )

        assert [row["id"] for row in result.rows] == ["wl_user_1", "wl_user_2", "wl_user_3"]
        assert result.paths == [
            "/user_management/waitlists",
            "/user_management/waitlists/waitlist_a/entries",
            "/user_management/waitlists/waitlist_a/entries",
            "/user_management/waitlists/waitlist_b/entries",
        ]
        # The waitlists listing is unpaginated and documents no `limit`.
        assert result.params("limit") == [None, "100", "100", "100"]
        assert result.params("after") == [None, None, "wl_user_1", None]

    def test_resume_skips_finished_waitlists_and_continues_the_current_one(self) -> None:
        first = self._run(
            [
                ScriptedResponse(json=_page(["waitlist_a", "waitlist_b"], after=None)),
                ScriptedResponse(json=_page(["wl_user_1"], after=None)),
                ScriptedResponse(json=_page(["wl_user_2"], after="wl_user_2")),
                ScriptedResponse(status=500, json={"message": "boom"}),
            ]
            + [ScriptedResponse(status=500, json={"message": "boom"})] * 10
        )
        assert first.raised is not None
        assert first.final_state is not None

        resumed = self._run(
            [
                ScriptedResponse(json=_page(["waitlist_a", "waitlist_b"], after=None)),
                ScriptedResponse(json=_page(["wl_user_3"], after=None)),
            ],
            resume_state=first.final_state,
        )

        assert resumed.paths == ["/user_management/waitlists", "/user_management/waitlists/waitlist_b/entries"]
        assert resumed.params("after") == [None, "wl_user_2"]
        assert [row["id"] for row in resumed.rows] == ["wl_user_3"]


class TestWorkOSValidateCredentials:
    @pytest.mark.parametrize(
        ("status_code", "body", "expected_valid"),
        [
            (200, {"data": [], "list_metadata": {}}, True),
            # A valid key lacking the Organizations scope still proves authenticity at source-create.
            (403, {"message": "forbidden"}, True),
            (401, {"message": "unauthorized"}, False),
            (500, {"message": "server error"}, False),
        ],
    )
    def test_validate_credentials(self, status_code: int, body: Any, expected_valid: bool) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code, json=body))):
            is_valid, _ = validate_credentials("sk_test_123")
            assert is_valid is expected_valid

    def test_resume_config_serialization_round_trip(self) -> None:
        cfg = WorkOSResumeConfig(after="org_1500")
        reconstituted = WorkOSResumeConfig(**json.loads(json.dumps(dataclasses.asdict(cfg))))
        assert reconstituted == cfg


WEBHOOK_URL = "https://webhooks.us.posthog.com/public/webhooks/dwh/hog_1"


def _webhook_page(webhooks: list[dict[str, Any]], after: str | None) -> ScriptedResponse:
    return ScriptedResponse(
        json={"object": "list", "data": webhooks, "list_metadata": {"before": None, "after": after}}
    )


class TestWorkOSWebhookManagement:
    def test_lookup_pages_past_the_first_page(self) -> None:
        # WorkOS lists 10 endpoints per page by default, so an account with more than that would
        # report ours as missing — prompting a duplicate create, and a delete that removes nothing.
        script = [
            _webhook_page([{"id": "we_1", "endpoint_url": "https://other.example"}], after="we_1"),
            _webhook_page(
                [{"id": "we_2", "endpoint_url": WEBHOOK_URL, "events": ["user.created"], "status": "enabled"}],
                after=None,
            ),
        ]
        with scripted_network(script) as network:
            info = get_webhook_info("sk_test_123", WEBHOOK_URL)

        assert info.exists is True
        assert info.enabled_events == ["user.created"]
        assert [r.param("limit") for r in network.requests_log] == ["100", "100"]
        assert [r.param("after") for r in network.requests_log] == [None, "we_1"]

    def test_lookup_reports_absence(self) -> None:
        with scripted_network([_webhook_page([], after=None)]):
            assert get_webhook_info("sk_test_123", WEBHOOK_URL).exists is False

    def test_create_persists_the_one_time_secret(self) -> None:
        with scripted_network([ScriptedResponse(json={"id": "we_1", "secret": "whsec_abc"})]) as network:
            result = create_webhook("sk_test_123", WEBHOOK_URL, ["user.created"])

        assert result.success is True
        assert result.extra_inputs == {"signing_secret": "whsec_abc"}
        assert network.requests_log[0].json() == {
            "endpoint_url": WEBHOOK_URL,
            "events": ["user.created"],
        }

    def test_create_without_a_secret_asks_for_manual_entry(self) -> None:
        # Without the secret the hog function rejects every delivery, so success would be a lie.
        with scripted_network([ScriptedResponse(json={"id": "we_1"})]):
            result = create_webhook("sk_test_123", WEBHOOK_URL, ["user.created"])

        assert result.success is False
        assert result.pending_inputs == ["signing_secret"]

    def test_create_failure_is_reported_not_raised(self) -> None:
        with scripted_network(always(ConnectionError("boom"))):
            assert create_webhook("sk_test_123", WEBHOOK_URL, ["user.created"]).success is False

    def test_sync_merges_missing_events_and_keeps_manual_ones(self) -> None:
        script = [
            _webhook_page(
                [{"id": "we_2", "endpoint_url": WEBHOOK_URL, "events": ["user.created", "invoice.paid"]}], after=None
            ),
            ScriptedResponse(json={}),
        ]
        with scripted_network(script) as network:
            result = sync_webhook_events("sk_test_123", WEBHOOK_URL, ["user.created", "user.deleted"])

        assert result.success is True
        patch_request = network.requests_log[1]
        assert patch_request.method == "PATCH"
        assert patch_request.path.endswith("/webhook_endpoints/we_2")
        assert patch_request.json() == {"events": ["invoice.paid", "user.created", "user.deleted"]}

    def test_sync_skips_the_write_when_events_already_match(self) -> None:
        script = [_webhook_page([{"id": "we_2", "endpoint_url": WEBHOOK_URL, "events": ["user.created"]}], after=None)]
        with scripted_network(script) as network:
            assert sync_webhook_events("sk_test_123", WEBHOOK_URL, ["user.created"]).success is True

        assert [r.method for r in network.requests_log] == ["GET"]

    def test_delete_removes_only_the_matching_endpoint(self) -> None:
        script = [
            _webhook_page(
                [
                    {"id": "we_1", "endpoint_url": "https://other.example"},
                    {"id": "we_2", "endpoint_url": WEBHOOK_URL},
                ],
                after=None,
            ),
            ScriptedResponse(json={}),
        ]
        with scripted_network(script) as network:
            result = delete_webhook("sk_test_123", WEBHOOK_URL)

        assert result.success is True
        deletes: list[RecordedRequest] = [r for r in network.requests_log if r.method == "DELETE"]
        assert [r.url for r in deletes] == ["https://api.workos.com/webhook_endpoints/we_2"]

    def test_delete_surfaces_a_rejected_removal(self) -> None:
        script = [
            _webhook_page([{"id": "we_2", "endpoint_url": WEBHOOK_URL}], after=None),
            ScriptedResponse(status=403, json={"message": "forbidden"}),
        ]
        with scripted_network(script):
            assert delete_webhook("sk_test_123", WEBHOOK_URL).success is False
