from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.cohere import cohere
from products.warehouse_sources.backend.temporal.data_imports.sources.cohere.cohere import (
    CohereError,
    CohereRetryableError,
    _paginate_offset,
    _paginate_page_token,
    cohere_source,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.cohere.settings import (
    COHERE_ENDPOINTS,
    CohereEndpointConfig,
    CoherePagination,
)


class TestValidateCredentials:
    @parameterized.expand([("ok", 200, True), ("unauthorized", 401, False), ("forbidden", 403, False)])
    def test_status_maps_to_bool(self, _name: str, status_code: int, expected: bool) -> None:
        response = MagicMock()
        response.status_code = status_code
        session = MagicMock()
        session.get.return_value = response
        with patch.object(cohere, "make_tracked_session", return_value=session):
            assert validate_credentials("test-key") is expected

    def test_network_error_is_false(self) -> None:
        session = MagicMock()
        session.get.side_effect = requests.ConnectionError("boom")
        with patch.object(cohere, "make_tracked_session", return_value=session):
            assert validate_credentials("test-key") is False

    def test_session_redacts_api_key(self) -> None:
        # The bearer token must be masked in captured HTTP samples and logged URLs.
        response = MagicMock()
        response.status_code = 200
        session = MagicMock()
        session.get.return_value = response
        with patch.object(cohere, "make_tracked_session", return_value=session) as make_session:
            validate_credentials("secret-key")
        assert make_session.call_args.kwargs["redact_values"] == ("secret-key",)


class TestFetchPage:
    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    def test_retryable_status_raises_retryable_error(self, _name: str, status_code: int) -> None:
        response = MagicMock()
        response.status_code = status_code
        session = MagicMock()
        session.get.return_value = response
        with patch.object(cohere._fetch_page.retry, "sleep", lambda *_: None):  # type: ignore[attr-defined]
            with pytest.raises(CohereRetryableError):
                cohere._fetch_page(session, "https://api.cohere.com/v1/datasets", {}, {}, MagicMock())

    @parameterized.expand([("read_timeout", requests.ReadTimeout()), ("connection", requests.ConnectionError())])
    def test_transient_errors_are_retried_then_succeed(self, _name: str, transient: Exception) -> None:
        good = MagicMock()
        good.status_code = 200
        good.ok = True
        good.json.return_value = {"datasets": []}
        session = MagicMock()
        session.get.side_effect = [transient, good]
        with patch.object(cohere._fetch_page.retry, "sleep", lambda *_: None):  # type: ignore[attr-defined]
            result = cohere._fetch_page(session, "https://api.cohere.com/v1/datasets", {}, {}, MagicMock())
        assert result == {"datasets": []}

    def test_unauthorized_raises_for_status(self) -> None:
        response = MagicMock()
        response.status_code = 401
        response.ok = False
        response.raise_for_status.side_effect = requests.HTTPError(
            "401 Client Error: Unauthorized", response=requests.Response()
        )
        session = MagicMock()
        session.get.return_value = response
        with pytest.raises(requests.HTTPError):
            cohere._fetch_page(session, "https://api.cohere.com/v1/datasets", {}, {}, MagicMock())


class TestPaginateOffset:
    def test_stops_on_short_page(self) -> None:
        config = CohereEndpointConfig(
            name="datasets", path="/datasets", data_key="datasets", pagination=CoherePagination.OFFSET, page_size=2
        )
        requested_offsets: list[int] = []

        def fake_fetch(_session: Any, _url: str, _headers: Any, params: dict[str, Any], _logger: Any) -> dict:
            requested_offsets.append(params["offset"])
            rows = {0: [{"id": "a"}, {"id": "b"}], 2: [{"id": "c"}]}.get(params["offset"], [])
            return {"datasets": rows}

        with patch.object(cohere, "_fetch_page", side_effect=fake_fetch):
            pages = list(_paginate_offset(MagicMock(), "url", {}, config, MagicMock()))

        assert [r["id"] for page in pages for r in page] == ["a", "b", "c"]
        # A full page advances the offset; the short second page ends pagination without a third request.
        assert requested_offsets == [0, 2]

    def test_empty_first_page_yields_nothing(self) -> None:
        config = CohereEndpointConfig(
            name="datasets", path="/datasets", data_key="datasets", pagination=CoherePagination.OFFSET, page_size=2
        )
        with patch.object(cohere, "_fetch_page", return_value={"datasets": []}):
            assert list(_paginate_offset(MagicMock(), "url", {}, config, MagicMock())) == []


class TestPaginatePageToken:
    def test_follows_next_page_token(self) -> None:
        config = COHERE_ENDPOINTS["finetuned_models"]
        requested_tokens: list[Any] = []

        def fake_fetch(_session: Any, _url: str, _headers: Any, params: dict[str, Any], _logger: Any) -> dict:
            token = params.get("page_token")
            requested_tokens.append(token)
            if token is None:
                return {"finetuned_models": [{"id": "a"}], "next_page_token": "t2"}
            return {"finetuned_models": [{"id": "b"}]}

        with patch.object(cohere, "_fetch_page", side_effect=fake_fetch):
            pages = list(_paginate_page_token(MagicMock(), "url", {}, config, MagicMock()))

        assert [r["id"] for page in pages for r in page] == ["a", "b"]
        # First request has no token; the second carries the token from the first response.
        assert requested_tokens == [None, "t2"]


class TestGetRows:
    def test_unpaginated_endpoint_makes_single_request(self) -> None:
        calls: list[Any] = []

        def fake_fetch(_session: Any, url: str, _headers: Any, _params: Any, _logger: Any) -> dict:
            calls.append(url)
            return {"embed_jobs": [{"job_id": "j1"}, {"job_id": "j2"}]}

        with patch.object(cohere, "_fetch_page", side_effect=fake_fetch):
            with patch.object(cohere, "make_tracked_session", return_value=MagicMock()):
                rows = [r for page in get_rows("test-key", "embed_jobs", MagicMock()) for r in page]

        assert [r["job_id"] for r in rows] == ["j1", "j2"]
        assert len(calls) == 1

    def test_missing_envelope_key_raises_instead_of_emptying(self) -> None:
        # A successful response whose shape lacks the envelope key must fail loudly, not be
        # treated as an empty page that clears the full-refresh table.
        with patch.object(cohere, "_fetch_page", return_value={"unexpected": []}):
            with patch.object(cohere, "make_tracked_session", return_value=MagicMock()):
                with pytest.raises(CohereError):
                    list(get_rows("test-key", "datasets", MagicMock()))

    def test_session_redacts_api_key(self) -> None:
        with patch.object(cohere, "_fetch_page", return_value={"embed_jobs": []}):
            with patch.object(cohere, "make_tracked_session", return_value=MagicMock()) as make_session:
                list(get_rows("secret-key", "embed_jobs", MagicMock()))
        assert make_session.call_args.kwargs["redact_values"] == ("secret-key",)


class TestCohereSource:
    @parameterized.expand([(e,) for e in COHERE_ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        config = COHERE_ENDPOINTS[endpoint]
        response = cohere_source(api_key="test-key", endpoint=endpoint, logger=MagicMock())
        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
            assert response.partition_count == 1
            assert response.partition_size == 1
        else:
            # The model catalog has no creation timestamp, so it must stay fully unpartitioned.
            # partition_count/size are left None too: a stray count makes the writer fall back to
            # primary_keys and md5-partition by name.
            assert response.partition_mode is None
            assert response.partition_keys is None
            assert response.partition_count is None
            assert response.partition_size is None

    def test_models_primary_key_is_name_not_id(self) -> None:
        # Model catalog rows are keyed by name; there is no id field to dedupe on.
        assert cohere_source(api_key="test-key", endpoint="models", logger=MagicMock()).primary_keys == ["name"]
