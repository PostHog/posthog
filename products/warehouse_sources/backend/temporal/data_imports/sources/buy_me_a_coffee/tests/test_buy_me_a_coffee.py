import json
from collections.abc import Iterable
from typing import Any, cast
from urllib.parse import parse_qs, urlsplit

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

import structlog
from parameterized import parameterized
from requests import PreparedRequest, Response
from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.buy_me_a_coffee.buy_me_a_coffee import (
    BuyMeACoffeeResumeConfig,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.buy_me_a_coffee.source import BuyMeACoffeeSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import UnknownResourceError
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.buymeacoffee import (
    BuyMeACoffeeSourceConfig,
)


@override_settings(DATA_WAREHOUSE_REDIS_HOST="localhost", DATA_WAREHOUSE_REDIS_PORT=6379)
class TestBuyMeACoffee(SimpleTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.source = BuyMeACoffeeSource()
        self.config = BuyMeACoffeeSourceConfig(access_token="test-token")
        self.inputs = SourceInputs(
            schema_name="supporters",
            schema_id="test-schema",
            source_id="test-source",
            team_id=1,
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
            db_incremental_field_earliest_value=None,
            incremental_field=None,
            incremental_field_type=None,
            job_id="test-job",
            logger=structlog.get_logger(),
            reset_pipeline=False,
        )
        self.state: dict[str, str] = {}
        redis = MagicMock()
        redis.exists.side_effect = lambda key: int(key in self.state)
        redis.get.side_effect = self.state.get
        redis.set.side_effect = lambda key, value, **kwargs: self.state.update({key: value})
        redis_patcher = patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable.get_client",
            return_value=redis,
        )
        redis_patcher.start()
        self.addCleanup(redis_patcher.stop)
        send_patcher = patch("requests.sessions.Session.send")
        self.send = send_patcher.start()
        self.addCleanup(send_patcher.stop)
        sleep_patcher = patch("tenacity.nap.time.sleep")
        self.sleep = sleep_patcher.start()
        self.addCleanup(sleep_patcher.stop)
        self.requests: list[PreparedRequest] = []

    def respond(self, bodies: list[dict[str, Any]], statuses: list[int] | None = None) -> None:
        responses = iter(zip(statuses or [200] * len(bodies), bodies))

        def send(request: PreparedRequest, **kwargs: Any) -> Response:
            self.requests.append(request)
            status, body = next(responses)
            response = Response()
            response.status_code = status
            response.reason = {
                200: "OK",
                401: "Unauthorized",
                403: "Forbidden",
                429: "Too Many Requests",
                503: "Service Unavailable",
            }.get(status, "Error")
            response._content = json.dumps(body).encode()
            response.headers.update({"Content-Type": "application/json", "Retry-After": "7"})
            assert request.url is not None
            response.url = request.url
            response.request = request
            return response

        self.send.side_effect = send

    @parameterized.expand(
        [
            ("supporters", "support_id", "support_created_on"),
            ("subscriptions", "subscription_id", "subscription_created_on"),
            ("extras", "purchase_id", "purchased_on"),
        ]
    )
    def test_full_refresh_walks_every_page_and_preserves_rows(
        self, endpoint: str, primary_key: str, created_field: str
    ) -> None:
        self.inputs.schema_name = endpoint
        self.inputs.db_incremental_field_last_value = "2099-01-01 00:00:00"
        rows = [
            {
                primary_key: 102,
                created_field: "2025-06-02 12:00:00",
                "payer_email": "supporter@example.com",
                "extra": {"reward_id": 501},
            },
            {primary_key: 101, created_field: "2025-06-01 12:00:00", "payer_name": None, "is_refunded": 1},
        ]
        self.respond(
            [
                {
                    "current_page": 1,
                    "last_page": 2,
                    "data": [rows[0]],
                    "next_page_url": f"https://developers.buymeacoffee.com/api/v1/{endpoint}?page=2",
                },
                {"current_page": 2, "last_page": 2, "data": [rows[1]], "next_page_url": None},
            ]
        )
        manager = self.source.get_resumable_source_manager(self.inputs)
        response = self.source.source_for_pipeline(self.config, manager, self.inputs)

        assert list(cast(Iterable[Any], response.items())) == [[rows[0]], [rows[1]]]
        assert response.primary_keys == [primary_key]
        assert response.partition_keys == [created_field]
        assert self.send.call_count == 2
        for page, request in enumerate(self.requests, start=1):
            url = urlsplit(request.url or "")
            assert url.path == f"/api/v1/{endpoint}"
            assert parse_qs(url.query) == (
                {"page": [str(page)], "status": ["all"]} if endpoint == "subscriptions" else {"page": [str(page)]}
            )
            assert request.headers["Authorization"] == "Bearer test-token"

    @parameterized.expand([("empty", []), ("single", [{"support_id": 1}])])
    def test_terminal_page_never_requests_an_extra_page(self, _name: str, rows: list[dict[str, int]]) -> None:
        self.respond([{"data": rows, "current_page": 1, "last_page": 1, "next_page_url": None}])
        response = self.source.source_for_pipeline(
            self.config, self.source.get_resumable_source_manager(self.inputs), self.inputs
        )
        assert list(cast(Iterable[Any], response.items())) == ([rows] if rows else [])
        assert self.send.call_count == 1

    def test_unexpected_envelope_fails_instead_of_erasing_data(self) -> None:
        self.respond([{"unexpected": [], "last_page": 1}])
        response = self.source.source_for_pipeline(
            self.config, self.source.get_resumable_source_manager(self.inputs), self.inputs
        )
        with self.assertRaisesRegex(ValueError, "matched nothing"):
            list(cast(Iterable[Any], response.items()))

    def test_unknown_table_fails_before_http(self) -> None:
        self.inputs.schema_name = "unknown"
        with self.assertRaises(UnknownResourceError):
            self.source.source_for_pipeline(
                self.config, self.source.get_resumable_source_manager(self.inputs), self.inputs
            )
        self.send.assert_not_called()

    @parameterized.expand([("supporters", {}), ("subscriptions", {"status": ["all"]}), ("extras", {})])
    def test_credential_probe_reads_only_the_first_page(self, endpoint: str, params: dict[str, list[str]]) -> None:
        self.respond([{"data": [], "current_page": 1, "last_page": 100}])
        assert self.source.validate_credentials(self.config, team_id=1, schema_name=endpoint) == (True, None)
        assert self.send.call_count == 1
        request = self.requests[0]
        assert request.headers["Authorization"] == "Bearer test-token"
        assert parse_qs(urlsplit(request.url or "").query) == {"page": ["1"], **params}

    @parameterized.expand([(401, "invalid or expired"), (403, "read-only access")])
    def test_credential_denials_are_actionable_and_never_retried(self, status: int, message: str) -> None:
        self.respond([{"error_code": 45}], [status])
        valid, error = validate_credentials("test-token")
        assert not valid
        assert error is not None and message in error
        assert self.send.call_count == 1
        self.sleep.assert_not_called()

    @parameterized.expand([("empty", ""), ("non_ascii", "test-token\u200b")])
    def test_invalid_header_values_are_rejected_without_http(self, _name: str, token: str) -> None:
        valid, error = validate_credentials(token)
        assert not valid
        assert error is not None and "personal access token" in error
        self.send.assert_not_called()

    @parameterized.expand([(429,), (503,)])
    def test_transient_probe_failure_uses_shared_retry_after(self, status: int) -> None:
        self.respond([{}, {"data": []}], [status, 200])
        assert validate_credentials("test-token") == (True, None)
        assert self.send.call_count == 2
        self.sleep.assert_called_once_with(7.0)

    def test_persistent_outage_is_not_reported_as_bad_credentials(self) -> None:
        self.respond([{}] * 5, [503] * 5)
        with self.assertRaises(RESTClientRetryableError):
            validate_credentials("test-token")
        assert self.send.call_count == 5

    def test_other_client_errors_propagate(self) -> None:
        self.respond([{}], [400])
        with self.assertRaises(HTTPError):
            validate_credentials("test-token")

    def test_resume_requests_saved_page_with_membership_filter(self) -> None:
        self.inputs.schema_name = "subscriptions"
        manager = self.source.get_resumable_source_manager(self.inputs)
        manager.save_state(BuyMeACoffeeResumeConfig(page=3))
        manager.commit()
        self.respond([{"data": [{"subscription_id": 100}], "current_page": 3, "last_page": 3}])
        response = self.source.source_for_pipeline(self.config, manager, self.inputs)
        assert list(cast(Iterable[Any], response.items())) == [[{"subscription_id": 100}]]
        assert parse_qs(urlsplit(self.requests[0].url or "").query) == {"page": ["3"], "status": ["all"]}
