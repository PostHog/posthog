from typing import Any

import pytest
from unittest import mock

import pyarrow as pa
import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.batcher import Batcher
from products.warehouse_sources.backend.temporal.data_imports.sources.apify_dataset import apify_dataset
from products.warehouse_sources.backend.temporal.data_imports.sources.apify_dataset.apify_dataset import (
    ApifyResumeConfig,
    ApifyRetryableError,
    _fetch_page,
    _items_url,
    apify_dataset_source,
    get_rows,
    validate_credentials,
)


def _response(status_code: int, *, json_body: Any = None, headers: dict[str, str] | None = None) -> mock.Mock:
    response = mock.Mock(spec=requests.Response)
    response.status_code = status_code
    response.ok = 200 <= status_code < 300
    response.text = ""
    response.headers = headers or {}
    response.json.return_value = json_body
    response.raise_for_status.side_effect = (
        None if response.ok else requests.HTTPError(f"{status_code} Client Error", response=response)
    )
    return response


def _small_batcher(**kwargs: Any) -> Batcher:
    # Force a tiny chunk so a yield fires after a couple of rows without building thousands of dicts.
    return Batcher(logger=kwargs["logger"], chunk_size=2, chunk_size_bytes=kwargs["chunk_size_bytes"])


@pytest.fixture(autouse=True)
def _no_sleep():
    # The tenacity retry decorator sleeps between attempts; zero it so retry tests stay instant.
    with mock.patch("time.sleep", return_value=None):
        yield


class TestItemsUrl:
    @parameterized.expand(
        [
            ("first_page", "ds1", 0, 1000),
            ("offset_page", "ds1", 2000, 500),
        ]
    )
    def test_items_url_contains_pagination_params(self, _name: str, dataset_id: str, offset: int, limit: int) -> None:
        url = _items_url(dataset_id, offset, limit)
        assert url.startswith(f"https://api.apify.com/v2/datasets/{dataset_id}/items?")
        assert f"offset={offset}" in url
        assert f"limit={limit}" in url
        assert "format=json" in url

    def test_items_url_encodes_dataset_id_as_path_segment(self) -> None:
        # A crafted dataset_id must not be able to inject extra path segments or query params
        # (e.g. dropping the enforced offset/limit); it has to stay a single encoded path segment.
        url = _items_url("evil/items?format=json#", 0, 1000)
        assert url.startswith("https://api.apify.com/v2/datasets/evil%2Fitems%3Fformat%3Djson%23/items?")
        assert "offset=0" in url
        assert "limit=1000" in url


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True),
            ("unauthorized", 401, False),
            ("forbidden", 403, False),
            ("not_found", 404, False),
            ("unexpected", 500, False),
        ]
    )
    def test_status_code_mapping(self, _name: str, status_code: int, expected_ok: bool) -> None:
        session = mock.Mock()
        session.get.return_value = _response(status_code)
        with mock.patch.object(apify_dataset, "make_tracked_session", return_value=session):
            ok, error = validate_credentials("token", "ds1")
        assert ok is expected_ok
        assert (error is None) is expected_ok

    def test_network_error_is_not_valid(self) -> None:
        session = mock.Mock()
        session.get.side_effect = requests.ConnectionError("boom")
        with mock.patch.object(apify_dataset, "make_tracked_session", return_value=session):
            ok, error = validate_credentials("token", "ds1")
        assert ok is False
        assert error is not None


class TestFetchPage:
    def test_reads_total_from_pagination_header(self) -> None:
        session = mock.Mock()
        session.get.return_value = _response(200, json_body=[{"a": 1}], headers={"X-Apify-Pagination-Total": "42"})
        items, total = _fetch_page(session, "https://api.apify.com/v2/datasets/ds1/items", {}, mock.Mock())
        assert items == [{"a": 1}]
        assert total == 42

    def test_total_falls_back_to_item_count_without_header(self) -> None:
        session = mock.Mock()
        session.get.return_value = _response(200, json_body=[{"a": 1}, {"a": 2}], headers={})
        items, total = _fetch_page(session, "https://api.apify.com/v2/datasets/ds1/items", {}, mock.Mock())
        assert total == 2

    @parameterized.expand([("empty", ""), ("non_numeric", "abc")])
    def test_total_falls_back_to_item_count_for_malformed_header(self, _name: str, header_value: str) -> None:
        session = mock.Mock()
        session.get.return_value = _response(
            200, json_body=[{"a": 1}, {"a": 2}], headers={"X-Apify-Pagination-Total": header_value}
        )
        items, total = _fetch_page(session, "https://api.apify.com/v2/datasets/ds1/items", {}, mock.Mock())
        assert total == 2

    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    def test_retryable_statuses_eventually_reraise(self, _name: str, status_code: int) -> None:
        session = mock.Mock()
        session.get.return_value = _response(status_code)
        with pytest.raises(ApifyRetryableError):
            _fetch_page(session, "https://api.apify.com/v2/datasets/ds1/items", {}, mock.Mock())
        assert session.get.call_count == 5

    def test_retries_then_succeeds(self) -> None:
        session = mock.Mock()
        session.get.side_effect = [
            _response(503),
            _response(200, json_body=[{"a": 1}], headers={"X-Apify-Pagination-Total": "1"}),
        ]
        items, total = _fetch_page(session, "https://api.apify.com/v2/datasets/ds1/items", {}, mock.Mock())
        assert items == [{"a": 1}]
        assert session.get.call_count == 2

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_raise_immediately(self, _name: str, status_code: int) -> None:
        session = mock.Mock()
        session.get.return_value = _response(status_code)
        with pytest.raises(requests.HTTPError):
            _fetch_page(session, "https://api.apify.com/v2/datasets/ds1/items", {}, mock.Mock())
        assert session.get.call_count == 1

    def test_non_list_body_raises_without_retrying(self) -> None:
        session = mock.Mock()
        session.get.return_value = _response(200, json_body={"error": "nope"})
        # A non-list 200 body is a permanent contract violation, so it raises ValueError (not a
        # retryable error) and exits immediately rather than waiting through all retry attempts.
        with pytest.raises(ValueError):
            _fetch_page(session, "https://api.apify.com/v2/datasets/ds1/items", {}, mock.Mock())
        assert session.get.call_count == 1


