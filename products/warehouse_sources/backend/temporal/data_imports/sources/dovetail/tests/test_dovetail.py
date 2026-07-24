from collections.abc import Iterable
from datetime import UTC, date, datetime
from typing import Any, Optional, cast

import pytest

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.dovetail.dovetail import (
    DovetailResumeConfig,
    _format_incremental_value,
    dovetail_source,
    get_resource,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.dovetail.settings import DOVETAIL_BASE_URL

BASE_URL = DOVETAIL_BASE_URL


class _FakeResumeManager(ResumableSourceManager[DovetailResumeConfig]):
    # In-memory stand-in — deliberately doesn't call super().__init__, so no Redis is touched.
    def __init__(self, state: Optional[dict[str, Any]] = None) -> None:
        self._state = state
        self.saved: list[dict[str, Any]] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> Optional[DovetailResumeConfig]:
        return DovetailResumeConfig(paginator_state=self._state) if self._state is not None else None

    def save_state(self, data: DovetailResumeConfig) -> None:
        self.saved.append(data.paginator_state)


def _collect_rows(response: SourceResponse) -> list[dict[str, Any]]:
    items = response.items()
    assert isinstance(items, Iterable)
    pages = cast(list[list[dict[str, Any]]], list(items))
    return [row for page in pages for row in page]


class TestValidateCredentials:
    def test_valid_token(self, requests_mock: Any) -> None:
        requests_mock.get(f"{BASE_URL}/v1/token/info", json={"data": {"id": "tok1", "subdomain": "acme"}})

        result = validate_credentials("tok")

        assert result == (True, None)
        assert requests_mock.last_request.headers["Authorization"] == "Bearer tok"

    @pytest.mark.parametrize(
        "status,expected_message",
        [
            (401, "Dovetail rejected the API token. Please generate a new personal API key and reconnect."),
            (403, "Your Dovetail API token does not have permission for this resource."),
            (500, "Dovetail API returned an unexpected status: 500"),
        ],
    )
    def test_status_mapping(self, status: int, expected_message: str, requests_mock: Any) -> None:
        requests_mock.get(f"{BASE_URL}/v1/token/info", status_code=status, json={"errors": []})

        result = validate_credentials("tok")

        assert result == (False, expected_message)

    def test_network_failure(self, requests_mock: Any) -> None:
        import requests as requests_lib

        requests_mock.get(f"{BASE_URL}/v1/token/info", exc=requests_lib.exceptions.ConnectionError)

        result = validate_credentials("tok")

        assert result == (False, "Could not reach Dovetail. Please check your network and try again.")


class TestFormatIncrementalValue:
    @parameterized.expand(
        [
            ("naive_datetime", datetime(2024, 1, 1, 12, 0, 0), "2024-01-01T12:00:00+00:00"),
            ("aware_datetime", datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC), "2024-01-01T12:00:00+00:00"),
            ("date_only", date(2024, 1, 1), "2024-01-01T00:00:00+00:00"),
            ("string_passthrough", "2024-01-01T00:00:00Z", "2024-01-01T00:00:00Z"),
        ]
    )
    def test_format(self, _name: str, value: Any, expected: str) -> None:
        assert _format_incremental_value(value) == expected


class TestGetResource:
    def test_full_refresh_endpoint_has_no_filter_param(self) -> None:
        resource = cast(
            dict[str, Any], get_resource("Projects", should_use_incremental_field=False, incremental_field=None)
        )

        assert resource["name"] == "Projects"
        assert resource["write_disposition"] == "replace"
        endpoint = resource["endpoint"]
        assert endpoint["path"] == "/v1/projects"
        assert endpoint["data_selector"] == "data"
        assert endpoint["params"] == {"page[limit]": 100, "sort": "created_at:asc"}
        assert endpoint["paginator"] == {
            "type": "cursor",
            "cursor_path": "page.next_cursor",
            "cursor_param": "page[start_cursor]",
        }
        assert resource["table_format"] == "delta"

    @parameterized.expand([("Tags",), ("Contacts",), ("Users",)])
    def test_other_full_refresh_endpoints_have_no_filter_param(self, endpoint_name: str) -> None:
        resource = cast(
            dict[str, Any], get_resource(endpoint_name, should_use_incremental_field=True, incremental_field=None)
        )
        # These endpoints have no incremental_fields declared, so requesting incremental sync
        # is a no-op: no filter param is added and the write disposition stays full replace.
        assert "filter[created_at][gte]" not in resource["endpoint"]["params"]
        assert resource["write_disposition"] == "replace"

    def test_incremental_endpoint_full_refresh_sends_null_filter(self) -> None:
        resource = cast(
            dict[str, Any], get_resource("Data", should_use_incremental_field=False, incremental_field=None)
        )

        assert resource["write_disposition"] == "replace"
        assert resource["endpoint"]["params"]["filter[created_at][gte]"] is None

    def test_incremental_endpoint_incremental_sends_incremental_param(self) -> None:
        resource = cast(dict[str, Any], get_resource("Data", should_use_incremental_field=True, incremental_field=None))

        assert resource["write_disposition"] == {"disposition": "merge", "strategy": "upsert"}
        param = resource["endpoint"]["params"]["filter[created_at][gte]"]
        assert param["type"] == "incremental"
        assert param["cursor_path"] == "created_at"
        assert param["convert"] is _format_incremental_value

    def test_highlights_defaults_to_created_at_when_no_field_chosen(self) -> None:
        resource = cast(
            dict[str, Any], get_resource("Highlights", should_use_incremental_field=True, incremental_field=None)
        )
        assert "filter[created_at][gte]" in resource["endpoint"]["params"]


