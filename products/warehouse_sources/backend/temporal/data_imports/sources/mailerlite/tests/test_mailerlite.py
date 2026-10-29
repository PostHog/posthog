from typing import Any

import pytest
from unittest.mock import MagicMock

from requests.exceptions import ChunkedEncodingError, HTTPError

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.arrow_utils import table_from_py_list
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.webhook_s3 import WebhookSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.mailerlite import (
    MailerLiteSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mailerlite.mailerlite import (
    INVALID_KEY_ERROR,
    MAILERLITE_BASE_URL,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.mailerlite.source import MailerLiteSource


def _make_manager(resume: MailerLiteResumeConfig | None = None) -> MagicMock:
    manager = MagicMock(spec=ResumableSourceManager)
    manager.can_resume.return_value = resume is not None
    manager.load_state.return_value = resume
    return manager


def _driver() -> SourceDriver:
    return SourceDriver(MailerLiteSource(), MailerLiteSourceConfig(api_key="test-key"))


def _page(items: list[dict[str, Any]], next_url: str | None) -> ScriptedResponse:
    return ScriptedResponse(json={"data": items, "links": {"next": next_url}, "meta": {}})


class TestPagination:
    def test_follows_links_next_across_pages(self) -> None:
        next_url = f"{MAILERLITE_BASE_URL}/subscribers?cursor=abc&limit=100"
        result = _driver().run("subscribers", [_page([{"id": "1"}], next_url), _page([{"id": "2"}], None)])

        assert result.raised is None
        assert result.items == [[{"id": "1"}], [{"id": "2"}]]
        assert result.urls[0] == f"{MAILERLITE_BASE_URL}/subscribers?limit=100"
        assert result.urls[1] == next_url

    def test_starts_unresumed_when_there_is_no_saved_state(self) -> None:
        result = _driver().run("subscribers", [_page([{"id": "1"}], None)])

        assert result.raised is None
        assert result.urls == [f"{MAILERLITE_BASE_URL}/subscribers?limit=100"]

    def test_non_retryable_status_raises(self) -> None:
        result = _driver().run("groups", [ScriptedResponse(status=404, json={"message": "Not Found"})])

        assert isinstance(result.raised, HTTPError)
        assert result.paths == ["/api/groups"]

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
        result = _driver().run("subscribers", [_page([{"id": "1"}], off_host_url)])

        assert result.raised is None
        assert result.items == [[{"id": "1"}]]
        assert result.urls == [f"{MAILERLITE_BASE_URL}/subscribers?limit=100"]
        assert result.saved_states == []

    def test_off_host_resume_url_raises(self) -> None:
        # A seeded resume URL pointing off-host is rejected by the client's allowed_hosts guard
        # before the authenticated request leaves the process.
        result = _driver().run(
            "subscribers",
            [],
            resume_state=MailerLiteResumeConfig(next_url="http://169.254.169.254/latest/meta-data/"),
        )

        assert isinstance(result.raised, ValueError)
        assert "disallowed host" in str(result.raised)
        assert result.requests == []


class TestFanout:
    @pytest.mark.parametrize(
        ("endpoint", "parent_path", "child_path", "parent_key", "expected_parent_query", "expected_child_query"),
        [
            (
                "campaign_subscriber_activity",
                "/campaigns",
                "/campaigns/c1/reports/subscriber-activity",
                "campaign_id",
                {"limit": ["100"], "filter[status]": ["sent"]},
                {"limit": ["100"], "include": ["subscriber"]},
            ),
            (
                "group_subscribers",
                "/groups",
                "/groups/c1/subscribers",
                "group_id",
                {"limit": ["100"]},
                {"limit": ["100"]},
            ),
            (
                "segment_subscribers",
                "/segments",
                "/segments/c1/subscribers",
                "segment_id",
                {"limit": ["100"]},
                {"limit": ["100"]},
            ),
            (
                "ecommerce_orders",
                "/ecommerce/shops",
                "/ecommerce/shops/c1/orders",
                "shop_id",
                {"limit": ["50"]},
                {"limit": ["100"]},
            ),
        ],
    )
    def test_walks_every_child_page_and_tags_rows_with_the_parent(
        self,
        endpoint: str,
        parent_path: str,
        child_path: str,
        parent_key: str,
        expected_parent_query: dict[str, list[str]],
        expected_child_query: dict[str, list[str]],
    ) -> None:
        child_next = f"{MAILERLITE_BASE_URL}{child_path}?cursor=abc"

        result = _driver().run(
            endpoint,
            [
                _page([{"id": "c1"}], None),
                _page([{"id": "a1"}], child_next),
                _page([{"id": "a2"}], None),
            ],
        )

        assert result.raised is None
        assert result.rows == [
            {"id": "a1", parent_key: "c1"},
            {"id": "a2", parent_key: "c1"},
        ]
        assert result.paths[:2] == [f"/api{parent_path}", f"/api{child_path}"]
        assert dict(result.requests[0].query) == {name: tuple(values) for name, values in expected_parent_query.items()}
        assert dict(result.requests[1].query) == {name: tuple(values) for name, values in expected_child_query.items()}
        assert result.requests[2].url == child_next

    def test_automation_activity_requests_each_status(self) -> None:
        # One page per status for the single automation, each answering one activity row.
        statuses = ("active", "completed", "canceled", "failed")
        result = _driver().run(
            "automation_activity",
            [_page([{"id": "au1"}], None)]
            + [_page([{"id": f"run-{status}", "status": status.title()}], None) for status in statuses],
        )

        assert result.raised is None
        assert result.paths[1:] == ["/api/automations/au1/activity"] * 4
        assert result.params("filter[status]")[1:] == list(statuses)
        assert {row["automation_id"] for row in result.rows} == {"au1"}
        assert "activity_status" not in result.rows[0]

    def test_automation_activity_pagination_carries_filter_status(self) -> None:
        # MailerLite's own `links.next` for this endpoint drops the required `filter[status]`
        # on page 2+ (it only carries `page`); the paginator must re-attach it from page 1's
        # request or the next request 422s.
        child_next = f"{MAILERLITE_BASE_URL}/automations/au1/activity?page=2"
        result = _driver().run(
            "automation_activity",
            [_page([{"id": "au1"}], None)]
            + [_page([{"id": "run-active-1"}], child_next), _page([{"id": "run-active-2"}], None)]
            + [_page([{"id": f"run-{status}"}], None) for status in ("completed", "canceled", "failed")],
        )

        assert result.raised is None
        assert result.params("filter[status]")[1:3] == ["active", "active"]
        assert result.params("page")[2] == "2"
        assert {row["id"] for row in result.rows} >= {"run-active-1", "run-active-2"}

    def test_resume_skips_completed_parents(self) -> None:
        result = _driver().run(
            "group_subscribers",
            [_page([{"id": "g1"}, {"id": "g2"}], None), _page([{"id": "s1"}], None)],
            resume_state=MailerLiteResumeConfig(completed=["/groups/g1/subscribers"]),
        )

        assert result.raised is None
        assert result.paths == ["/api/groups", "/api/groups/g2/subscribers"]
        assert result.rows == [{"id": "s1", "group_id": "g2"}]
        assert result.saved_states[-1].completed == ["/groups/g1/subscribers", "/groups/g2/subscribers"]


class TestRetry:
    def test_chunked_encoding_error_eventually_reraises(self) -> None:
        result = _driver().run("subscribers", always(ChunkedEncodingError("Connection broken")))

        assert isinstance(result.raised, RESTClientRetryableError)
        assert set(result.paths) == {"/api/subscribers"}
        assert len(result.requests) == 5


class TestApiVersionHeader:
    def test_v2_pins_version_header(self) -> None:
        result = SourceDriver(MailerLiteSource(), MailerLiteSourceConfig(api_key="test-key")).run(
            "subscribers",
            [ScriptedResponse(json={"data": [{"id": "1"}], "links": {"next": None}})],
            api_version=MAILERLITE_V2,
        )

        assert result.raised is None
        assert result.requests[0].headers["x-version"] == "2038-01-19"


class TestValidateCredentials:
    @pytest.mark.parametrize(
        ("status_code", "expected_ok", "expected_error"),
        [
            (400, False, INVALID_KEY_ERROR),
            (429, False, UNVERIFIED_KEY_ERROR),
        ],
    )
    def test_status_maps_to_message(self, status_code: int, expected_ok: bool, expected_error: str | None) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code, json={}))) as network:
            assert validate_credentials("key") == (expected_ok, expected_error)
        assert {request.path for request in network.requests_log} == {"/api/subscribers"}
        assert network.requests_log[0].param("limit") == "1"


