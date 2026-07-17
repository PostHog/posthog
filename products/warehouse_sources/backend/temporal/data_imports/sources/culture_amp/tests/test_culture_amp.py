from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.culture_amp.culture_amp import (
    CultureAmpResumeConfig,
    _format_timestamp,
    culture_amp_source,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.culture_amp.settings import (
    CULTURE_AMP_ENDPOINTS,
    ENDPOINTS,
)

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.culture_amp.culture_amp"


def _make_manager(resume_state: CultureAmpResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _response(body: Any, status_code: int = 200) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.json.return_value = body
    resp.status_code = status_code
    resp.ok = status_code < 400
    return resp


def _token_response() -> mock.MagicMock:
    return _response({"access_token": "tok-1", "expires_in": 3599, "token_type": "Bearer"})


def _page(rows: list[dict[str, Any]], after_key: str | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {"data": rows}
    if after_key:
        body["pagination"] = {"afterKey": after_key, "nextPath": f"/v1/x?cursor={after_key}"}
    return body


class TestFormatTimestamp:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC), "2024-01-02T03:04:05Z"),
            (datetime(2024, 1, 2, 3, 4, 5), "2024-01-02T03:04:05Z"),
            (date(2024, 1, 2), "2024-01-02T00:00:00Z"),
            ("2024-01-02T03:04:05Z", "2024-01-02T03:04:05Z"),
        ],
    )
    def test_formats(self, value, expected):
        assert _format_timestamp(value) == expected


class TestValidateCredentials:
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_valid_credentials_mint_scoped_token(self, mock_session):
        mock_session.return_value.post.return_value = _token_response()

        assert validate_credentials("cid", "sec", "entity-1") is True
        body = mock_session.return_value.post.call_args.kwargs["data"]
        assert body["grant_type"] == "client_credentials"
        assert body["scope"] == "target-entity:entity-1:employees-read"

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_invalid_credentials(self, mock_session):
        response = _response({}, status_code=401)
        response.raise_for_status.side_effect = Exception("401")
        mock_session.return_value.post.return_value = response

        assert validate_credentials("cid", "bad", "entity-1") is False


class TestCursorEndpoints:
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_employees_follow_after_key_until_absent(self, mock_session):
        mock_session.return_value.post.return_value = _token_response()
        mock_session.return_value.get.side_effect = [
            _response(_page([{"id": "e1"}], after_key="k1")),
            _response(_page([{"id": "e2"}])),
        ]

        manager = _make_manager()
        batches = list(get_rows("cid", "sec", "entity-1", "employees", mock.MagicMock(), manager))

        assert [row["id"] for batch in batches for row in batch] == ["e1", "e2"]
        second_url = mock_session.return_value.get.call_args_list[1].args[0]
        assert "cursor=k1" in second_url
        assert [call.args[0].cursor for call in manager.save_state.call_args_list] == ["k1"]

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_incremental_passes_after_date(self, mock_session):
        mock_session.return_value.post.return_value = _token_response()
        mock_session.return_value.get.return_value = _response(_page([]))

        list(
            get_rows(
                "cid",
                "sec",
                "entity-1",
                "performance_cycles",
                mock.MagicMock(),
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC),
            )
        )

        url = mock_session.return_value.get.call_args.args[0]
        assert "after_date=2024-01-02T03%3A04%3A05Z" in url

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_resumes_from_saved_cursor(self, mock_session):
        mock_session.return_value.post.return_value = _token_response()
        mock_session.return_value.get.return_value = _response(_page([{"managerReviewId": "r9"}]))

        manager = _make_manager(CultureAmpResumeConfig(cursor="k9"))
        list(get_rows("cid", "sec", "entity-1", "manager_reviews", mock.MagicMock(), manager))

        url = mock_session.return_value.get.call_args.args[0]
        assert "cursor=k9" in url

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_mid_sync_401_re_mints_token(self, mock_session):
        mock_session.return_value.post.side_effect = [_token_response(), _token_response()]
        mock_session.return_value.get.side_effect = [
            _response({}, status_code=401),
            _response(_page([{"id": "e1"}])),
        ]

        batches = list(get_rows("cid", "sec", "entity-1", "employees", mock.MagicMock(), _make_manager()))

        assert batches == [[{"id": "e1"}]]
        assert mock_session.return_value.post.call_count == 2

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_endpoint_scopes_are_minted_per_stream(self, mock_session):
        mock_session.return_value.post.return_value = _token_response()
        mock_session.return_value.get.return_value = _response(_page([]))

        list(get_rows("cid", "sec", "entity-1", "performance_cycles", mock.MagicMock(), _make_manager()))

        scope = mock_session.return_value.post.call_args.kwargs["data"]["scope"]
        assert scope == "target-entity:entity-1:performance-evaluations-read"


class TestEmployeeDemographicsFanOut:
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_fans_out_per_employee_and_injects_employee_id(self, mock_session):
        mock_session.return_value.post.return_value = _token_response()
        mock_session.return_value.get.side_effect = [
            _response(_page([{"id": "e1"}, {"id": "e2"}])),
            _response(_page([{"name": "department", "value": "eng"}])),
            _response(_page([{"name": "department", "value": "sales"}])),
        ]

        manager = _make_manager()
        batches = list(get_rows("cid", "sec", "entity-1", "employee_demographics", mock.MagicMock(), manager))

        flat = [row for batch in batches for row in batch]
        assert [(r["_employee_id"], r["value"]) for r in flat] == [("e1", "eng"), ("e2", "sales")]
        assert [call.args[0].last_processed_employee_id for call in manager.save_state.call_args_list] == ["e1", "e2"]

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_resumes_from_saved_employee_id(self, mock_session):
        mock_session.return_value.post.return_value = _token_response()
        mock_session.return_value.get.side_effect = [
            _response(_page([{"id": "e1"}, {"id": "e2"}])),
            _response(_page([{"name": "department", "value": "sales"}])),
        ]

        manager = _make_manager(CultureAmpResumeConfig(last_processed_employee_id="e1"))
        batches = list(get_rows("cid", "sec", "entity-1", "employee_demographics", mock.MagicMock(), manager))

        flat = [row for batch in batches for row in batch]
        assert [r["_employee_id"] for r in flat] == ["e2"]
        urls = [call.args[0] for call in mock_session.return_value.get.call_args_list]
        assert len(urls) == 2
        assert "/employees/e2/demographics" in urls[1]

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_resumes_from_beginning_when_saved_employee_removed(self, mock_session):
        # The employee whose id was saved (e9) is gone from the refetched list,
        # so the sync restarts from the top rather than skipping anyone.
        mock_session.return_value.post.return_value = _token_response()
        mock_session.return_value.get.side_effect = [
            _response(_page([{"id": "e1"}, {"id": "e2"}])),
            _response(_page([{"name": "department", "value": "eng"}])),
            _response(_page([{"name": "department", "value": "sales"}])),
        ]

        manager = _make_manager(CultureAmpResumeConfig(last_processed_employee_id="e9"))
        batches = list(get_rows("cid", "sec", "entity-1", "employee_demographics", mock.MagicMock(), manager))

        flat = [row for batch in batches for row in batch]
        assert [r["_employee_id"] for r in flat] == ["e1", "e2"]


class TestCultureAmpSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint):
        config = CULTURE_AMP_ENDPOINTS[endpoint]
        response = culture_amp_source("cid", "sec", "entity-1", endpoint, mock.MagicMock(), _make_manager())

        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        # Incremental streams defer the watermark (ordering undocumented).
        expected_sort = "desc" if config.incremental_fields else "asc"
        assert response.sort_mode == expected_sort