class TestDovetailSourceTopLevel:
    def test_two_page_full_refresh_sync(self, requests_mock: Any) -> None:
        requests_mock.get(
            f"{BASE_URL}/v1/projects",
            [
                {
                    "json": {
                        "data": [{"id": "p1", "title": "First"}],
                        "page": {"total_count": 2, "has_more": True, "next_cursor": "CURSOR1"},
                    }
                },
                {
                    "json": {
                        "data": [{"id": "p2", "title": "Second"}],
                        "page": {"total_count": 2, "has_more": False, "next_cursor": None},
                    }
                },
            ],
        )

        response = dovetail_source(
            api_key="tok",
            endpoint="Projects",
            team_id=1,
            job_id="job-1",
            resumable_source_manager=_FakeResumeManager(),
        )
        rows = _collect_rows(response)

        assert rows == [{"id": "p1", "title": "First"}, {"id": "p2", "title": "Second"}]
        assert response.primary_keys == ["id"]
        assert response.sort_mode == "asc"
        assert response.partition_keys == ["created_at"]

        first_request, second_request = requests_mock.request_history
        assert first_request.qs["page[limit]"] == ["100"]
        assert "page[start_cursor]" not in first_request.qs
        # requests_mock's `.qs` lowercases query values.
        assert second_request.qs["page[start_cursor]"] == ["cursor1"]

    def test_incremental_sync_sends_filter(self, requests_mock: Any) -> None:
        requests_mock.get(
            f"{BASE_URL}/v1/data",
            json={
                "data": [{"id": "d1", "created_at": "2024-01-02T00:00:00Z"}],
                "page": {"total_count": 1, "has_more": False, "next_cursor": None},
            },
        )

        response = dovetail_source(
            api_key="tok",
            endpoint="Data",
            team_id=1,
            job_id="job-1",
            resumable_source_manager=_FakeResumeManager(),
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 1, 1, tzinfo=UTC),
            incremental_field="created_at",
        )
        rows = _collect_rows(response)

        assert rows == [{"id": "d1", "created_at": "2024-01-02T00:00:00Z"}]
        request = requests_mock.request_history[0]
        assert request.qs["filter[created_at][gte]"] == ["2024-01-01t00:00:00+00:00"]

    def test_resumes_from_saved_cursor(self, requests_mock: Any) -> None:
        requests_mock.get(
            f"{BASE_URL}/v1/data",
            json={
                "data": [{"id": "d2"}],
                "page": {"total_count": 1, "has_more": False, "next_cursor": None},
            },
        )
        manager = _FakeResumeManager(state={"cursor": "SAVED_CURSOR"})

        response = dovetail_source(
            api_key="tok",
            endpoint="Data",
            team_id=1,
            job_id="job-1",
            resumable_source_manager=manager,
        )
        _collect_rows(response)

        request = requests_mock.request_history[0]
        assert request.qs["page[start_cursor]"] == ["saved_cursor"]

    def test_saves_checkpoint_after_batch(self, requests_mock: Any) -> None:
        requests_mock.get(
            f"{BASE_URL}/v1/data",
            json={
                "data": [{"id": "d1"}],
                "page": {"total_count": 2, "has_more": True, "next_cursor": "NEXT"},
            },
        )
        manager = _FakeResumeManager()

        response = dovetail_source(
            api_key="tok",
            endpoint="Data",
            team_id=1,
            job_id="job-1",
            resumable_source_manager=manager,
        )
        # The checkpoint for a page is only saved once the generator resumes past its `yield`
        # (see rest_client.paginate), so fetch the first page and then advance once more to
        # observe the checkpoint saved right after it.
        items = response.items()
        assert isinstance(items, Iterable)
        iterator = iter(items)
        next(iterator)
        next(iterator)

        assert manager.saved == [{"cursor": "NEXT"}]


class TestDovetailSourceFanout:
    def test_doc_comments_injects_parent_doc_id(self, requests_mock: Any) -> None:
        requests_mock.get(
            f"{BASE_URL}/v1/docs",
            json={
                "data": [{"id": "doc1"}, {"id": "doc2"}],
                "page": {"total_count": 2, "has_more": False, "next_cursor": None},
            },
        )
        requests_mock.get(
            f"{BASE_URL}/v1/docs/doc1/comments",
            json={
                "data": [{"id": "c1", "body": "hello"}],
                "page": {"total_count": 1, "has_more": False, "next_cursor": None},
            },
        )
        requests_mock.get(
            f"{BASE_URL}/v1/docs/doc2/comments",
            json={
                "data": [{"id": "c2", "body": "world"}],
                "page": {"total_count": 1, "has_more": False, "next_cursor": None},
            },
        )

        response = dovetail_source(
            api_key="tok",
            endpoint="DocComments",
            team_id=1,
            job_id="job-1",
            resumable_source_manager=_FakeResumeManager(),
        )
        rows = _collect_rows(response)

        assert rows == [
            {"id": "c1", "body": "hello", "doc_id": "doc1"},
            {"id": "c2", "body": "world", "doc_id": "doc2"},
        ]
        assert response.primary_keys == ["doc_id", "id"]
