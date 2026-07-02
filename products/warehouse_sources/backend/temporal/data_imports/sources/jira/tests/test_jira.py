from datetime import date, datetime
from typing import Any

import pytest
from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.jira.jira import (
    JiraResumeConfig,
    _build_issues_jql,
    _extract_items,
    _format_jql_datetime,
    _normalize_issue,
    base_url,
    get_rows,
    is_valid_subdomain,
    jira_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.jira.settings import JIRA_ENDPOINTS


def _fake_response(json_data: Any, status_code: int = 200) -> mock.MagicMock:
    response = mock.MagicMock()
    response.status_code = status_code
    response.ok = 200 <= status_code < 300
    response.json.return_value = json_data
    response.text = ""
    return response


def _manager(resume: JiraResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume is not None
    manager.load_state.return_value = resume
    return manager


class TestSubdomain:
    @parameterized.expand(
        [
            ("simple", "acme", True),
            ("with_dash", "acme-corp", True),
            ("alphanumeric", "acme123", True),
            ("empty", "", False),
            ("with_dot", "acme.evil", False),
            ("with_at", "acme@evil.com", False),
            ("with_slash", "acme/path", False),
            ("leading_dash", "-acme", False),
        ]
    )
    def test_is_valid_subdomain(self, _name: str, subdomain: str, expected: bool) -> None:
        assert is_valid_subdomain(subdomain) is expected

    def test_base_url(self) -> None:
        assert base_url("acme") == "https://acme.atlassian.net"


class TestFormatJqlDatetime:
    @parameterized.expand(
        [
            # A one day lookback is subtracted to absorb timezone skew between our UTC watermark and the instance TZ.
            ("datetime", datetime(2026, 3, 4, 2, 58), "2026-03-03 02:58"),
            ("date", date(2026, 3, 4), "2026-03-03 00:00"),
            ("iso_string", "2026-03-04T02:58:14+00:00", "2026-03-03 02:58"),
            ("iso_string_z", "2026-03-04T02:58:14Z", "2026-03-03 02:58"),
        ]
    )
    def test_format_jql_datetime(self, _name: str, value: Any, expected: str) -> None:
        assert _format_jql_datetime(value) == expected


class TestBuildIssuesJql:
    def test_no_last_value_bounds_with_epoch_floor(self) -> None:
        # ``/search/jql`` 400s on unbounded queries, so a full sync must still carry a lower bound.
        assert _build_issues_jql("updated", None) == 'updated >= "1970-01-01 00:00" ORDER BY updated ASC'

    def test_with_last_value_filters_and_orders(self) -> None:
        jql = _build_issues_jql("updated", datetime(2026, 3, 4, 2, 58))
        assert jql == 'updated >= "2026-03-03 02:58" ORDER BY updated ASC'

    def test_custom_incremental_field(self) -> None:
        jql = _build_issues_jql("created", datetime(2026, 3, 4, 2, 58))
        assert jql == 'created >= "2026-03-03 02:58" ORDER BY created ASC'

    def test_none_field_defaults_to_updated(self) -> None:
        assert _build_issues_jql(None, None) == 'updated >= "1970-01-01 00:00" ORDER BY updated ASC'


class TestExtractItems:
    @parameterized.expand(
        [
            ("bare_list", [{"id": "1"}], None, [{"id": "1"}]),
            ("wrapped_values", {"values": [{"id": "1"}]}, "values", [{"id": "1"}]),
            ("wrapped_issues", {"issues": [{"id": "1"}]}, "issues", [{"id": "1"}]),
            ("missing_key", {"other": []}, "values", []),
            ("null_key", {"values": None}, "values", []),
            ("dict_without_key", {"id": "1"}, None, []),
        ]
    )
    def test_extract_items(self, _name: str, data: Any, data_key: str | None, expected: list) -> None:
        assert _extract_items(data, data_key) == expected


class TestNormalizeIssue:
    def test_lifts_timestamps_to_top_level(self) -> None:
        issue = {
            "id": "1",
            "fields": {"created": "2026-01-01T00:00:00.000+0000", "updated": "2026-02-01T00:00:00.000+0000"},
        }
        normalized = _normalize_issue(issue)
        assert normalized["created"] == "2026-01-01T00:00:00.000+0000"
        assert normalized["updated"] == "2026-02-01T00:00:00.000+0000"
        # Original nested object is preserved.
        assert normalized["fields"]["created"] == "2026-01-01T00:00:00.000+0000"

    def test_missing_fields_surfaces_error(self) -> None:
        # `fields` is always present with `fields=*all`; a malformed response should fail loudly
        # rather than silently null the `created` partition key.
        with pytest.raises(KeyError):
            _normalize_issue({"id": "1"})


class TestValidateCredentials:
    def test_rejects_invalid_subdomain_without_request(self) -> None:
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.jira.jira.make_tracked_session"
        ) as session:
            ok, status = validate_credentials("acme.evil", "e@x.com", "token")
            assert ok is False
            assert status is None
            session.assert_not_called()

    @parameterized.expand([(200, True), (401, False), (403, False)])
    def test_status_mapping(self, status_code: int, expected_ok: bool) -> None:
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.jira.jira.make_tracked_session"
        ) as session:
            session.return_value.get.return_value = _fake_response({}, status_code=status_code)
            ok, status = validate_credentials("acme", "e@x.com", "token")
            assert ok is expected_ok
            assert status == status_code

    def test_request_exception_returns_false(self) -> None:
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.jira.jira.make_tracked_session"
        ) as session:
            session.return_value.get.side_effect = Exception("boom")
            ok, status = validate_credentials("acme", "e@x.com", "token")
            assert ok is False
            assert status is None


