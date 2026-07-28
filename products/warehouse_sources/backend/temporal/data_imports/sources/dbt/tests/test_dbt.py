from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import parse_qs, urlparse

import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.dbt.dbt import (
    DbtHostNotAllowedError,
    DbtResumeConfig,
    _coerce_datetime,
    dbt_source,
    get_base_url,
    get_endpoint_permissions,
    get_rows,
    validate_credentials,
)

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.dbt.dbt"


def _response(*, status_code: int = 200, json_data: Any = None, text: str = "") -> mock.MagicMock:
    response = mock.MagicMock()
    response.status_code = status_code
    response.ok = 200 <= status_code < 400
    response.is_redirect = status_code in (302, 303, 307)
    response.is_permanent_redirect = status_code in (301, 308)
    response.text = text
    response.json.return_value = json_data
    return response


def _page(rows: list[dict], *, count: Optional[int] = None, total_count: Optional[int] = None) -> mock.MagicMock:
    """A dbt API list response envelope."""
    return _response(
        json_data={
            "status": {"code": 200, "is_success": True},
            "data": rows,
            "extra": {
                "pagination": {
                    "count": count if count is not None else len(rows),
                    "total_count": total_count if total_count is not None else len(rows),
                },
            },
        }
    )


def _manager(resume: Optional[DbtResumeConfig] = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume is not None
    manager.load_state.return_value = resume
    return manager


def _requested_query(session: mock.MagicMock, call_index: int) -> dict[str, list[str]]:
    url = session.get.call_args_list[call_index].args[0]
    return parse_qs(urlparse(url).query)


class TestGetBaseUrl:
    @pytest.mark.parametrize(
        "region, expected",
        [
            ("us", "https://cloud.getdbt.com"),
            ("emea", "https://emea.dbt.com"),
            ("au", "https://au.dbt.com"),
            ("unknown", "https://cloud.getdbt.com"),
        ],
    )
    def test_region_mapping(self, region, expected):
        assert get_base_url(region, None) == expected

    @pytest.mark.parametrize(
        "custom, expected",
        [
            ("https://ab123.us1.dbt.com", "https://ab123.us1.dbt.com"),
            ("https://ab123.us1.dbt.com/", "https://ab123.us1.dbt.com"),
            ("  https://single-tenant.example.com  ", "https://single-tenant.example.com"),
            ("", "https://cloud.getdbt.com"),
            ("   ", "https://cloud.getdbt.com"),
            (None, "https://cloud.getdbt.com"),
        ],
    )
    def test_custom_base_url_overrides_region(self, custom, expected):
        assert get_base_url("us", custom) == expected

    def test_non_https_custom_url_rejected(self):
        with pytest.raises(DbtHostNotAllowedError):
            get_base_url("us", "http://internal-host")


class TestCoerceDatetime:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC), datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)),
            (datetime(2026, 6, 1, 12, 0, 0), datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)),
            (date(2026, 6, 1), datetime(2026, 6, 1, tzinfo=UTC)),
            ("2026-06-01T12:00:00Z", datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)),
            ("2026-06-01 12:00:00+00:00", datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)),
            ("2026-06-01T12:00:00", datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)),
            ("not-a-date", None),
            (12345, None),
            (None, None),
        ],
    )
    def test_coerce(self, value, expected):
        assert _coerce_datetime(value) == expected


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, schema_name, expected_valid, expected_error_fragment",
        [
            (200, None, True, None),
            (401, None, False, "Invalid dbt API token"),
            # A 403 at source-create means the token authenticated but lacks the permission for
            # this probe — creation must go through so per-endpoint checks can guide the user.
            (403, None, True, None),
            (403, "runs", False, "permissions"),
            (404, None, False, "not found"),
        ],
    )
    def test_status_mapping(self, status_code, schema_name, expected_valid, expected_error_fragment):
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.return_value = _response(status_code=status_code, json_data={"status": {}})

            valid, error = validate_credentials(
                api_token="token", account_id="12345", region="us", custom_base_url=None, schema_name=schema_name
            )

        assert valid is expected_valid
        if expected_error_fragment is None:
            assert error is None
        else:
            assert expected_error_fragment in (error or "")

    def test_probes_account_endpoint_without_following_redirects(self):
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.return_value = _response(status_code=200, json_data={"status": {}})

            validate_credentials(api_token="token", account_id="12345", region="emea", custom_base_url=None)

            call = mock_session.return_value.get.call_args
            assert call.args[0] == "https://emea.dbt.com/api/v2/accounts/12345/"
            assert call.kwargs["headers"]["Authorization"] == "Token token"
            assert call.kwargs["allow_redirects"] is False

    def test_redirect_is_rejected(self):
        # A custom host could 3xx to an internal address, defeating the host check (SSRF).
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.return_value = _response(status_code=302)

            valid, error = validate_credentials(
                api_token="token", account_id="12345", region="us", custom_base_url=None
            )

        assert valid is False
        assert error is not None

    def test_non_https_custom_url_fails_without_request(self):
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            valid, _error = validate_credentials(
                api_token="token", account_id="12345", region="us", custom_base_url="http://internal"
            )

        assert valid is False
        mock_session.return_value.get.assert_not_called()


