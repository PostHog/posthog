import json
import dataclasses
from collections.abc import Iterable
from typing import Any, cast

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.webhook_s3 import WebhookSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.workos.settings import ENDPOINTS, WORKOS_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.workos.workos import (
    WorkOSPaginator,
    WorkOSResumeConfig,
    create_webhook,
    delete_webhook,
    get_webhook_info,
    sync_webhook_events,
    validate_credentials,
    workos_source,
)

WORKOS_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.workos.workos.make_tracked_session"
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


def _make_http_response(body: Any, status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    resp.headers["Content-Type"] = "application/json"
    return resp


def _page(ids: list[str], after: str | None) -> dict[str, Any]:
    return {"data": [{"id": i} for i in ids], "list_metadata": {"before": None, "after": after}}


def _webhook_manager(enabled: bool) -> MagicMock:
    manager = MagicMock(spec=WebhookSourceManager)
    manager.webhook_enabled = AsyncMock(return_value=enabled)
    return manager


class TestWorkOSEndpoints:
    def test_all_endpoints_registered(self) -> None:
        assert set(ENDPOINTS) == set(WORKOS_ENDPOINTS)
        # Every endpoint partitions on the immutable created_at field.
        assert all(cfg.partition_key == "created_at" for cfg in WORKOS_ENDPOINTS.values())


class TestWorkOSSourceResumeBehavior:
    """End-to-end resume behaviour through the shared ``rest_api_resource`` path."""

    def _drive(
        self, manager: MagicMock, responses: list[Response], endpoint: str = "organizations"
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        sent_params: list[dict[str, Any]] = []
        response_iter = iter(responses)

        def fake_send(request: Any, *_args: Any, **_kwargs: Any) -> Response:
            sent_params.append(dict(request.params))
            return next(response_iter)

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
        ) as MockSession:
            mock_session = MockSession.return_value
            mock_session.headers = {}
            mock_session.prepare_request.side_effect = lambda req: req
            mock_session.send.side_effect = fake_send

            source_response = workos_source(
                api_key="sk_test_123",
                endpoint=endpoint,
                team_id=123,
                job_id="job_1",
                resumable_source_manager=manager,
                webhook_source_manager=_webhook_manager(enabled=False),
            )
            pages = list(cast(Iterable[Any], source_response.items()))
            return sent_params, [row for page in pages for row in page]

    def test_fresh_run_saves_cursor_after_each_non_terminal_page(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [
            _make_http_response(_page(["org_1", "org_2"], after="org_2")),
            _make_http_response(_page(["org_3", "org_4"], after="org_4")),
            _make_http_response(_page(["org_5"], after=None)),
        ]
        sent_params, _ = self._drive(manager, responses)

        # First request omits the cursor (fresh run); subsequent requests carry it.
        assert [p.get("after") for p in sent_params] == [None, "org_2", "org_4"]

        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [WorkOSResumeConfig(after="org_2"), WorkOSResumeConfig(after="org_4")]

    def test_resume_seeds_paginator_with_saved_cursor(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        manager.load_state.return_value = WorkOSResumeConfig(after="org_4")

        responses = [
            _make_http_response(_page(["org_5"], after=None)),
        ]
        sent_params, _ = self._drive(manager, responses)

        # First request goes out at the resumed cursor, so synced pages are not re-fetched.
        assert [p.get("after") for p in sent_params] == ["org_4"]


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
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.workos.workos.make_tracked_session"
        ) as MockSession:
            MockSession.return_value.get.return_value = _make_http_response(body, status_code=status_code)
            is_valid, _ = validate_credentials("sk_test_123")
            assert is_valid is expected_valid

    def test_resume_config_serialization_round_trip(self) -> None:
        cfg = WorkOSResumeConfig(after="org_1500")
        reconstituted = WorkOSResumeConfig(**json.loads(json.dumps(dataclasses.asdict(cfg))))
        assert reconstituted == cfg


WEBHOOK_URL = "https://webhooks.us.posthog.com/public/webhooks/dwh/hog_1"


def _webhook_page(webhooks: list[dict[str, Any]], after: str | None) -> Response:
    return _make_http_response({"object": "list", "data": webhooks, "list_metadata": {"before": None, "after": after}})


class TestWorkOSWebhookManagement:
    @patch(WORKOS_SESSION_PATCH)
    def test_lookup_pages_past_the_first_page(self, MockSession: MagicMock) -> None:
        # WorkOS lists 10 endpoints per page by default, so an account with more than that would
        # report ours as missing — prompting a duplicate create, and a delete that removes nothing.
        session = MockSession.return_value
        session.get.side_effect = [
            _webhook_page([{"id": "we_1", "endpoint_url": "https://other.example"}], after="we_1"),
            _webhook_page(
                [{"id": "we_2", "endpoint_url": WEBHOOK_URL, "events": ["user.created"], "status": "enabled"}],
                after=None,
            ),
        ]

        info = get_webhook_info("sk_test_123", WEBHOOK_URL)

        assert info.exists is True
        assert info.enabled_events == ["user.created"]
        assert session.get.call_args_list[0].kwargs["params"] == {"limit": 100}
        assert session.get.call_args_list[1].kwargs["params"] == {"limit": 100, "after": "we_1"}

    @patch(WORKOS_SESSION_PATCH)
    def test_lookup_reports_absence(self, MockSession: MagicMock) -> None:
        MockSession.return_value.get.return_value = _webhook_page([], after=None)
        assert get_webhook_info("sk_test_123", WEBHOOK_URL).exists is False

    @patch(WORKOS_SESSION_PATCH)
    def test_create_persists_the_one_time_secret(self, MockSession: MagicMock) -> None:
        MockSession.return_value.post.return_value = _make_http_response({"id": "we_1", "secret": "whsec_abc"})

        result = create_webhook("sk_test_123", WEBHOOK_URL, ["user.created"])

        assert result.success is True
        assert result.extra_inputs == {"signing_secret": "whsec_abc"}
        assert MockSession.return_value.post.call_args.kwargs["json"] == {
            "endpoint_url": WEBHOOK_URL,
            "events": ["user.created"],
        }

    @patch(WORKOS_SESSION_PATCH)
    def test_create_without_a_secret_asks_for_manual_entry(self, MockSession: MagicMock) -> None:
        # Without the secret the hog function rejects every delivery, so success would be a lie.
        MockSession.return_value.post.return_value = _make_http_response({"id": "we_1"})

        result = create_webhook("sk_test_123", WEBHOOK_URL, ["user.created"])

        assert result.success is False
        assert result.pending_inputs == ["signing_secret"]

    @patch(WORKOS_SESSION_PATCH)
    def test_create_failure_is_reported_not_raised(self, MockSession: MagicMock) -> None:
        MockSession.return_value.post.side_effect = Exception("boom")
        assert create_webhook("sk_test_123", WEBHOOK_URL, ["user.created"]).success is False

    @patch(WORKOS_SESSION_PATCH)
    def test_sync_merges_missing_events_and_keeps_manual_ones(self, MockSession: MagicMock) -> None:
        session = MockSession.return_value
        session.get.return_value = _webhook_page(
            [{"id": "we_2", "endpoint_url": WEBHOOK_URL, "events": ["user.created", "invoice.paid"]}], after=None
        )
        session.patch.return_value = _make_http_response({})

        result = sync_webhook_events("sk_test_123", WEBHOOK_URL, ["user.created", "user.deleted"])

        assert result.success is True
        assert session.patch.call_args.args[0].endswith("/webhook_endpoints/we_2")
        assert session.patch.call_args.kwargs["json"] == {"events": ["invoice.paid", "user.created", "user.deleted"]}

    @patch(WORKOS_SESSION_PATCH)
    def test_sync_skips_the_write_when_events_already_match(self, MockSession: MagicMock) -> None:
        session = MockSession.return_value
        session.get.return_value = _webhook_page(
            [{"id": "we_2", "endpoint_url": WEBHOOK_URL, "events": ["user.created"]}], after=None
        )

        assert sync_webhook_events("sk_test_123", WEBHOOK_URL, ["user.created"]).success is True
        session.patch.assert_not_called()

    @patch(WORKOS_SESSION_PATCH)
    def test_delete_removes_only_the_matching_endpoint(self, MockSession: MagicMock) -> None:
        session = MockSession.return_value
        session.get.return_value = _webhook_page(
            [
                {"id": "we_1", "endpoint_url": "https://other.example"},
                {"id": "we_2", "endpoint_url": WEBHOOK_URL},
            ],
            after=None,
        )
        session.delete.return_value = _make_http_response({})

        result = delete_webhook("sk_test_123", WEBHOOK_URL)

        assert result.success is True
        assert [call.args[0] for call in session.delete.call_args_list] == [
            "https://api.workos.com/webhook_endpoints/we_2"
        ]

    @patch(WORKOS_SESSION_PATCH)
    def test_delete_surfaces_a_rejected_removal(self, MockSession: MagicMock) -> None:
        session = MockSession.return_value
        session.get.return_value = _webhook_page([{"id": "we_2", "endpoint_url": WEBHOOK_URL}], after=None)
        session.delete.return_value = _make_http_response({"message": "forbidden"}, status_code=403)

        assert delete_webhook("sk_test_123", WEBHOOK_URL).success is False