WEBHOOK_URL = "https://ph.example/public/webhooks/abc"


def _webhook_list(items: list[dict[str, Any]], next_url: str | None = None) -> ScriptedResponse:
    return ScriptedResponse(json={"data": items, "links": {"next": next_url}, "meta": {}})


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
        with scripted_network([ScriptedResponse(status=status_code, json=body)]) as network:
            result = create_webhook("key", WEBHOOK_URL)

        assert result.success is expected_success
        assert result.extra_inputs == expected_extra
        assert result.pending_inputs == expected_pending
        assert [(request.method, request.path) for request in network.requests_log] == [("POST", "/api/webhooks")]

    def test_transport_failure_reports_manual_setup(self) -> None:
        with scripted_network([ConnectionError("boom")]):
            result = create_webhook("key", WEBHOOK_URL)

        assert result.success is False
        assert result.error is not None and "manually" in result.error


class TestDeleteWebhook:
    def test_deletes_only_webhooks_pointing_at_our_url(self) -> None:
        with scripted_network(
            [
                _webhook_list([{"id": "1", "url": WEBHOOK_URL}, {"id": "2", "url": "https://other.example/hook"}]),
                ScriptedResponse(status=204),
            ]
        ) as network:
            result = delete_webhook("key", WEBHOOK_URL)

        assert result.success is True
        assert [(request.method, request.url) for request in network.requests_log if request.method == "DELETE"] == [
            ("DELETE", f"{MAILERLITE_BASE_URL}/webhooks/1")
        ]

    def test_failed_delete_is_reported(self) -> None:
        with scripted_network(
            [_webhook_list([{"id": "1", "url": WEBHOOK_URL}]), ScriptedResponse(status=500, json={})]
        ):
            result = delete_webhook("key", WEBHOOK_URL)

        assert result.success is False
        assert result.error is not None and "500" in result.error