class TestGetEndpointPermissions:
    def test_denied_endpoints_get_a_reason(self):
        responses = {
            "https://cloud.getdbt.com/api/v3/accounts/12345/users/?limit=1": _response(
                status_code=403, json_data={"status": {"user_message": "Insufficient permissions"}}
            ),
            "https://cloud.getdbt.com/api/v3/accounts/12345/projects/?limit=1": _page([{"id": 1}]),
        }
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.side_effect = lambda url, **kwargs: responses[url]

            result = get_endpoint_permissions(
                api_token="token",
                account_id="12345",
                region="us",
                custom_base_url=None,
                team_id=1,
                endpoints=["users", "projects"],
            )

        assert result["projects"] is None
        assert "Insufficient permissions" in (result["users"] or "")

    def test_network_errors_do_not_report_missing_permission(self):
        # A blip is not a denial — only a real 401/403/404 should flag the table.
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.side_effect = requests.ConnectionError("boom")

            result = get_endpoint_permissions(
                api_token="token",
                account_id="12345",
                region="us",
                custom_base_url=None,
                team_id=1,
                endpoints=["projects"],
            )

        assert result["projects"] is None

    def test_unsafe_custom_host_is_rejected_without_probing(self):
        # The probes are separate outbound requests, so an internal custom host must be blocked
        # here too — not just in validate_credentials — before any request goes out (SSRF).
        with (
            mock.patch(f"{MODULE}._is_host_safe", return_value=(False, "Host not allowed")),
            mock.patch(f"{MODULE}.make_tracked_session") as mock_session,
        ):
            result = get_endpoint_permissions(
                api_token="token",
                account_id="12345",
                region="us",
                custom_base_url="https://internal.local",
                team_id=1,
                endpoints=["projects", "users"],
            )

        mock_session.return_value.get.assert_not_called()
        assert result["projects"] is not None
        assert result["users"] is not None