class TestGetRows:
    def _run(
        self, endpoint: str, pages: list[Any], manager: mock.MagicMock, **kwargs: Any
    ) -> list[list[dict[str, Any]]]:
        config = JIRA_ENDPOINTS[endpoint]
        session = mock.MagicMock()
        session.get.side_effect = [_fake_response(page) for page in pages]
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.jira.jira.make_tracked_session",
            return_value=session,
        ):
            batches = list(
                get_rows(
                    config=config,
                    subdomain="acme",
                    email="e@x.com",
                    api_token="token",
                    logger=mock.MagicMock(),
                    resumable_source_manager=manager,
                    **kwargs,
                )
            )
        return batches

    def test_none_pagination_single_request(self) -> None:
        manager = _manager()
        batches = self._run("fields", [[{"id": "f1"}, {"id": "f2"}]], manager)
        assert batches == [[{"id": "f1"}, {"id": "f2"}]]
        manager.save_state.assert_not_called()

    def test_token_pagination_walks_pages(self) -> None:
        manager = _manager()
        pages = [
            {"issues": [{"id": "1", "fields": {"created": "c1", "updated": "u1"}}], "nextPageToken": "tok2"},
            {"issues": [{"id": "2", "fields": {"created": "c2", "updated": "u2"}}], "isLast": True},
        ]
        batches = self._run(
            "issues", pages, manager, should_use_incremental_field=False, db_incremental_field_last_value=None
        )
        assert [row["id"] for batch in batches for row in batch] == ["1", "2"]
        # State is saved with the token for the *next* page after the first batch is yielded.
        manager.save_state.assert_called_once_with(JiraResumeConfig(next_page_token="tok2"))

    def test_token_pagination_resumes_from_saved_token(self) -> None:
        manager = _manager(JiraResumeConfig(next_page_token="tok2"))
        pages = [{"issues": [{"id": "2", "fields": {"created": "c2", "updated": "u2"}}], "isLast": True}]
        batches = self._run("issues", pages, manager, should_use_incremental_field=False)
        assert [row["id"] for batch in batches for row in batch] == ["2"]

    def test_token_pagination_applies_incremental_jql(self) -> None:
        manager = _manager()
        session = mock.MagicMock()
        session.get.side_effect = [_fake_response({"issues": [], "isLast": True})]
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.jira.jira.make_tracked_session",
            return_value=session,
        ):
            list(
                get_rows(
                    config=JIRA_ENDPOINTS["issues"],
                    subdomain="acme",
                    email="e@x.com",
                    api_token="token",
                    logger=mock.MagicMock(),
                    resumable_source_manager=manager,
                    should_use_incremental_field=True,
                    db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58),
                    incremental_field="updated",
                )
            )
        params = session.get.call_args.kwargs["params"]
        assert params["jql"] == 'updated >= "2026-03-03 02:58" ORDER BY updated ASC'
        assert params["fields"] == "*all"

    def test_offset_pagination_walks_pages(self) -> None:
        manager = _manager()
        pages = [
            {"values": [{"id": str(i)} for i in range(100)]},
            {"values": [{"id": "100"}], "isLast": True},
        ]
        batches = self._run("projects", pages, manager)
        assert sum(len(b) for b in batches) == 101
        manager.save_state.assert_called_once_with(JiraResumeConfig(start_at=100))

    def test_offset_pagination_stops_on_short_page(self) -> None:
        manager = _manager()
        pages = [{"values": [{"id": "1"}]}]
        batches = self._run("projects", pages, manager)
        assert batches == [[{"id": "1"}]]
        manager.save_state.assert_not_called()

    def test_offset_pagination_handles_bare_array(self) -> None:
        manager = _manager()
        pages = [[{"accountId": "a1"}]]
        batches = self._run("users", pages, manager)
        assert batches == [[{"accountId": "a1"}]]


class TestJiraSource:
    def test_issues_response_has_partitioning_and_primary_key(self) -> None:
        response = jira_source(
            subdomain="acme",
            email="e@x.com",
            api_token="token",
            endpoint="issues",
            logger=mock.MagicMock(),
            resumable_source_manager=_manager(),
        )
        assert response.name == "issues"
        assert response.primary_keys == ["id"]
        assert response.partition_keys == ["created"]
        assert response.partition_mode == "datetime"
        assert response.sort_mode == "asc"

    @parameterized.expand([("projects", ["id"]), ("users", ["accountId"]), ("fields", ["id"])])
    def test_non_issue_endpoints_have_no_partitioning(self, endpoint: str, primary_key: list[str]) -> None:
        response = jira_source(
            subdomain="acme",
            email="e@x.com",
            api_token="token",
            endpoint=endpoint,
            logger=mock.MagicMock(),
            resumable_source_manager=_manager(),
        )
        assert response.primary_keys == primary_key
        assert response.partition_keys is None
        assert response.partition_mode is None

    def test_unknown_endpoint_raises(self) -> None:
        with pytest.raises(KeyError):
            jira_source(
                subdomain="acme",
                email="e@x.com",
                api_token="token",
                endpoint="nope",
                logger=mock.MagicMock(),
                resumable_source_manager=_manager(),
            )
