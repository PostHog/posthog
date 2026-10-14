import re
import json
import dataclasses
from datetime import date, datetime
from typing import Any

import pytest
from unittest.mock import MagicMock

from requests import Response
from requests.exceptions import HTTPError, ProxyError, RequestException

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    route,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.mailchimp import (
    MailchimpSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mailchimp.mailchimp import (
    MAX_RETRY_ATTEMPTS,
    MailchimpResumeConfig,
    MailchimpRetryableError,
    _format_incremental_value,
    _get_with_retry,
    _incremental_query_params,
    extract_data_center,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mailchimp.settings import MAILCHIMP_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.mailchimp.source import MailchimpSource


class TestExtractDataCenter:
    def test_invalid_key_raises(self):
        with pytest.raises(ValueError, match="Invalid Mailchimp API key format"):
            extract_data_center("invalidkey")

    @pytest.mark.parametrize(
        "malicious_key",
        [
            "key-evil.com/#",
            "key-evil.com/path",
            "key-us6.attacker.com",
            "key-dc:8080",
            "key-",
            "key- spaces",
        ],
    )
    def test_malicious_dc_values_raise(self, malicious_key):
        with pytest.raises(ValueError, match="Invalid Mailchimp API key format"):
            extract_data_center(malicious_key)


class TestValidateCredentials:
    def test_success(self) -> None:
        with scripted_network([ScriptedResponse(json={})]) as network:
            assert validate_credentials("key-us6") == (True, None)

        assert network.requests_log[0].path == "/3.0/ping"

    def test_invalid_api_key_format_is_surfaced(self):
        valid, error = validate_credentials("invalidkey")
        assert valid is False
        assert error is not None and "Invalid Mailchimp API key format" in error

    @pytest.mark.parametrize(
        "exception",
        [
            ProxyError("Cannot connect to proxy.", OSError("Tunnel connection failed: 502 Bad gateway")),
            RequestException("connection reset"),
        ],
    )
    def test_network_errors_return_friendly_message_without_raw_details(self, exception: RequestException) -> None:
        with scripted_network(always(exception)) as network:
            valid, error = validate_credentials("key-us6")

        assert valid is False
        assert error == "Could not reach the Mailchimp API. Check your network connection and try again."
        assert {request.path for request in network.requests_log} == {"/3.0/ping"}


class TestFormatIncrementalValue:
    def test_date(self):
        d = date(2024, 1, 15)
        result = _format_incremental_value(d)
        assert result == "2024-01-15T00:00:00+00:00"

    def test_string(self):
        assert _format_incremental_value("2024-01-15") == "2024-01-15"


class TestGetWithRetry:
    @pytest.mark.parametrize(
        ("status_code", "expected_error", "expected_call_count"),
        [
            # `MAX_RETRY_ATTEMPTS` is baked into the decorator at import time (it wraps a
            # top-level function, unlike the per-call nested functions other sources use), so
            # a retryable status is retried the full budget rather than a patched-down count.
            (429, MailchimpRetryableError, MAX_RETRY_ATTEMPTS),
            (500, MailchimpRetryableError, MAX_RETRY_ATTEMPTS),
            (401, HTTPError, 1),
        ],
    )
    def test_errors_are_classified(self, status_code, expected_error, expected_call_count):
        session = MagicMock()
        session.get.return_value = _make_http_response({}, status_code=status_code)

        with pytest.raises(expected_error):
            _get_with_retry(session, "https://us6.api.mailchimp.com/3.0/automations")

        assert session.get.call_count == expected_call_count

    @pytest.mark.parametrize(
        ("status_code", "reason", "expected_prefix"),
        [
            (429, "Too Many Requests", "429 Client Error"),
            (503, "Service Unavailable", "503 Server Error"),
        ],
    )
    def test_retryable_error_keeps_raise_for_status_wording(self, status_code, reason, expected_prefix):
        # A failure that outlives the retry budget is classified by message in `import_data_sync`
        # (via `MailchimpSource.get_retryable_errors`), so the wrapper must reraise the wording
        # `raise_for_status` produced rather than a phrasing of its own.
        url = "https://us6.api.mailchimp.com/3.0/automations"
        response = _make_http_response({}, status_code=status_code)
        response.reason = reason
        response.url = url
        session = MagicMock()
        session.get.return_value = response

        with pytest.raises(MailchimpRetryableError) as excinfo:
            _get_with_retry(session, url)

        assert str(excinfo.value).startswith(expected_prefix)
        assert url in str(excinfo.value)


def _driver() -> SourceDriver:
    return SourceDriver(MailchimpSource(), MailchimpSourceConfig(api_key="key-us6"))


class TestFetchContactsForList:
    @pytest.mark.parametrize(
        ("label", "start_offset", "members", "total_items", "expected_ids", "expected_checkpoint"),
        [
            (
                "fresh_page_checkpoints_at_offset_zero",
                0,
                [{"id": "m1"}, {"id": "m2"}],
                2,
                ["m1", "m2"],
                MailchimpResumeConfig(list_id="list_a", offset=0),
            ),
            (
                "resume_page_checkpoints_at_start_offset",
                1000,
                [{"id": "m3"}],
                1001,
                ["m3"],
                MailchimpResumeConfig(list_id="list_a", offset=1000),
            ),
            (
                "empty_page_is_not_checkpointed",
                0,
                [],
                0,
                [],
                None,
            ),
        ],
    )
    def test_single_page_behaviour(
        self,
        label: str,
        start_offset: int,
        members: list[dict[str, Any]],
        total_items: int,
        expected_ids: list[str],
        expected_checkpoint: MailchimpResumeConfig | None,
    ) -> None:
        result = _driver().run(
            "contacts",
            [
                ScriptedResponse(json={"lists": [{"id": "list_a"}], "total_items": 1}),
                ScriptedResponse(json={"members": members, "total_items": total_items}),
            ],
            resume_state=MailchimpResumeConfig(list_id="list_a", offset=start_offset) if start_offset else None,
        )

        assert result.raised is None
        assert [contact["id"] for contact in result.rows] == expected_ids
        assert all(contact["list_id"] == "list_a" for contact in result.rows)
        assert result.requests[1].param("offset") == str(start_offset)

        if expected_checkpoint is None:
            assert result.saved_states == []
        else:
            assert result.saved_states == [expected_checkpoint]


class TestGetContactsIterator:
    @pytest.mark.parametrize(
        (
            "label",
            "can_resume",
            "load_state",
            "list_ids",
            "page_by_list_offset",
            "expected_emitted",
            "expected_visits",
            "expected_checkpoints",
        ),
        [
            (
                "fresh_run_iterates_all_lists",
                False,
                None,
                ["list_a", "list_b"],
                {
                    ("list_a", 0): ([{"id": "a1"}], 1),
                    ("list_b", 0): ([{"id": "b1"}], 1),
                },
                [("list_a", "a1"), ("list_b", "b1")],
                [("list_a", 0), ("list_b", 0)],
                [
                    MailchimpResumeConfig(list_id="list_a", offset=0),
                    MailchimpResumeConfig(list_id="list_b", offset=0),
                ],
            ),
            (
                "resume_skips_prior_lists_and_starts_mid_list",
                True,
                MailchimpResumeConfig(list_id="list_b", offset=1000),
                ["list_a", "list_b", "list_c"],
                {
                    ("list_b", 1000): ([{"id": "b2"}], 1001),
                    ("list_c", 0): ([{"id": "c1"}], 1),
                },
                [("list_b", "b2"), ("list_c", "c1")],
                [("list_b", 1000), ("list_c", 0)],
                [
                    MailchimpResumeConfig(list_id="list_b", offset=1000),
                    MailchimpResumeConfig(list_id="list_c", offset=0),
                ],
            ),
            (
                "resume_falls_back_to_fresh_when_list_id_missing",
                True,
                MailchimpResumeConfig(list_id="gone", offset=500),
                ["list_a"],
                {
                    ("list_a", 0): ([{"id": "a1"}], 1),
                },
                [("list_a", "a1")],
                [("list_a", 0)],
                [MailchimpResumeConfig(list_id="list_a", offset=0)],
            ),
        ],
    )
    def test_iteration(
        self,
        label: str,
        can_resume: bool,
        load_state: MailchimpResumeConfig | None,
        list_ids: list[str],
        page_by_list_offset: dict[tuple[str, int], tuple[list[dict[str, Any]], int]],
        expected_emitted: list[tuple[str, str]],
        expected_visits: list[tuple[str, int]],
        expected_checkpoints: list[MailchimpResumeConfig],
    ) -> None:
        responses = {
            "/3.0/lists": [
                ScriptedResponse(
                    json={"lists": [{"id": list_id} for list_id in list_ids], "total_items": len(list_ids)}
                )
            ],
            **{
                f"/3.0/lists/{list_id}/members": [
                    ScriptedResponse(json={"members": members, "total_items": total_items})
                ]
                for (list_id, _), (members, total_items) in page_by_list_offset.items()
            },
        }
        result = _driver().run(
            "contacts",
            route(responses),
            resume_state=load_state if can_resume else None,
        )

        assert result.raised is None
        assert [(contact["list_id"], contact["id"]) for contact in result.rows] == expected_emitted
        assert [
            (request.path.split("/")[3], int(request.param("offset") or "0")) for request in result.requests[1:]
        ] == expected_visits
        assert result.saved_states == expected_checkpoints


def _make_http_response(body: dict[str, Any], status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    resp.headers["Content-Type"] = "application/json"
    return resp


class TestRestEndpointResumeBehavior:
    """End-to-end resume behaviour of the shared ``rest_api_resource`` path used
    for ``lists``/``campaigns``/``reports`` (offset/count pagination)."""

    @pytest.mark.parametrize("endpoint", ["lists", "campaigns", "reports"])
    def test_fresh_run_saves_offset_after_each_non_terminal_page(self, endpoint: str) -> None:
        data_key = endpoint  # lists/campaigns/reports all use their own name as data_selector
        responses = [
            ScriptedResponse(json={data_key: [{"id": "a"}], "total_items": 2500}),
            ScriptedResponse(json={data_key: [{"id": "b"}], "total_items": 2500}),
            ScriptedResponse(json={data_key: [{"id": "c"}], "total_items": 2500}),
        ]
        result = _driver().run(endpoint, responses)

        assert result.raised is None
        assert result.params("offset") == ["0", "1000", "2000"]
        assert result.saved_states == [
            MailchimpResumeConfig(offset=1000),
            MailchimpResumeConfig(offset=2000),
        ]

    @pytest.mark.parametrize("endpoint", ["lists", "campaigns", "reports"])
    def test_resume_seeds_paginator_with_saved_offset(self, endpoint: str) -> None:
        data_key = endpoint
        result = _driver().run(
            endpoint,
            [ScriptedResponse(json={data_key: [{"id": "c"}], "total_items": 2500})],
            resume_state=MailchimpResumeConfig(offset=2000),
        )

        assert result.raised is None
        assert result.params("offset") == ["2000"]

    def test_saved_state_serialization_round_trip_with_list_id_absent(self) -> None:
        # REST-endpoint checkpoints omit list_id; ensure ResumableSourceManager's
        # asdict/json round trip reproduces the dataclass unchanged.
        cfg = MailchimpResumeConfig(offset=1500)
        as_json = json.dumps(dataclasses.asdict(cfg))
        reconstituted = MailchimpResumeConfig(**json.loads(as_json))
        assert reconstituted == cfg
        assert reconstituted.list_id is None


class TestEndpointConfigInvariants:
    @pytest.mark.parametrize("name", sorted(MAILCHIMP_ENDPOINTS))
    def test_fan_out_path_placeholders_match_declared_parents(self, name: str) -> None:
        # A placeholder with no matching parent raises KeyError at str.format() time — mid-sync,
        # on that endpoint only. `contacts` is exempt: it formats its path in its own iterator.
        config = MAILCHIMP_ENDPOINTS[name]
        if name == "contacts":
            return

        placeholders = set(re.findall(r"\{(\w+)\}", config.path))
        assert placeholders == {parent.inject_as for parent in config.parents}

    @pytest.mark.parametrize("name", sorted(MAILCHIMP_ENDPOINTS))
    def test_fan_out_primary_keys_include_every_parent_id(self, name: str) -> None:
        # Child rows are pooled from every parent, so a key without the parent id is not unique
        # table-wide and every later merge multi-matches the duplicates.
        config = MAILCHIMP_ENDPOINTS[name]
        for parent in config.parents:
            assert parent.inject_as in config.primary_keys


class TestIncrementalQueryParams:
    @pytest.mark.parametrize(
        ("endpoint", "field", "expected"),
        [
            # Guards the params the pre-existing endpoints have always sent.
            ("campaigns", "create_time", {"since_create_time": "2024-01-02T03:04:05+00:00"}),
            ("campaigns", "send_time", {"since_send_time": "2024-01-02T03:04:05+00:00"}),
            ("reports", "send_time", {"since_send_time": "2024-01-02T03:04:05+00:00"}),
            ("reports", "create_time", {}),
            ("lists", None, {}),
            ("automations", "create_time", {"since_create_time": "2024-01-02T03:04:05+00:00"}),
            ("automations", "start_time", {"since_start_time": "2024-01-02T03:04:05+00:00"}),
            ("templates", "date_created", {"since_date_created": "2024-01-02T03:04:05+00:00"}),
            ("list_segments", "updated_at", {"since_updated_at": "2024-01-02T03:04:05+00:00"}),
            ("list_segments", "created_at", {"since_created_at": "2024-01-02T03:04:05+00:00"}),
            # No server-side filter available, so the endpoint stays on full refresh.
            ("ecommerce_orders", "processed_at_foreign", {}),
        ],
    )
    def test_field_maps_to_vendor_filter(self, endpoint: str, field: str | None, expected: dict[str, str]) -> None:
        assert (
            _incremental_query_params(
                MAILCHIMP_ENDPOINTS[endpoint],
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2024, 1, 2, 3, 4, 5),
                incremental_field=field,
            )
            == expected
        )


class TestGenericEndpointIterator:
    @pytest.mark.parametrize(
        ("endpoint", "routes", "expected_paths", "expected_params"),
        [
            (
                # count/offset endpoint: both params sent.
                "list_activity",
                {
                    "/lists": [{"lists": [{"id": "l1"}], "total_items": 1}],
                    "/lists/l1/activity": [{"activity": [{"day": "2024-01-01"}], "total_items": 1}],
                },
                ["/lists", "/lists/l1/activity"],
                {"count": 1000, "offset": 0},
            ),
            (
                # `count` is accepted but `offset` is not — sending it risks a 400.
                "landing_pages",
                {"/landing-pages": [{"landing_pages": [{"id": "p1"}], "total_items": 1}]},
                ["/landing-pages"],
                {"count": 1000},
            ),
            (
                # No pagination params at all on this endpoint.
                "verified_domains",
                {"/verified-domains": [{"domains": [{"domain": "example.com"}], "total_items": 1}]},
                ["/verified-domains"],
                {},
            ),
        ],
    )
    def test_only_supported_pagination_params_are_sent(
        self,
        endpoint: str,
        routes: dict[str, list[dict[str, Any]]],
        expected_paths: list[str],
        expected_params: dict[str, Any],
    ) -> None:
        result = _driver().run(
            endpoint,
            route({path: [ScriptedResponse(json=body) for body in bodies] for path, bodies in routes.items()}),
        )

        assert result.raised is None
        assert result.paths == [f"/3.0{path}" for path in expected_paths]
        assert {name: values[0] for name, values in result.requests[-1].query.items()} == {
            name: str(value) for name, value in expected_params.items()
        }
        assert len(result.rows) == 1

    def test_fan_out_injects_parent_id_onto_rows_the_api_omits(self) -> None:
        # /reports/{id}/locations rows carry no campaign_id, so without injection the
        # primary key would collapse every campaign's regions onto each other.
        result = _driver().run(
            "report_locations",
            route(
                {
                    "/reports": [ScriptedResponse(json={"reports": [{"id": "c1"}, {"id": "c2"}], "total_items": 2})],
                    "/reports/c1/locations": [
                        ScriptedResponse(json={"locations": [{"country_code": "US", "region": "CA"}], "total_items": 1})
                    ],
                    "/reports/c2/locations": [
                        ScriptedResponse(json={"locations": [{"country_code": "GB", "region": ""}], "total_items": 1})
                    ],
                }
            ),
        )

        assert result.raised is None
        assert result.rows == [
            {"campaign_id": "c1", "country_code": "US", "region": "CA"},
            {"campaign_id": "c2", "country_code": "GB", "region": ""},
        ]
        assert result.paths == ["/3.0/reports", "/3.0/reports/c1/locations", "/3.0/reports/c2/locations"]

    def test_single_object_endpoint_yields_one_row_per_parent(self) -> None:
        result = _driver().run(
            "campaign_content",
            route(
                {
                    "/campaigns": [ScriptedResponse(json={"campaigns": [{"id": "c1"}], "total_items": 1})],
                    "/campaigns/c1/content": [ScriptedResponse(json={"html": "<p>hi</p>", "plain_text": "hi"})],
                }
            ),
        )

        assert result.raised is None
        assert result.rows == [{"campaign_id": "c1", "html": "<p>hi</p>", "plain_text": "hi"}]

    def test_resume_skips_completed_parents_and_seeds_the_saved_offset(self) -> None:
        result = _driver().run(
            "report_sent_to",
            route(
                {
                    "/reports": [ScriptedResponse(json={"reports": [{"id": "c1"}, {"id": "c2"}], "total_items": 2})],
                    "/reports/c2/sent-to": [
                        ScriptedResponse(json={"sent_to": [{"email_id": "e9"}], "total_items": 1001})
                    ],
                }
            ),
            resume_state=MailchimpResumeConfig(offset=1000, parent_ids=["c2"]),
        )

        assert result.raised is None
        assert [row["email_id"] for row in result.rows] == ["e9"]
        assert result.paths == ["/3.0/reports", "/3.0/reports/c2/sent-to"]
        assert result.requests[-1].param("offset") == "1000"


class TestSourceResponseForNewEndpoints:
    def test_fan_out_endpoint_is_routed_away_from_the_rest_path(self) -> None:
        # Routing a fan-out endpoint through rest_api_resource would request the literal
        # unformatted `/reports/{campaign_id}/locations` and 404.
        result = _driver().run(
            "report_locations",
            route(
                {
                    "/reports": [ScriptedResponse(json={"reports": [{"id": "c1"}], "total_items": 1})],
                    "/reports/c1/locations": [
                        ScriptedResponse(json={"locations": [{"country_code": "US", "region": ""}], "total_items": 1})
                    ],
                }
            ),
        )

        assert result.raised is None
        assert result.response is not None
        assert result.response.primary_keys == ["campaign_id", "country_code", "region"]
        assert result.rows == [{"campaign_id": "c1", "country_code": "US", "region": ""}]
        assert result.paths == ["/3.0/reports", "/3.0/reports/c1/locations"]

    @pytest.mark.parametrize(
        ("endpoint", "expected_primary_keys", "expected_partition_keys", "first_response"),
        [
            ("lists", ["id"], ["date_created"], {"lists": [], "total_items": 0}),
            ("contacts", ["list_id", "id"], None, {"lists": [], "total_items": 0}),
            ("ecommerce_orders", ["store_id", "id"], ["processed_at_foreign"], {"orders": [], "total_items": 0}),
            ("verified_domains", ["domain"], None, {"domains": []}),
            ("report_unsubscribed", ["campaign_id", "email_id"], ["timestamp"], {"reports": [], "total_items": 0}),
        ],
    )
    def test_primary_and_partition_keys_come_from_the_endpoint_config(
        self,
        endpoint: str,
        expected_primary_keys: list[str],
        expected_partition_keys: list[str] | None,
        first_response: dict[str, Any],
    ) -> None:
        result = _driver().run(endpoint, [ScriptedResponse(json=first_response)])

        assert result.raised is None
        assert result.response is not None
        assert result.response.primary_keys == expected_primary_keys
        assert result.response.partition_keys == expected_partition_keys


class TestMailchimpRetryableErrors:
    @pytest.mark.parametrize(
        ("name", "observed_error"),
        [
            ("401", "401 Client Error: Unauthorized for url: https://us15.api.mailchimp.com/3.0/lists"),
            ("403", "403 Client Error: Forbidden for url: https://us15.api.mailchimp.com/3.0/lists"),
            ("invalid_key_format", "Invalid Mailchimp API key format. Expected format: key-dc"),
        ],
    )
    def test_non_retryable_errors_do_not_match(self, name: str, observed_error: str) -> None:
        retryable_errors = MailchimpSource().get_retryable_errors()
        assert not any(key in observed_error for key in retryable_errors), observed_error

    @pytest.mark.parametrize(
        ("name", "observed_error"),
        [
            ("429", "429 Client Error: Too Many Requests for url: https://us15.api.mailchimp.com/3.0/lists"),
            (
                "server_error",
                "500 Server Error: Internal Server Error for url: https://us15.api.mailchimp.com/3.0/lists",
            ),
            (
                "read_timeout_exhausted",
                "HTTPSConnectionPool(host='us15.api.mailchimp.com', port=443): Max retries exceeded with url: "
                '/3.0/campaigns?count=1000&offset=0 (Caused by ReadTimeoutError("HTTPSConnectionPool('
                "host='us15.api.mailchimp.com', port=443): Read timed out. (read timeout=120)\"))",
            ),
        ],
    )
    def test_transient_errors_are_recognized_as_retryable(self, name: str, observed_error: str) -> None:
        retryable_errors = MailchimpSource().get_retryable_errors()
        assert any(key in observed_error for key in retryable_errors), observed_error
