from datetime import UTC, date, datetime
from typing import Any

import pytest

from requests import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.guru import GuruSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.guru.guru import (
    GuruResumeConfig,
    _ensure_event_id,
    _format_last_modified,
    _normalize_member,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.guru.settings import GURU_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.guru.source import GuruSource


def _driver() -> SourceDriver:
    return SourceDriver(GuruSource(), GuruSourceConfig(username="user@company.com", api_token="token"))


def _page(items: Any, next_link: str | None = None) -> ScriptedResponse:
    headers = {"Link": f'<{next_link}>; rel="next-page"'} if next_link else {}
    return ScriptedResponse(json=items, headers=headers)


def _whoami() -> ScriptedResponse:
    return ScriptedResponse(json={"team": {"id": "team-1"}, "tokenType": "API"})


class TestFormatLastModified:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC), "2024-01-02T03:04:05+00:00"),
            (datetime(2024, 1, 2, 3, 4, 5), "2024-01-02T03:04:05+00:00"),
            (date(2024, 1, 2), "2024-01-02T00:00:00+00:00"),
            ("2024-01-02T03:04:05+00:00", "2024-01-02T03:04:05+00:00"),
        ],
    )
    def test_format_values(self, value: Any, expected: str) -> None:
        assert _format_last_modified(value) == expected


class TestNormalizeMember:
    def test_keeps_existing_top_level_email(self) -> None:
        item = {"email": "top@company.com", "user": {"email": "nested@company.com"}}
        assert _normalize_member(item)["email"] == "top@company.com"

    def test_missing_nested_email_raises_keyerror(self) -> None:
        # email is the primary key, so a member nesting a user dict without an email must
        # fail loudly rather than produce a row with a null primary key.
        with pytest.raises(KeyError):
            _normalize_member({"user": {"firstName": "Jane"}})


class TestEnsureEventId:
    def test_documented_event_without_id_gets_stable_content_key(self) -> None:
        event = {
            "type": "card-viewed",
            "user": "jane@company.com",
            "eventDate": "2016-01-20T03:10:11.351+0000",
            "properties": {"cardId": "c1"},
        }
        other = {**event, "eventDate": "2016-01-20T03:10:12.000+0000"}

        first = _ensure_event_id(event)["id"]

        assert first and first == _ensure_event_id(dict(event))["id"]
        assert first != _ensure_event_id(other)["id"]


class TestValidateCredentials:
    def test_probe_disables_redirects_to_protect_credential(self) -> None:
        # The Basic-auth credential rides on the probe; the session must be built with redirects
        # pinned off so a redirect can't replay it to the redirect target during validation.
        with scripted_network([_whoami()]) as network:
            assert validate_credentials("user@company.com", "token") is True

        assert network.session_options[0].get("allow_redirects") is False


