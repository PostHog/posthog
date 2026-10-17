from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any

import pytest
import time_machine

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.capsule_crm.capsule_crm import (
    CAPSULE_CRM_BASE_URL,
    CapsuleCRMResumeConfig,
    CapsuleCRMUntrustedURLError,
    _clamp_future_value_to_now,
    _format_since_value,
    _validate_pagination_url,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.capsule_crm.source import CapsuleCRMSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.capsulecrm import (
    CapsuleCRMSourceConfig,
)


def _driver(access_token: str = "tok") -> SourceDriver:
    return SourceDriver(CapsuleCRMSource(), CapsuleCRMSourceConfig(access_token=access_token))


def _response(body: dict[str, Any], *, next_url: str | None = None, status_code: int = 200) -> ScriptedResponse:
    headers = {"Link": f'<{next_url}>; rel="next"'} if next_url else {}
    return ScriptedResponse(status=status_code, json=body, headers=headers)


class TestFormatSinceValue:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14Z"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14Z"),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00Z"),
            ("string_passthrough", "2026-03-04T02:58:14Z", "2026-03-04T02:58:14Z"),
        ]
    )
    def test_format_since_value(self, _name: str, value: object, expected: str) -> None:
        assert _format_since_value(value) == expected

    def test_non_utc_datetime_is_converted_to_utc(self) -> None:
        value = datetime(2026, 3, 4, 12, 0, 0, tzinfo=timezone(timedelta(hours=5)))
        assert _format_since_value(value) == "2026-03-04T07:00:00Z"


class TestClampFutureValueToNow:
    @time_machine.travel("2026-06-15T12:00:00Z", tick=False)
    def test_future_date_is_clamped(self) -> None:
        assert _clamp_future_value_to_now(date(2027, 2, 5)) == date(2026, 6, 15)

    def test_string_passthrough(self) -> None:
        assert _clamp_future_value_to_now("some-cursor") == "some-cursor"


class TestRequestParams:
    def test_incremental_endpoint_embeds_related_data(self) -> None:
        result = _driver().run("parties", [_response({"parties": [{"id": 1}]})])

        assert result.raised is None
        # embed values are folded in to reduce round-trips.
        assert result.requests[0].param("embed") == "tags,fields,organisation"
        assert result.requests[0].param("since") is None

    @time_machine.travel("2026-06-15T12:00:00Z", tick=False)
    def test_future_watermark_is_clamped_to_now(self) -> None:
        result = _driver().run(
            "parties",
            [_response({"parties": []})],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2027, 2, 5, 21, 46, 42, tzinfo=UTC),
        )

        assert result.raised is None
        assert result.requests[0].param("since") == "2026-06-15T12:00:00Z"

    @parameterized.expand(
        [
            ("boards", "boards", {"status": "all"}),
            ("stages", "stages", {"status": "all", "includeOnDeletedBoard": "true"}),
        ]
    )
    def test_lookup_endpoints_request_archived_records(
        self, endpoint: str, data_key: str, expected: dict[str, Any]
    ) -> None:
        # Capsule defaults these to active-only, which would drop the boards and stages that
        # historic projects still point at.
        result = _driver().run(endpoint, [_response({data_key: []})])

        assert result.raised is None
        assert result.queries == [{key: (str(value),) for key, value in {"perPage": 100, **expected}.items()}]

    def test_entries_embeds_its_associations(self) -> None:
        # Without the embeds an entry cannot be joined back to the record it belongs to.
        result = _driver().run("entries", [_response({"entries": []})])

        assert result.raised is None
        assert result.requests[0].param("embed") == "party,kase,opportunity,creator,activityType"

    @parameterized.expand(
        [
            ("party_tags", f"{CAPSULE_CRM_BASE_URL}/parties/tags"),
            ("opportunity_tags", f"{CAPSULE_CRM_BASE_URL}/opportunities/tags"),
            ("kase_tags", f"{CAPSULE_CRM_BASE_URL}/kases/tags"),
        ]
    )
    def test_tag_endpoints_are_entity_scoped(self, endpoint: str, expected_url: str) -> None:
        # Capsule has no top-level /tags collection; tag definitions hang off each entity type and
        # all three nest under the same "tags" wrapper key.
        result = _driver().run(endpoint, [_response({"tags": [{"id": 3, "name": "VIP"}]})])

        assert result.raised is None
        assert result.requests[0].origin + result.requests[0].path == expected_url
        assert result.rows == [{"id": 3, "name": "VIP"}]

    def test_since_ignored_for_full_refresh_only_endpoint(self) -> None:
        # tasks has no server-side `since` filter, so a watermark must not produce a `since` param.
        result = _driver().run(
            "tasks",
            [_response({"tasks": []})],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
        )

        assert result.raised is None
        assert result.requests[0].param("since") is None


