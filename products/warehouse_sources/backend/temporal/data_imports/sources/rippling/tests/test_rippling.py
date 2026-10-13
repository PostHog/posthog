import json
from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.rippling.rippling import (
    PAGE_SIZE,
    RipplingResumeConfig,
    _absolutize_next_url,
    _build_params,
    _format_filter_timestamp,
    rippling_source,
    validate_credentials,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the rippling module.
RIPPLING_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.rippling.rippling.make_tracked_session"
)


def _response(items: list[dict[str, Any]], next_link: str | None = None) -> Response:
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps({"results": items, "next_link": next_link}).encode()
    return resp


def _make_manager(resume_state: RipplingResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and capture each request's URL + params AT SEND TIME.

    ``request.params`` / ``request.url`` are mutated in place across pages (the paginator
    rewrites ``url`` to the next-page link), so snapshot a copy when each request is prepared.
    """
    session.headers = {}
    snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        snapshots.append({"url": request.url, "params": dict(request.params or {})})
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return snapshots


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestFormatFilterTimestamp:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (datetime(2024, 10, 1, 3, 4, 5, tzinfo=UTC), "2024-10-01T03:04:05"),
            (datetime(2024, 10, 1, 3, 4, 5), "2024-10-01T03:04:05"),
            (date(2024, 10, 1), "2024-10-01T00:00:00"),
            ("2024-10-01T00:00:00", "2024-10-01T00:00:00"),
        ],
    )
    def test_format_values(self, value, expected):
        assert _format_filter_timestamp(value) == expected


class TestBuildParams:
    def test_incremental_builds_odata_filter_and_sort(self):
        params = _build_params(
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 10, 1, tzinfo=UTC),
            incremental_field="updated_at",
        )

        assert params["filter"] == "updated_at ge 2024-10-01T00:00:00"
        assert params["order_by"] == "updated_at"
        assert params["limit"] == PAGE_SIZE


class TestAbsolutizeNextUrl:
    @pytest.mark.parametrize(
        "next_link",
        [
            "https://attacker.example/workers",
            "//attacker.example/workers",
            "http://rest.ripplingapis.com/workers",
            "https://rest.ripplingapis.com.attacker.example/workers",
        ],
    )
    def test_rejects_off_domain_links(self, next_link):
        with pytest.raises(ValueError):
            _absolutize_next_url(next_link)


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected",
        [
            (200, True),
            # A valid token without the companies.read scope still 403s; only 401
            # means the token itself is bad.
            (403, True),
            (401, False),
        ],
    )
    @mock.patch(RIPPLING_SESSION_PATCH)
    def test_validate_credentials_status_mapping(self, mock_session, status_code, expected):
        response = mock.MagicMock()
        response.status_code = status_code
        mock_session.return_value.get.return_value = response

        assert validate_credentials("token") is expected


class TestGetRows:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_absolute_next_link_used_as_is(self, MockSession):
        session = MockSession.return_value
        absolute = "https://rest.ripplingapis.com/workers?cursor=xyz"
        snapshots = _wire(session, [_response([{"id": "1"}], next_link=absolute), _response([])])

        _rows(rippling_source("token", "workers", team_id=1, job_id="j", resumable_source_manager=_make_manager()))

        assert snapshots[1]["url"] == absolute

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_state(self, MockSession):
        session = MockSession.return_value
        resume_url = "https://rest.ripplingapis.com/workers?cursor=resume"
        snapshots = _wire(session, [_response([{"id": "9"}])])

        manager = _make_manager(RipplingResumeConfig(next_url=resume_url))
        _rows(rippling_source("token", "workers", team_id=1, job_id="j", resumable_source_manager=manager))

        assert snapshots[0]["url"] == resume_url

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_off_domain_next_link_raises(self, MockSession):
        session = MockSession.return_value
        _wire(session, [_response([{"id": "1"}], next_link="https://attacker.example/workers")])

        with pytest.raises(ValueError, match="off-domain"):
            _rows(rippling_source("token", "workers", team_id=1, job_id="j", resumable_source_manager=_make_manager()))