class TestGetRows:
    def test_paginates_via_link_header(self) -> None:
        next_url = "https://api.getguru.com/api/v1/collections?token=abc"
        result = _driver().run(
            "collections",
            [_page([{"id": "1"}, {"id": "2"}], next_link=next_url), _page([{"id": "3"}])],
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["1", "2", "3"]
        assert result.urls == ["https://api.getguru.com/api/v1/collections", next_url]
        # State is saved only while a next page exists, after the page is yielded.
        assert result.saved_states == [GuruResumeConfig(next_url=next_url)]

    def test_rejects_next_url_with_foreign_host(self) -> None:
        # A tampered Link header pointing off-host must not move the credentialed request; the
        # SSRF host pin rejects it loudly rather than silently exfiltrating the Basic auth header.
        evil_url = "http://169.254.169.254/latest/meta-data"
        result = _driver().run("collections", [_page([{"id": "1"}], next_link=evil_url)])

        assert isinstance(result.raised, ValueError)
        assert "disallowed host" in str(result.raised)
        assert result.paths == ["/api/v1/collections"]

    def test_rejects_resume_url_with_foreign_host(self) -> None:
        result = _driver().run(
            "collections",
            [],
            resume_state=GuruResumeConfig(next_url="http://169.254.169.254/latest/meta-data"),
        )

        assert isinstance(result.raised, ValueError)
        assert "disallowed host" in str(result.raised)
        assert result.requests == []

    def test_rejects_redirect_response(self) -> None:
        # Redirects are disabled so a 3xx can't silently move the credentialed request off-host.
        result = _driver().run(
            "collections",
            [ScriptedResponse(status=302, headers={"Location": "http://169.254.169.254/latest/meta-data"})],
        )

        assert isinstance(result.raised, ValueError)
        assert "redirect" in str(result.raised).lower()
        assert result.paths == ["/api/v1/collections"]

    def test_incremental_request_includes_gql_filter(self) -> None:
        result = _driver().run(
            "cards",
            [_page([])],
            db_incremental_field_last_value=datetime(2024, 1, 1, tzinfo=UTC),
            incremental_field="lastModified",
        )

        assert result.raised is None
        assert result.requests[0].param("q") == "lastModified >= 2024-01-01T00:00:00+00:00"
        assert result.requests[0].param("sortField") == "lastModified"
        assert result.requests[0].param("sortOrder") == "asc"

    def test_non_list_response_fails_loud(self) -> None:
        # A 200 body that isn't a bare array means the response shape changed — fail loud rather
        # than wrapping the stray object as a single row.
        result = _driver().run("cards", [_page({"error": "unexpected"})])

        assert isinstance(result.raised, ValueError)
        assert "list response body" in str(result.raised)


class TestTeamScopedEndpoints:
    def test_tags_are_flattened_from_categories_under_resolved_team(self) -> None:
        result = _driver().run(
            "tags",
            [
                _whoami(),
                _page(
                    [
                        {"id": "cat-1", "name": "Fruits", "tags": [{"id": "t1", "value": "Apple"}]},
                        {"id": "cat-2", "name": "Empty", "tags": []},
                    ]
                ),
            ],
        )

        assert result.raised is None
        assert result.paths[1] == "/api/v1/teams/team-1/tagcategories"
        assert result.rows == [{"categoryId": "cat-1", "categoryName": "Fruits", "id": "t1", "value": "Apple"}]

    def test_analytics_incremental_request_filters_by_from_date(self) -> None:
        result = _driver().run(
            "analytics_events",
            [_whoami(), _page([{"id": "e1", "eventDate": "2024-01-02T00:00:00.000+0000"}])],
            db_incremental_field_last_value=datetime(2024, 1, 1, tzinfo=UTC),
            incremental_field="eventDate",
        )

        assert result.raised is None
        assert result.paths[1] == "/api/v1/teams/team-1/analytics"
        assert result.queries[1] == {"fromDate": ("2024-01-01T00:00:00.000+00:00",)}
        assert [row["id"] for row in result.rows] == ["e1"]
        # Guru documents no order for the export, so the watermark must not checkpoint mid-run.
        assert result.response is not None
        assert result.response.sort_mode == "desc"

    def test_whoami_auth_failure_surfaces_as_http_error(self) -> None:
        result = _driver().run("analytics_events", [ScriptedResponse(status=401)])

        assert isinstance(result.raised, HTTPError)
        assert "401 Client Error: Unauthorized for url: https://api.getguru.com" in str(result.raised)


class TestFanoutEndpoints:
    @pytest.mark.parametrize(
        "endpoint, parent_id, child_path, child_rows, expected",
        [
            (
                "group_members",
                "g1",
                "/groups/g1/members",
                [{"id": "m1", "user": {"email": "jane@company.com"}}],
                [{"id": "m1", "user": {"email": "jane@company.com"}, "group_id": "g1", "email": "jane@company.com"}],
            ),
            (
                "folder_items",
                "f1",
                "/folders/f1/items",
                [{"id": "c1", "type": "card"}],
                [{"id": "c1", "type": "card", "folder_id": "f1"}],
            ),
        ],
    )
    def test_child_rows_carry_parent_id(
        self,
        endpoint: str,
        parent_id: str,
        child_path: str,
        child_rows: list[dict[str, Any]],
        expected: list[dict[str, Any]],
    ) -> None:
        result = _driver().run(endpoint, [_page([{"id": parent_id}]), _page(child_rows)])

        assert result.raised is None
        assert result.paths[1].endswith(child_path)
        assert result.rows == expected
        assert result.response is not None
        assert result.response.primary_keys is not None
        assert all(row[key] is not None for row in result.rows for key in result.response.primary_keys)


class TestGuruSourceResponse:
    @pytest.mark.parametrize("endpoint", [name for name, config in GURU_ENDPOINTS.items() if config.fanout is None])
    def test_response_metadata_per_endpoint(self, endpoint: str) -> None:
        config = GURU_ENDPOINTS[endpoint]
        script = [_whoami(), _page([])] if "{team_id}" in config.path else [_page([])]
        result = _driver().run(endpoint, script)

        assert result.raised is None
        assert result.response is not None
        assert result.response.name == endpoint
        assert result.response.primary_keys == [config.primary_key]
        if config.partition_key:
            assert result.response.partition_mode == "datetime"
            assert result.response.partition_keys == [config.partition_key]
        else:
            assert result.response.partition_mode is None
            assert result.response.partition_keys is None
