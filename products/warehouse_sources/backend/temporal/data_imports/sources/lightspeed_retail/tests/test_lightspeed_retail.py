import json
from collections.abc import Iterable
from typing import Any, cast

import pytest
from unittest import mock

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.lightspeed_retail.constants import (
    LIGHTSPEED_RETAIL_API_VERSION_2_0,
    LIGHTSPEED_RETAIL_API_VERSION_2026_01,
    LIGHTSPEED_RETAIL_API_VERSION_2026_07,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.lightspeed_retail.lightspeed_retail import (
    LightspeedRetailResumeConfig,
    _clean_domain_prefix,
    _to_version,
    lightspeed_retail_source,
    validate_credentials,
)

SUPPORTED_API_VERSIONS = [
    LIGHTSPEED_RETAIL_API_VERSION_2_0,
    LIGHTSPEED_RETAIL_API_VERSION_2026_01,
    LIGHTSPEED_RETAIL_API_VERSION_2026_07,
]

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the lightspeed module.
LR_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.lightspeed_retail.lightspeed_retail.make_tracked_session"


def _response(items: list[dict[str, Any]], max_version: int | None = None) -> Response:
    body: dict[str, Any] = {"data": items}
    if max_version is not None:
        body["version"] = {"min": 0, "max": max_version}
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    return resp


def _make_manager(resume_state: LightspeedRetailResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and capture each request's params AT SEND TIME.

    ``request.params`` is one dict mutated in place across pages, so snapshot a copy
    when each request is prepared instead of reading it after the run.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        prepared = mock.MagicMock()
        prepared.url = request.url
        return prepared

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots


def _run(manager: mock.MagicMock, endpoint: str = "sales", **kwargs: Any) -> list[Any]:
    kwargs.setdefault("api_version", LIGHTSPEED_RETAIL_API_VERSION_2026_01)
    response = lightspeed_retail_source(
        "mystore", "token", endpoint, team_id=1, job_id="j", resumable_source_manager=manager, **kwargs
    )
    return list(cast("Iterable[Any]", response.items()))


class TestCleanDomainPrefix:
    @pytest.mark.parametrize("value", ["", "my store", "store?x=1", "../evil"])
    def test_invalid_prefixes_raise(self, value):
        with pytest.raises(ValueError):
            _clean_domain_prefix(value)


class TestToVersion:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (None, None),
            (12345, 12345),
            ("12345", 12345),
            (123.9, 123),
            ("not-a-number", None),
            (True, None),
        ],
    )
    def test_to_version_values(self, value, expected):
        assert _to_version(value) == expected


class TestValidateCredentials:
    @pytest.mark.parametrize("api_version", SUPPORTED_API_VERSIONS)
    @mock.patch(LR_SESSION_PATCH)
    def test_validate_credentials_probes_the_pinned_version(self, mock_session, api_version):
        mock_session.return_value.get.return_value.status_code = 200

        assert validate_credentials("mystore", "token", api_version) is True

        url = mock_session.return_value.get.call_args.args[0]
        assert url.startswith(f"https://mystore.retail.lightspeed.app/api/{api_version}/outlets")

    @mock.patch(LR_SESSION_PATCH)
    def test_validate_credentials_rejects_bad_prefix_without_request(self, mock_session):
        assert validate_credentials("my store!", "token", LIGHTSPEED_RETAIL_API_VERSION_2026_01) is False
        mock_session.return_value.get.assert_not_called()


class TestGetRows:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_starts_from_watermark_version(self, mock_session):
        params = _wire(mock_session.return_value, [_response([])])

        manager = _make_manager()
        _run(manager, should_use_incremental_field=True, db_incremental_field_last_value=777)

        assert params[0]["after"] == 777

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_missing_version_block_falls_back_to_page_max(self, mock_session):
        params = _wire(
            mock_session.return_value,
            [
                _response([{"id": "1", "version": 10}]),
                _response([]),
            ],
        )

        manager = _make_manager()
        batches = _run(manager)

        assert [item["id"] for batch in batches for item in batch] == ["1"]
        assert params[1]["after"] == 10

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_non_advancing_cursor_stops_instead_of_looping(self, mock_session):
        # Page with no version block and versions <= the current cursor must
        # terminate rather than refetch the same window forever.
        session = mock_session.return_value
        _wire(session, [_response([{"id": "1", "version": 5}])])

        manager = _make_manager(LightspeedRetailResumeConfig(after=5))
        batches = _run(manager)

        assert [item["id"] for batch in batches for item in batch] == ["1"]
        assert session.send.call_count == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_first_page_advances_when_fallback_version_is_zero(self, mock_session):
        # First page (no saved cursor) with no version block and page max of 0
        # must still advance rather than treat 0 as "no cursor".
        session = mock_session.return_value
        params = _wire(
            session,
            [
                _response([{"id": "1", "version": 0}]),
                _response([]),
            ],
        )

        manager = _make_manager()
        batches = _run(manager)

        assert [item["id"] for batch in batches for item in batch] == ["1"]
        assert session.send.call_count == 2
        assert params[1]["after"] == 0