def _resume_manager(saved: ApifyResumeConfig | None = None) -> mock.Mock:
    manager = mock.Mock()
    manager.can_resume.return_value = saved is not None
    manager.load_state.return_value = saved
    return manager


def _collect_rows(tables: list[pa.Table]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for table in tables:
        rows.extend(table.to_pylist())
    return rows


class TestGetRows:
    def test_paginates_until_offset_reaches_total(self) -> None:
        manager = _resume_manager()
        pages = [
            ([{"i": 0}, {"i": 1}], 5),
            ([{"i": 2}, {"i": 3}], 5),
            ([{"i": 4}], 5),
        ]
        with (
            mock.patch.object(apify_dataset, "make_tracked_session", return_value=mock.Mock()),
            mock.patch.object(apify_dataset, "PAGE_SIZE", 2),
            mock.patch.object(apify_dataset, "_fetch_page", side_effect=pages) as fetch,
        ):
            rows = _collect_rows(list(get_rows("token", "ds1", mock.Mock(), manager)))

        assert fetch.call_count == 3
        assert [r["i"] for r in rows] == [0, 1, 2, 3, 4]
        # The offset advances on each request: 0 -> 2 -> 4.
        offsets = [call.args[1] for call in fetch.call_args_list]
        assert "offset=0" in offsets[0]
        assert "offset=2" in offsets[1]
        assert "offset=4" in offsets[2]

    def test_resumes_from_saved_offset(self) -> None:
        manager = _resume_manager(ApifyResumeConfig(offset=2))
        with (
            mock.patch.object(apify_dataset, "make_tracked_session", return_value=mock.Mock()),
            mock.patch.object(apify_dataset, "PAGE_SIZE", 2),
            mock.patch.object(apify_dataset, "_fetch_page", side_effect=[([{"i": 2}], 3)]) as fetch,
        ):
            list(get_rows("token", "ds1", mock.Mock(), manager))

        assert "offset=2" in fetch.call_args_list[0].args[1]

    def test_saves_state_after_yield_with_next_offset(self) -> None:
        manager = _resume_manager()
        pages = [
            ([{"i": 0}, {"i": 1}], 4),
            ([{"i": 2}, {"i": 3}], 4),
        ]
        with (
            mock.patch.object(apify_dataset, "make_tracked_session", return_value=mock.Mock()),
            mock.patch.object(apify_dataset, "PAGE_SIZE", 2),
            mock.patch.object(apify_dataset, "Batcher", _small_batcher),
            mock.patch.object(apify_dataset, "_fetch_page", side_effect=pages),
        ):
            list(get_rows("token", "ds1", mock.Mock(), manager))

        # After the first page (offset advanced to 2) more rows remain, so state is saved at offset 2.
        saved_offsets = [call.args[0].offset for call in manager.save_state.call_args_list]
        assert 2 in saved_offsets

    def test_does_not_save_state_on_final_page(self) -> None:
        manager = _resume_manager()
        with (
            mock.patch.object(apify_dataset, "make_tracked_session", return_value=mock.Mock()),
            mock.patch.object(apify_dataset, "PAGE_SIZE", 2),
            mock.patch.object(apify_dataset, "Batcher", _small_batcher),
            mock.patch.object(apify_dataset, "_fetch_page", side_effect=[([{"i": 0}, {"i": 1}], 2)]),
        ):
            list(get_rows("token", "ds1", mock.Mock(), manager))

        manager.save_state.assert_not_called()

    def test_empty_dataset_yields_nothing(self) -> None:
        manager = _resume_manager()
        with (
            mock.patch.object(apify_dataset, "make_tracked_session", return_value=mock.Mock()),
            mock.patch.object(apify_dataset, "_fetch_page", side_effect=[([], 0)]),
        ):
            tables = list(get_rows("token", "ds1", mock.Mock(), manager))

        assert tables == []


class TestApifyDatasetSource:
    def test_source_response_shape(self) -> None:
        response = apify_dataset_source("token", "ds1", "dataset_items", mock.Mock(), _resume_manager())
        assert response.name == "dataset_items"
        # Arbitrary dataset rows have no unique key, so the table is full-refresh only.
        assert response.primary_keys is None
        assert response.sort_mode == "asc"
