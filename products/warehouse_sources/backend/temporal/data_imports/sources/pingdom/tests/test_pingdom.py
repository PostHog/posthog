from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.pingdom.pingdom import (
    PingdomResumeConfig,
    _build_params,
    _build_url,
    _extract_items,
    _to_epoch,
    get_rows,
    pingdom_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.pingdom.settings import (
    ENDPOINTS,
    PINGDOM_ENDPOINTS,
)


def _make_manager(resume_state: PingdomResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _response(body: dict[str, Any]) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.json.return_value = body
    resp.status_code = 200
    resp.ok = True
    return resp


class TestToEpoch:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (None, None),
            (1700000000, 1700000000),
            (1700000000.9, 1700000000),
            ("1700000000", 1700000000),
            (datetime(2023, 11, 14, 22, 13, 20, tzinfo=UTC), 1700000000),
            (date(2023, 11, 15), int(datetime(2023, 11, 15, tzinfo=UTC).timestamp())),
            ("not-a-number", None),
            (True, None),
        ],
    )
    def test_to_epoch_values(self, value, expected):
        assert _to_epoch(value) == expected


class TestExtractItems:
    @pytest.mark.parametrize(
        "body, data_key, expected",
        [
            ({"checks": [{"id": 1}]}, "checks", [{"id": 1}]),
            ({"actions": {"alerts": [{"time": 1}]}}, "actions.alerts", [{"time": 1}]),
        ],
    )
    def test_extracts_items(self, body, data_key, expected):
        assert _extract_items(body, data_key) == expected

    @pytest.mark.parametrize(
        "body",
        [
            {},
            {"actions": {}},
            {"actions": {"alerts": None}},
            {"actions": None},
            {"actions": {"alerts": {"not": "a list"}}},
        ],
    )
    def test_missing_or_malformed_returns_empty(self, body):
        assert _extract_items(body, "actions.alerts") == []


class TestBuildParams:
    def test_includes_limit_and_offset(self):
        params = _build_params(PINGDOM_ENDPOINTS["alerts"], from_value=None, offset=0)
        assert params == {"limit": 1000, "offset": 0}

    def test_includes_from_when_set(self):
        params = _build_params(PINGDOM_ENDPOINTS["alerts"], from_value=1700000000, offset=2000)
        assert params == {"limit": 1000, "offset": 2000, "from": 1700000000}

    def test_checks_uses_large_page_size(self):
        params = _build_params(PINGDOM_ENDPOINTS["checks"], from_value=None, offset=0)
        assert params["limit"] == 25000


class TestBuildUrl:
    def test_with_params(self):
        url = _build_url("/checks", {"limit": 1})
        assert url == "https://api.pingdom.com/api/3.1/checks?limit=1"


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected",
        [
            (200, True),
            (401, False),
            (403, False),
            (500, False),
        ],
    )
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.pingdom.pingdom.make_tracked_session")
    def test_validate_credentials_status_mapping(self, mock_session, status_code, expected):
        response = mock.MagicMock()
        response.status_code = status_code
        mock_session.return_value.get.return_value = response

        assert validate_credentials("token") is expected

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.pingdom.pingdom.make_tracked_session")
    def test_validate_credentials_swallows_exceptions(self, mock_session):
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("token") is False


class TestGetRows:
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.pingdom.pingdom.make_tracked_session")
    def test_paginates_until_short_page(self, mock_session):
        page_size = PINGDOM_ENDPOINTS["alerts"].page_size
        full_page = {"actions": {"alerts": [{"time": i} for i in range(page_size)]}}
        short_page = {"actions": {"alerts": [{"time": page_size}]}}
        mock_session.return_value.get.side_effect = [_response(full_page), _response(short_page)]

        manager = _make_manager()
        batches = list(get_rows("token", "alerts", mock.MagicMock(), manager))

        assert len(batches) == 2
        assert len(batches[0]) == page_size
        # State saved once, after the first (full) page, pointing at the next offset.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0].offset == page_size
        second_url = mock_session.return_value.get.call_args_list[1].args[0]
        assert parse_qs(urlparse(second_url).query)["offset"] == [str(page_size)]

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.pingdom.pingdom.make_tracked_session")
    def test_resumes_from_saved_offset(self, mock_session):
        mock_session.return_value.get.return_value = _response({"checks": [{"id": 1}]})

        manager = _make_manager(PingdomResumeConfig(offset=50000))
        list(get_rows("token", "checks", mock.MagicMock(), manager))

        url = mock_session.return_value.get.call_args.args[0]
        assert parse_qs(urlparse(url).query)["offset"] == ["50000"]

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.pingdom.pingdom.make_tracked_session")
    def test_incremental_request_includes_from_filter(self, mock_session):
        mock_session.return_value.get.return_value = _response({"actions": {"alerts": []}})

        manager = _make_manager()
        list(
            get_rows(
                "token",
                "alerts",
                mock.MagicMock(),
                manager,
                should_use_incremental_field=True,
                db_incremental_field_last_value=1700000000,
            )
        )

        url = mock_session.return_value.get.call_args.args[0]
        assert parse_qs(urlparse(url).query)["from"] == ["1700000000"]

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.pingdom.pingdom.make_tracked_session")
    def test_full_refresh_has_no_from_filter(self, mock_session):
        mock_session.return_value.get.return_value = _response({"actions": {"alerts": []}})

        manager = _make_manager()
        list(get_rows("token", "alerts", mock.MagicMock(), manager))

        url = mock_session.return_value.get.call_args.args[0]
        assert "from" not in parse_qs(urlparse(url).query)

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.pingdom.pingdom.make_tracked_session")
    def test_empty_response_stops_without_saving_state(self, mock_session):
        mock_session.return_value.get.return_value = _response({"checks": []})

        manager = _make_manager()
        batches = list(get_rows("token", "checks", mock.MagicMock(), manager))

        assert batches == []
        manager.save_state.assert_not_called()


class TestPingdomSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint):
        config = PINGDOM_ENDPOINTS[endpoint]
        response = pingdom_source("token", endpoint, mock.MagicMock(), _make_manager())

        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        assert response.sort_mode == "asc"
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None

    def test_alerts_flag_duplicate_primary_keys(self):
        response = pingdom_source("token", "alerts", mock.MagicMock(), _make_manager())
        assert response.has_duplicate_primary_keys is True

    def test_checks_do_not_flag_duplicate_primary_keys(self):
        response = pingdom_source("token", "checks", mock.MagicMock(), _make_manager())
        assert response.has_duplicate_primary_keys is None

    @pytest.mark.parametrize("config", list(PINGDOM_ENDPOINTS.values()))
    def test_partition_keys_are_stable_fields(self, config):
        if config.partition_key:
            # Alert timestamps are immutable event times.
            assert config.partition_key == "time"