class TestGetRows:
    def _get_rows(self, session: mock.MagicMock, manager: mock.MagicMock, endpoint: str, **kwargs: Any) -> list[Any]:
        with mock.patch(f"{MODULE}.make_tracked_session", return_value=session):
            return list(
                get_rows(
                    api_token="token",
                    account_id="12345",
                    region=kwargs.pop("region", "us"),
                    custom_base_url=kwargs.pop("custom_base_url", None),
                    endpoint=endpoint,
                    team_id=1,
                    logger=mock.MagicMock(),
                    resumable_source_manager=manager,
                    **kwargs,
                )
            )

    def test_full_refresh_paginates_until_total_count(self):
        session = mock.MagicMock()
        page1_rows = [{"id": index} for index in range(3)]
        page2_rows = [{"id": 100 + index} for index in range(2)]
        session.get.side_effect = [
            _page(page1_rows, count=100, total_count=137),
            _page(page2_rows, count=37, total_count=137),
        ]
        manager = _manager()

        batches = self._get_rows(session, manager, "projects")

        assert batches == [page1_rows, page2_rows]
        assert session.get.call_count == 2
        assert (
            session.get.call_args_list[0].args[0].startswith("https://cloud.getdbt.com/api/v3/accounts/12345/projects/")
        )
        assert _requested_query(session, 0)["offset"] == ["0"]
        assert _requested_query(session, 1)["offset"] == ["100"]
        assert "order_by" not in _requested_query(session, 0)
        assert session.get.call_args_list[0].kwargs["headers"]["Authorization"] == "Token token"

    def test_state_saved_after_yield_only_when_more_pages_remain(self):
        session = mock.MagicMock()
        session.get.side_effect = [
            _page([{"id": 1}], count=100, total_count=137),
            _page([{"id": 2}], count=37, total_count=137),
        ]
        manager = _manager()

        self._get_rows(session, manager, "projects")

        manager.save_state.assert_called_once_with(DbtResumeConfig(offset=100))

    def test_stops_when_offset_reaches_total_count(self):
        session = mock.MagicMock()
        session.get.side_effect = [_page([{"id": 1}], count=100, total_count=100)]
        manager = _manager()

        batches = self._get_rows(session, manager, "projects")

        assert batches == [[{"id": 1}]]
        assert session.get.call_count == 1
        manager.save_state.assert_not_called()

    def test_empty_page_yields_nothing(self):
        session = mock.MagicMock()
        session.get.side_effect = [_page([])]
        manager = _manager()

        assert self._get_rows(session, manager, "projects") == []

    def test_resume_starts_from_saved_offset(self):
        session = mock.MagicMock()
        session.get.side_effect = [_page([{"id": 1}], count=5, total_count=105)]
        manager = _manager(resume=DbtResumeConfig(offset=100))

        self._get_rows(session, manager, "projects")

        assert _requested_query(session, 0)["offset"] == ["100"]

    def test_runs_walk_newest_first(self):
        session = mock.MagicMock()
        session.get.side_effect = [_page([{"id": 1, "created_at": "2026-06-10T00:00:00Z"}])]
        manager = _manager()

        self._get_rows(session, manager, "runs")

        assert _requested_query(session, 0)["order_by"] == ["-created_at"]

    def test_runs_incremental_stops_once_page_dips_below_watermark(self):
        watermark = datetime(2026, 6, 10, tzinfo=UTC)
        session = mock.MagicMock()
        page1_rows = [{"id": 3, "created_at": "2026-06-20T00:00:00Z"}]
        page2_rows: list[dict[str, Any]] = [
            {"id": 2, "created_at": "2026-06-11T00:00:00Z"},
            # Within the 24h lookback window below the watermark: re-pulled so late status
            # changes land; merge dedupes it on the primary key.
            {"id": 1, "created_at": "2026-06-09T12:00:00Z"},
            # Missing cursor value: kept to stay on the safe side.
            {"id": 0},
            # Below the effective watermark: already synced, walking stops here.
            {"id": -1, "created_at": "2026-06-01T00:00:00Z"},
        ]
        session.get.side_effect = [
            _page(page1_rows, count=100, total_count=500),
            _page(page2_rows, count=100, total_count=500),
        ]
        manager = _manager()

        batches = self._get_rows(
            session,
            manager,
            "runs",
            should_use_incremental_field=True,
            db_incremental_field_last_value=watermark,
            incremental_field="created_at",
        )

        assert batches == [page1_rows, page2_rows[:3]]
        # The third page (offset=200) must never be requested — that's the whole point of the
        # newest-first walk: incremental syncs don't re-crawl history.
        assert session.get.call_count == 2

    def test_runs_without_watermark_walk_all_pages(self):
        session = mock.MagicMock()
        page1_rows = [{"id": 2, "created_at": "2026-06-10T00:00:00Z"}]
        page2_rows = [{"id": 1, "created_at": "2026-01-01T00:00:00Z"}]
        session.get.side_effect = [
            _page(page1_rows, count=100, total_count=101),
            _page(page2_rows, count=1, total_count=101),
        ]
        manager = _manager()

        batches = self._get_rows(
            session,
            manager,
            "runs",
            should_use_incremental_field=True,
            db_incremental_field_last_value=None,
            incremental_field="created_at",
        )

        assert batches == [page1_rows, page2_rows]

    def test_custom_base_url_is_used(self):
        session = mock.MagicMock()
        session.get.side_effect = [_page([])]
        manager = _manager()

        self._get_rows(session, manager, "projects", custom_base_url="https://ab123.us1.dbt.com/")

        assert session.get.call_args_list[0].args[0].startswith("https://ab123.us1.dbt.com/api/v3/accounts/12345/")


class TestDbtSourceResponse:
    def test_runs_response_shape(self):
        response = dbt_source(
            api_token="token",
            account_id="12345",
            region="us",
            custom_base_url=None,
            endpoint="runs",
            team_id=1,
            logger=mock.MagicMock(),
            resumable_source_manager=_manager(),
        )

        assert response.name == "runs"
        assert response.primary_keys == ["id"]
        # Runs are walked newest-first; declaring asc here would checkpoint the watermark to
        # ~now after the first batch and corrupt resume semantics.
        assert response.sort_mode == "desc"
        assert response.partition_keys == ["created_at"]
        assert response.partition_mode == "datetime"

    def test_full_refresh_response_shape(self):
        response = dbt_source(
            api_token="token",
            account_id="12345",
            region="us",
            custom_base_url=None,
            endpoint="projects",
            team_id=1,
            logger=mock.MagicMock(),
            resumable_source_manager=_manager(),
        )

        assert response.name == "projects"
        assert response.primary_keys == ["id"]
        assert response.sort_mode == "asc"
        assert response.partition_mode is None
