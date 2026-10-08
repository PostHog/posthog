import json
from collections.abc import Iterable
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

from requests import Response
from requests.exceptions import ChunkedEncodingError, HTTPError

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.arrow_utils import table_from_py_list
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.webhook_s3 import WebhookSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.mailerlite.mailerlite import (
    INVALID_KEY_ERROR,
    MAILERLITE_BASE_URL,
    MISSING_PERMISSION_ERROR,
    UNVERIFIED_KEY_ERROR,
    MailerLiteResumeConfig,
    _webhook_table_transformer,
    create_webhook,
    delete_webhook,
    get_external_webhook_info,
    mailerlite_source,
    sync_webhook_events,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mailerlite.settings import MAILERLITE_V2

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the mailerlite module.
MAILERLITE_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.mailerlite.mailerlite.make_tracked_session"
)


def _make_response(body: dict[str, Any], status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    resp.headers["Content-Type"] = "application/json"
    return resp


def _page(items: list[dict[str, Any]], next_url: str | None) -> Response:
    return _make_response({"data": items, "links": {"next": next_url}, "meta": {}})


def _make_manager(resume: MailerLiteResumeConfig | None = None) -> MagicMock:
    manager = MagicMock(spec=ResumableSourceManager)
    manager.can_resume.return_value = resume is not None
    manager.load_state.return_value = resume
    return manager


def _wire(session: MagicMock, responses: Any) -> list[str]:
    """Wire a mock session and return the URLs each request is actually sent to.

    ``_check_allowed_host`` reads ``prepared.url``, so prepare_request must return a real
    ``PreparedRequest`` whose URL reflects the request's URL + params for that page. The
    next-page URL is followed with an empty params dict, so its ``prepared.url`` echoes the
    absolute ``links.next`` exactly.
    """
    session.headers = {}
    sent_urls: list[str] = []

    def _prepare(request: Any) -> Any:
        prepared = request.prepare()
        sent_urls.append(prepared.url)
        return prepared

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return sent_urls


def _run(endpoint: str, manager: MagicMock, responses: Any) -> tuple[list[list[dict[str, Any]]], list[str], MagicMock]:
    with patch(CLIENT_SESSION_PATCH) as MockSession:
        session = MockSession.return_value
        sent_urls = _wire(session, responses)
        source = mailerlite_source(
            api_key="test-key", endpoint=endpoint, team_id=1, job_id="j", resumable_source_manager=manager
        )
        batches = list(cast("Iterable[Any]", source.items()))
    return batches, sent_urls, session


class TestPagination:
    def test_follows_links_next_across_pages(self) -> None:
        next_url = f"{MAILERLITE_BASE_URL}/subscribers?cursor=abc&limit=100"
        responses = [_page([{"id": "1"}], next_url), _page([{"id": "2"}], None)]

        batches, sent_urls, _ = _run("subscribers", _make_manager(), responses)

        assert batches == [[{"id": "1"}], [{"id": "2"}]]
        assert sent_urls[0] == f"{MAILERLITE_BASE_URL}/subscribers?limit=100"
        assert sent_urls[1] == next_url

    def test_does_not_load_state_when_cannot_resume(self) -> None:
        manager = _make_manager()

        _run("subscribers", manager, [_page([{"id": "1"}], None)])

        manager.load_state.assert_not_called()

    def test_non_retryable_status_raises(self) -> None:
        with pytest.raises(HTTPError):
            _run("groups", _make_manager(), [_make_response({"message": "Not Found"}, status_code=404)])

    @pytest.mark.parametrize(
        "off_host_url",
        [
            "http://169.254.169.254/latest/meta-data/",
            "https://evil.example.com/api/subscribers?cursor=abc",
            "https://connect.mailerlite.com.evil.com/api/subscribers",
        ],
    )
    def test_off_host_next_url_is_ignored(self, off_host_url: str) -> None:
        # The custom paginator drops a tampered off-host ``next`` link, so we yield the first page
        # and stop without ever issuing (or checkpointing) the off-host request.
        manager = _make_manager()

        batches, sent_urls, _ = _run("subscribers", manager, [_page([{"id": "1"}], off_host_url)])

        assert batches == [[{"id": "1"}]]
        assert sent_urls == [f"{MAILERLITE_BASE_URL}/subscribers?limit=100"]
        manager.save_state.assert_not_called()

    def test_off_host_resume_url_raises(self) -> None:
        # A seeded resume URL pointing off-host is rejected by the client's allowed_hosts guard
        # before the authenticated request leaves the process.
        manager = _make_manager(MailerLiteResumeConfig(next_url="http://169.254.169.254/latest/meta-data/"))

        with pytest.raises(ValueError, match="disallowed host"):
            _run("subscribers", manager, [])


class TestRetry:
    def test_chunked_encoding_error_eventually_reraises(self) -> None:
        manager = _make_manager()

        with patch(CLIENT_SESSION_PATCH) as MockSession, patch("tenacity.nap.time.sleep"):
            session = MockSession.return_value
            _wire(session, ChunkedEncodingError("Connection broken"))
            source = mailerlite_source(
                api_key="test-key", endpoint="subscribers", team_id=1, job_id="j", resumable_source_manager=manager
            )
            with pytest.raises(RESTClientRetryableError):
                list(cast("Iterable[Any]", source.items()))

        assert session.send.call_count == 5


class TestApiVersionHeader:
    def _headers_for(self, endpoint: str, manager: MagicMock, **source_kwargs: Any) -> dict[str, str]:
        """Return the session headers mailerlite_source pins for a run.

        The REST client merges its configured headers onto the session (``session.headers``),
        so the ``X-Version`` pin lands there rather than on each individual request.
        """
        with patch(CLIENT_SESSION_PATCH) as MockSession:
            session = MockSession.return_value
            _wire(session, [_page([{"id": "1"}], None)])
            source = mailerlite_source(
                api_key="test-key",
                endpoint=endpoint,
                team_id=1,
                job_id="j",
                resumable_source_manager=manager,
                **source_kwargs,
            )
            list(cast("Iterable[Any]", source.items()))
        return session.headers

    def test_v2_pins_version_header(self) -> None:
        headers = self._headers_for("subscribers", _make_manager(), api_version=MAILERLITE_V2)
        assert headers["X-Version"] == "2038-01-19"


class TestValidateCredentials:
    @pytest.mark.parametrize(
        ("status_code", "expected_ok", "expected_error"),
        [
            (200, True, None),
            (401, False, INVALID_KEY_ERROR),
            (400, False, INVALID_KEY_ERROR),
            (403, False, MISSING_PERMISSION_ERROR),
            (429, False, UNVERIFIED_KEY_ERROR),
            (500, False, UNVERIFIED_KEY_ERROR),
        ],
    )
    def test_status_maps_to_message(self, status_code: int, expected_ok: bool, expected_error: str | None) -> None:
        with patch(MAILERLITE_SESSION_PATCH) as MockSession:
            MockSession.return_value.get.return_value = _make_response({}, status_code=status_code)
            assert validate_credentials("key") == (expected_ok, expected_error)


WEBHOOK_URL = "https://ph.example/public/webhooks/abc"


def _webhook_list(items: list[dict[str, Any]], next_url: str | None = None) -> Response:
    return _make_response({"data": items, "links": {"next": next_url}, "meta": {}})


def _subscriber(subscriber_id: str, updated_at: str, **overrides: Any) -> dict[str, Any]:
    return {
        "id": subscriber_id,
        "email": f"{subscriber_id}@example.com",
        "status": "active",
        "created_at": "2024-05-08T08:26:04.000000Z",
        "updated_at": updated_at,
        **overrides,
    }


class TestCreateWebhook:
    @pytest.mark.parametrize(
        ("status_code", "body", "expected_success", "expected_extra", "expected_pending"),
        [
            (201, {"data": {"id": "1", "secret": "s3cr3t"}}, True, {"signing_secret": "s3cr3t"}, []),
            (200, {"data": {"id": "1", "secret": "s3cr3t"}}, True, {"signing_secret": "s3cr3t"}, []),
            # MailerLite returns the secret exactly once; if it's absent we must ask the user for
            # it rather than leaving a webhook whose deliveries can't be verified.
            (201, {"data": {"id": "1"}}, True, {}, ["signing_secret"]),
            (422, {"message": "invalid"}, False, {}, []),
            (403, {"message": "forbidden"}, False, {}, []),
        ],
    )
    def test_secret_handling_by_response(
        self,
        status_code: int,
        body: dict[str, Any],
        expected_success: bool,
        expected_extra: dict[str, str],
        expected_pending: list[str],
    ) -> None:
        with patch(MAILERLITE_SESSION_PATCH) as MockSession:
            MockSession.return_value.post.return_value = _make_response(body, status_code=status_code)
            result = create_webhook("key", WEBHOOK_URL)

        assert result.success is expected_success
        assert result.extra_inputs == expected_extra
        assert result.pending_inputs == expected_pending

    def test_transport_failure_reports_manual_setup(self) -> None:
        with patch(MAILERLITE_SESSION_PATCH) as MockSession:
            MockSession.return_value.post.side_effect = Exception("boom")
            result = create_webhook("key", WEBHOOK_URL)

        assert result.success is False
        assert result.error is not None and "manually" in result.error


class TestDeleteWebhook:
    def test_deletes_only_webhooks_pointing_at_our_url(self) -> None:
        with patch(MAILERLITE_SESSION_PATCH) as MockSession:
            session = MockSession.return_value
            session.get.return_value = _webhook_list(
                [{"id": "1", "url": WEBHOOK_URL}, {"id": "2", "url": "https://other.example/hook"}]
            )
            session.delete.return_value = _make_response({}, status_code=204)
            result = delete_webhook("key", WEBHOOK_URL)

        assert result.success is True
        assert [call.args[0] for call in session.delete.call_args_list] == [f"{MAILERLITE_BASE_URL}/webhooks/1"]

    def test_failed_delete_is_reported(self) -> None:
        with patch(MAILERLITE_SESSION_PATCH) as MockSession:
            session = MockSession.return_value
            session.get.return_value = _webhook_list([{"id": "1", "url": WEBHOOK_URL}])
            session.delete.return_value = _make_response({}, status_code=500)
            result = delete_webhook("key", WEBHOOK_URL)

        assert result.success is False
        assert result.error is not None and "500" in result.error


class TestGetExternalWebhookInfo:
    def test_missing_webhook_reports_not_exists(self) -> None:
        with patch(MAILERLITE_SESSION_PATCH) as MockSession:
            MockSession.return_value.get.return_value = _webhook_list([])
            info = get_external_webhook_info("key", WEBHOOK_URL)

        assert info.exists is False
        assert info.error is None

    @pytest.mark.parametrize(
        "off_host_url",
        [
            "http://169.254.169.254/latest/meta-data/",
            "https://evil.example.com/api/webhooks",
            "https://connect.mailerlite.com.evil.com/api/webhooks",
            "https://connect.mailerlite.com/oauth/token",
        ],
    )
    def test_off_host_next_link_stops_the_credentialed_walk(self, off_host_url: str) -> None:
        # `links.next` is response-controlled and this session carries the API key, so a poisoned
        # link must never be fetched.
        with patch(MAILERLITE_SESSION_PATCH) as MockSession:
            session = MockSession.return_value
            session.get.return_value = _webhook_list([{"id": "2", "url": "https://other.example"}], off_host_url)
            info = get_external_webhook_info("key", WEBHOOK_URL)

        assert info.exists is False
        assert info.error is not None and "Refusing to follow" in info.error
        assert session.get.call_count == 1

    def test_on_host_next_link_is_followed(self) -> None:
        next_url = f"{MAILERLITE_BASE_URL}/webhooks?page=2&limit=100"
        with patch(MAILERLITE_SESSION_PATCH) as MockSession:
            session = MockSession.return_value
            session.get.side_effect = [
                _webhook_list([{"id": "2", "url": "https://other.example"}], next_url),
                _webhook_list([{"id": "1", "url": WEBHOOK_URL, "events": [], "enabled": True}]),
            ]
            info = get_external_webhook_info("key", WEBHOOK_URL)

        assert info.exists is True
        assert [call.args[0] for call in session.get.call_args_list][1] == next_url


class TestSyncWebhookEvents:
    def test_missing_events_are_merged_in(self) -> None:
        with patch(MAILERLITE_SESSION_PATCH) as MockSession:
            session = MockSession.return_value
            session.get.return_value = _webhook_list(
                [{"id": "1", "url": WEBHOOK_URL, "events": ["subscriber.created", "campaign.sent"]}]
            )
            session.put.return_value = _make_response({}, status_code=200)
            result = sync_webhook_events("key", WEBHOOK_URL, ["subscriber.created", "subscriber.bounced"])

        assert result.success is True
        # Existing events are kept so a manually broadened webhook isn't narrowed behind the user's back.
        assert session.put.call_args.kwargs["json"] == {
            "events": ["campaign.sent", "subscriber.bounced", "subscriber.created"]
        }

    def test_already_covered_events_skip_the_write(self) -> None:
        with patch(MAILERLITE_SESSION_PATCH) as MockSession:
            session = MockSession.return_value
            session.get.return_value = _webhook_list(
                [{"id": "1", "url": WEBHOOK_URL, "events": ["subscriber.created", "subscriber.bounced"]}]
            )
            result = sync_webhook_events("key", WEBHOOK_URL, ["subscriber.created"])

        assert result.success is True
        session.put.assert_not_called()


class TestWebhookTableTransformer:
    def test_nested_group_delivery_unwraps_the_subscriber(self) -> None:
        # subscriber.added_to_group nests the same object one level down; without unwrapping it the
        # row has no id and the delivery is silently dropped.
        payload = {
            "type": "subscriber.added_to_group",
            "subscriber": _subscriber("1", "2024-05-28T10:30:29.000000Z"),
            "group": {"id": "9", "name": "Newsletter"},
            "account_id": 7,
        }

        rows = _webhook_table_transformer(table_from_py_list([payload])).to_pylist()

        assert rows == [_subscriber("1", "2024-05-28T10:30:29.000000Z")]

    def test_delivery_without_an_id_is_dropped(self) -> None:
        payloads = [
            {"event": "subscriber.created", "account_id": 7, "email": "no-id@example.com"},
            {**_subscriber("1", "2024-05-28T10:30:29.000000Z"), "event": "subscriber.created"},
        ]

        rows = _webhook_table_transformer(table_from_py_list(payloads)).to_pylist()

        assert [row["id"] for row in rows] == ["1"]


class TestWebhookSourceWiring:
    def _manager(self, enabled: bool) -> MagicMock:
        manager = MagicMock(spec=WebhookSourceManager)

        async def _webhook_enabled(webhook_only: bool = False) -> bool:
            return enabled

        manager.webhook_enabled.side_effect = _webhook_enabled
        manager.get_items.return_value = "webhook-items"
        return manager

    def test_enabled_webhook_replaces_the_poll_for_that_sync(self) -> None:
        webhook_manager = self._manager(enabled=True)

        response = mailerlite_source(
            api_key="key",
            endpoint="subscribers",
            team_id=1,
            job_id="j",
            resumable_source_manager=_make_manager(),
            webhook_source_manager=webhook_manager,
        )

        assert response.items() == "webhook-items"
        # Without the dedup transformer a batch can seed duplicate rows for one subscriber.
        assert webhook_manager.get_items.call_args.kwargs["table_transformer"] is not None

    @pytest.mark.parametrize("endpoint", ["campaigns", "groups", "fields"])
    def test_non_webhook_endpoints_never_consult_the_webhook_manager(self, endpoint: str) -> None:
        # Webhooks are only wired for subscribers; any other table must keep polling in full.
        webhook_manager = self._manager(enabled=True)

        response = mailerlite_source(
            api_key="key",
            endpoint=endpoint,
            team_id=1,
            job_id="j",
            resumable_source_manager=_make_manager(),
            webhook_source_manager=webhook_manager,
        )

        assert response.items() != "webhook-items"
        webhook_manager.webhook_enabled.assert_not_called()