class TestPagination:
    def test_follows_link_header_pagination(self) -> None:
        page2 = f"{CAPSULE_CRM_BASE_URL}/parties?perPage=100&page=2"
        result = _driver().run(
            "parties",
            [
                _response({"parties": [{"id": 1}, {"id": 2}]}, next_url=page2),
                _response({"parties": [{"id": 3}]}),
            ],
        )

        assert result.raised is None
        assert result.rows == [{"id": 1}, {"id": 2}, {"id": 3}]
        # The next-page URL is self-contained; the original params must not be re-appended.
        assert result.urls[1] == page2
        assert result.queries[1] == {"perPage": ("100",), "page": ("2",)}

    def test_saves_resume_state_after_each_page_with_more(self) -> None:
        page2 = f"{CAPSULE_CRM_BASE_URL}/parties?perPage=100&page=2"
        result = _driver().run(
            "parties",
            [
                _response({"parties": [{"id": 1}]}, next_url=page2),
                _response({"parties": [{"id": 2}]}),
            ],
        )

        assert result.raised is None
        # State saved once (after page 1, which still had a next page); not after the final page.
        assert result.saved_states == [CapsuleCRMResumeConfig(next_url=page2)]

    def test_resumes_from_saved_next_url(self) -> None:
        page2 = f"{CAPSULE_CRM_BASE_URL}/parties?perPage=100&page=2"
        result = _driver().run(
            "parties", [_response({"parties": [{"id": 2}]})], resume_state=CapsuleCRMResumeConfig(next_url=page2)
        )

        assert result.raised is None
        assert result.rows == [{"id": 2}]
        # The starting URL must NOT be fetched when resuming.
        assert len(result.requests) == 1
        assert result.urls[0] == page2
        assert result.queries[0] == {"perPage": ("100",), "page": ("2",)}

    def test_hostile_upstream_next_url_is_rejected(self) -> None:
        # An upstream Link header pointing at another host must abort before the bearer token is sent
        # there, and the poisoned URL must not be persisted as resume state.
        result = _driver().run(
            "parties",
            [_response({"parties": [{"id": 1}]}, next_url="https://evil.example.com/api/v2/parties")],
        )

        assert isinstance(result.raised, CapsuleCRMUntrustedURLError)
        assert len(result.requests) == 1
        assert result.saved_states == []

    def test_hostile_resumed_next_url_is_rejected(self) -> None:
        # A poisoned resume state from Redis must never be requested with the bearer token.
        result = _driver().run(
            "parties", [], resume_state=CapsuleCRMResumeConfig(next_url="https://evil.example.com/api/v2/parties")
        )
        assert isinstance(result.raised, CapsuleCRMUntrustedURLError)
        assert result.requests == []


class TestErrorHandling:
    @parameterized.expand([(401,), (403,), (404,)])
    def test_client_errors_raise_for_status(self, status: int) -> None:
        result = _driver().run("parties", [_response({}, status_code=status)])

        # `get_non_retryable_errors` matches on this stable "NNN Client Error ... for url" text.
        assert isinstance(result.raised, requests.HTTPError)
        assert f"{status} Client Error" in str(result.raised)


class TestValidatePaginationUrl:
    @parameterized.expand(
        [
            ("first_page", f"{CAPSULE_CRM_BASE_URL}/parties?perPage=100"),
            ("next_page", f"{CAPSULE_CRM_BASE_URL}/parties?perPage=100&page=2"),
            ("other_endpoint", f"{CAPSULE_CRM_BASE_URL}/opportunities?page=3"),
        ]
    )
    def test_trusted_urls_pass_through(self, _name: str, url: str) -> None:
        assert _validate_pagination_url(url) == url

    @parameterized.expand(
        [
            ("foreign_host", "https://evil.example.com/api/v2/parties"),
            ("subdomain_lookalike", "https://api.capsulecrm.com.evil.example.com/api/v2/parties"),
            ("http_scheme", "http://api.capsulecrm.com/api/v2/parties"),
            ("wrong_path_prefix", "https://api.capsulecrm.com/internal/parties"),
            ("missing_path", "https://api.capsulecrm.com"),
            ("metadata_endpoint", "http://169.254.169.254/latest/meta-data/"),
        ]
    )
    def test_untrusted_urls_raise(self, _name: str, url: str) -> None:
        with pytest.raises(CapsuleCRMUntrustedURLError):
            _validate_pagination_url(url)


class TestTokenRedaction:
    def test_validate_credentials_redacts_token_and_disables_redirects(self) -> None:
        with scripted_network([ScriptedResponse(status=200, json={})]) as network:
            assert validate_credentials("secret-token") is True

        assert network.session_options[0]["redact_values"] == ("secret-token",)
        assert network.session_options[0]["allow_redirects"] is False
        assert network.requests_log[0].headers["authorization"] == "Bearer secret-token"

    def test_source_session_redacts_token_and_disables_redirects(self) -> None:
        result = _driver("secret-token").run("parties", [_response({"parties": []})])

        assert result.raised is None
        assert result.session_options[0]["redact_values"] == ("secret-token",)
        assert result.session_options[0]["allow_redirects"] is False
        assert result.requests[0].headers["authorization"] == "Bearer secret-token"


class TestSourceResponse:
    @parameterized.expand(
        [
            ("parties", "createdAt"),
            ("opportunities", "createdAt"),
            ("kases", "createdAt"),
            ("tasks", "createdAt"),
        ]
    )
    def test_incremental_and_taskish_endpoints_partition_on_created_at(self, endpoint: str, partition_key: str) -> None:
        result = _driver().run(endpoint, [_response({endpoint: []})])
        assert result.raised is None
        response = result.response
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        assert response.partition_mode == "datetime"
        assert response.partition_keys == [partition_key]
        assert response.sort_mode == "asc"

    @parameterized.expand(
        [
            ("users",),
            ("milestones",),
            ("pipelines",),
            ("categories",),
            ("lost_reasons",),
            ("boards",),
            ("stages",),
            ("party_tags",),
            ("opportunity_tags",),
            ("kase_tags",),
        ]
    )
    def test_metadata_endpoints_are_unpartitioned(self, endpoint: str) -> None:
        data_key = "lostReasons" if endpoint == "lost_reasons" else "tags" if endpoint.endswith("_tags") else endpoint
        result = _driver().run(endpoint, [_response({data_key: []})])
        assert result.raised is None
        response = result.response
        assert response is not None
        assert response.primary_keys == ["id"]
        assert response.partition_mode is None
        assert response.partition_keys is None
        assert response.sort_mode == "asc"