class TestGetExternalWebhookInfo:
    def test_missing_webhook_reports_not_exists(self) -> None:
        with scripted_network([_webhook_list([])]):
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
        with scripted_network([_webhook_list([{"id": "2", "url": "https://other.example"}], off_host_url)]) as network:
            info = get_external_webhook_info("key", WEBHOOK_URL)

        assert info.exists is False
        assert info.error is not None and "Refusing to follow" in info.error
        assert [(request.method, request.path) for request in network.requests_log] == [("GET", "/api/webhooks")]

    def test_on_host_next_link_is_followed(self) -> None:
        next_url = f"{MAILERLITE_BASE_URL}/webhooks?page=2&limit=100"
        with scripted_network(
            [
                _webhook_list([{"id": "2", "url": "https://other.example"}], next_url),
                _webhook_list([{"id": "1", "url": WEBHOOK_URL, "events": [], "enabled": True}]),
            ]
        ) as network:
            info = get_external_webhook_info("key", WEBHOOK_URL)

        assert info.exists is True
        assert network.requests_log[1].url == next_url


class TestSyncWebhookEvents:
    def test_missing_events_are_merged_in(self) -> None:
        with scripted_network(
            [
                _webhook_list([{"id": "1", "url": WEBHOOK_URL, "events": ["subscriber.created", "campaign.sent"]}]),
                ScriptedResponse(status=200, json={}),
            ]
        ) as network:
            result = sync_webhook_events("key", WEBHOOK_URL, ["subscriber.created", "subscriber.bounced"])

        assert result.success is True
        # Existing events are kept so a manually broadened webhook isn't narrowed behind the user's back.
        assert network.requests_log[1].json() == {
            "events": ["campaign.sent", "subscriber.bounced", "subscriber.created"]
        }
        assert (network.requests_log[1].method, network.requests_log[1].path) == ("PUT", "/api/webhooks/1")

    def test_already_covered_events_skip_the_write(self) -> None:
        with scripted_network(
            [_webhook_list([{"id": "1", "url": WEBHOOK_URL, "events": ["subscriber.created", "subscriber.bounced"]}])]
        ) as network:
            result = sync_webhook_events("key", WEBHOOK_URL, ["subscriber.created"])

        assert result.success is True
        assert [request.method for request in network.requests_log] == ["GET"]


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
        result = SourceDriver(MailerLiteSource(), MailerLiteSourceConfig(api_key="key")).run(
            endpoint,
            [ScriptedResponse(json={"data": [{"id": "1"}], "links": {"next": None}, "meta": {}})],
        )

        assert result.raised is None
        assert result.rows == [{"id": "1"}]
        assert result.paths == [f"/api/{endpoint}"]
