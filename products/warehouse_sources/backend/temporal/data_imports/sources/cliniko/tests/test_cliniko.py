import json
from collections.abc import Iterable
from datetime import UTC, date, datetime
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.cliniko.cliniko import (
    ClinikoResumeConfig,
    _to_iso8601,
    base_url,
    cliniko_source,
    get_resource,
    shard_from_api_key,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import Endpoint
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager


class TestShardDetection:
    @pytest.mark.parametrize(
        ("api_key", "expected_shard"),
        [
            ("MS0xLWl4SzYYYYdtR3V2-au1", "au1"),
            ("MS0xLWl4SzYYYYdtR3V2-uk1", "uk1"),
            ("MS0xLWl4SzYYYYdtR3V2-ca1", "ca1"),
            ("MS0xLWl4SzYYYYdtR3V2-us12", "us12"),
            # Keys minted before sharding existed carry no suffix and default to au1.
            ("MS0xLWl4SzYYYYdtR3V2", "au1"),
            # A hyphen that isn't a valid shard suffix (e.g. inside a UUID-like key) is ignored.
            ("some-key-without-a-shard", "au1"),
        ],
    )
    def test_shard_from_api_key(self, api_key: str, expected_shard: str) -> None:
        assert shard_from_api_key(api_key) == expected_shard

    def test_base_url_derives_from_shard(self) -> None:
        assert base_url("test-key-uk1") == "https://api.uk1.cliniko.com/v1"
        assert base_url("test-key") == "https://api.au1.cliniko.com/v1"


class TestToIso8601:
    def test_naive_datetime_treated_as_utc(self) -> None:
        assert _to_iso8601(datetime(2024, 1, 2, 3, 4, 5)) == "2024-01-02T03:04:05Z"

    def test_aware_datetime_converted_to_utc(self) -> None:
        from datetime import timedelta, timezone

        aware = datetime(2024, 1, 2, 13, 0, 0, tzinfo=timezone(timedelta(hours=10)))
        assert _to_iso8601(aware) == "2024-01-02T03:00:00Z"

    def test_date_becomes_midnight_utc(self) -> None:
        assert _to_iso8601(date(2024, 1, 2)) == "2024-01-02T00:00:00Z"

    def test_passthrough_string(self) -> None:
        assert _to_iso8601("2024-01-02T03:04:05Z") == "2024-01-02T03:04:05Z"


class TestGetResource:
    def test_full_refresh_has_no_filter_and_replace_disposition(self) -> None:
        resource = get_resource("patients", should_use_incremental_field=False)

        assert resource["name"] == "patients"
        assert resource["write_disposition"] == "replace"
        # `EndpointResource.endpoint` is typed `str | Endpoint | None`; `get_resource` always sets
        # a dict, so the cast makes that runtime shape explicit for indexing below.
        endpoint = cast(Endpoint, resource["endpoint"])
        assert endpoint["path"] == "/patients"
        assert endpoint["data_selector"] == "patients"
        # `endpoint["params"]` is typed `Optional[dict[...]]`; `get_resource` always sets one, so
        # the cast makes that runtime shape explicit for indexing below.
        params = cast(dict[str, Any], endpoint["params"])
        assert params["q[]"] is None
        assert params["sort"] == "created_at:asc"

    def test_incremental_sets_merge_disposition_and_filter(self) -> None:
        resource = get_resource("invoices", should_use_incremental_field=True)

        assert resource["write_disposition"] == {"disposition": "merge", "strategy": "upsert"}
        endpoint = cast(Endpoint, resource["endpoint"])
        params = cast(dict[str, Any], endpoint["params"])
        assert params["sort"] == "updated_at:asc"
        # `params` values are typed as a resolve/incremental/Any union, so the
        # cast makes the runtime shape (an incremental filter dict, including `convert`) explicit.
        q_filter = cast(dict[str, Any], params["q[]"])
        assert q_filter["type"] == "incremental"
        assert q_filter["convert"](datetime(2024, 1, 1, tzinfo=UTC)) == "updated_at:>2024-01-01T00:00:00Z"


def _make_http_response(body: dict[str, Any], status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    resp.headers["Content-Type"] = "application/json"
    return resp


class TestClinikoSourceResumeBehavior:
    """End-to-end resume behaviour of ``cliniko_source`` via ``rest_api_resource``."""

    def _drive(
        self, endpoint: str, manager: MagicMock, responses: list[Response], should_use_incremental_field: bool = False
    ) -> tuple[list[str], list[dict[str, Any]]]:
        """Drive ``cliniko_source`` with a mocked HTTP session.

        Returns ``(sent_urls, sent_params)`` captured at send-time — the underlying Request
        object is mutated in-place by the paginator between pages.
        """
        sent_urls: list[str] = []
        sent_params: list[dict[str, Any]] = []
        response_iter = iter(responses)

        def fake_send(request: Any, *_args: Any, **_kwargs: Any) -> Response:
            sent_urls.append(request.url)
            sent_params.append(dict(request.params or {}))
            return next(response_iter)

        # `_client_config` now passes an explicit `capture=False` session (see the module docstring
        # on why), so the session comes from cliniko's own `make_tracked_session` import rather than
        # `RESTClient`'s internal default.
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.cliniko.cliniko.make_tracked_session"
        ) as MockSession:
            mock_session = MockSession.return_value
            mock_session.headers = {}
            mock_session.prepare_request.side_effect = lambda req: req
            mock_session.send.side_effect = fake_send

            source_response = cliniko_source(
                api_key="test-key-au1",
                endpoint=endpoint,
                team_id=123,
                job_id="test_job",
                resumable_source_manager=manager,
                should_use_incremental_field=should_use_incremental_field,
                db_incremental_field_last_value=None,
            )
            list(cast(Iterable[Any], source_response.items()))
            return sent_urls, sent_params

    def test_fresh_run_follows_links_next_and_saves_state(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [
            _make_http_response(
                {
                    "patients": [{"id": "1"}],
                    "links": {"next": "https://api.au1.cliniko.com/v1/patients?page=2"},
                }
            ),
            _make_http_response(
                {
                    "patients": [{"id": "2"}],
                    "links": {"next": "https://api.au1.cliniko.com/v1/patients?page=3"},
                }
            ),
            _make_http_response({"patients": [{"id": "3"}], "links": {}}),
        ]
        sent_urls, sent_params = self._drive("patients", manager, responses)

        # The first request is built from the endpoint config (path + params); the
        # paginator only takes over the URL once a `links.next` has been seen.
        assert sent_urls == [
            "https://api.au1.cliniko.com/v1/patients",
            "https://api.au1.cliniko.com/v1/patients?page=2",
            "https://api.au1.cliniko.com/v1/patients?page=3",
        ]
        assert sent_params[0] == {"per_page": 100, "sort": "created_at:asc"}
        # Subsequent requests carry no separate params — the next-page URL is self-contained.
        assert sent_params[1] == {}
        assert sent_params[2] == {}

        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [
            ClinikoResumeConfig(next_url="https://api.au1.cliniko.com/v1/patients?page=2"),
            ClinikoResumeConfig(next_url="https://api.au1.cliniko.com/v1/patients?page=3"),
        ]

    def test_resume_seeds_paginator_with_saved_next_url(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        manager.load_state.return_value = ClinikoResumeConfig(next_url="https://api.au1.cliniko.com/v1/patients?page=5")

        responses = [_make_http_response({"patients": [{"id": "resumed"}], "links": {}})]
        sent_urls, _ = self._drive("patients", manager, responses)

        assert sent_urls == ["https://api.au1.cliniko.com/v1/patients?page=5"]
        manager.load_state.assert_called_once()

    def test_terminal_single_page_does_not_save_state(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [_make_http_response({"patients": [{"id": "only"}], "links": {}})]
        self._drive("patients", manager, responses)

        manager.save_state.assert_not_called()

    def test_incremental_run_sends_updated_at_filter(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [_make_http_response({"invoices": [{"id": "1"}], "links": {}})]
        _, sent_params = self._drive("invoices", manager, responses, should_use_incremental_field=True)

        assert sent_params[0]["q[]"] == "updated_at:>1970-01-01T00:00:00Z"
        assert sent_params[0]["sort"] == "updated_at:asc"


class TestValidateCredentials:
    @pytest.mark.parametrize(("status_code", "expected"), [(200, True), (401, False), (403, False), (429, False)])
    def test_status_code_maps_to_validity(self, status_code: int, expected: bool) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.cliniko.cliniko.make_tracked_session"
        ) as mock_make_session:
            mock_session = mock_make_session.return_value
            mock_session.get.return_value = MagicMock(status_code=status_code)

            assert validate_credentials("test-key-au1") is expected

    def test_request_carries_required_headers_and_shard_url(self) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.cliniko.cliniko.make_tracked_session"
        ) as mock_make_session:
            mock_session = mock_make_session.return_value
            mock_session.get.return_value = MagicMock(status_code=200)

            validate_credentials("test-key-uk1")

            args, kwargs = mock_session.get.call_args
            assert args[0] == "https://api.uk1.cliniko.com/v1/patients?per_page=1"
            assert kwargs["headers"]["Accept"] == "application/json"
            assert "PostHog" in kwargs["headers"]["User-Agent"]
            assert kwargs["headers"]["Authorization"].startswith("Basic ")
