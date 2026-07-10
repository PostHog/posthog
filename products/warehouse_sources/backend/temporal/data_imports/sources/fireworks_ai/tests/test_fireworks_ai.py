from typing import Any

import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.fireworks_ai.fireworks_ai import (
    FireworksAIResumeConfig,
    _build_url,
    fireworks_ai_source,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.fireworks_ai.settings import (
    ENDPOINTS,
    FIREWORKS_AI_ENDPOINTS,
)

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.fireworks_ai.fireworks_ai"


def _make_manager(resume_state: FireworksAIResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _page(data_key: str, items: list[dict[str, Any]], next_token: str | None) -> dict[str, Any]:
    page: dict[str, Any] = {data_key: items}
    if next_token is not None:
        page["nextPageToken"] = next_token
    return page


def _resp(status: int, json: dict[str, Any] | None = None) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.status_code = status
    resp.ok = 200 <= status < 300
    resp.json.return_value = json or {}
    if not resp.ok:
        resp.raise_for_status.side_effect = requests.HTTPError(f"{status} error")
    return resp


class TestBuildUrl:
    def test_embeds_account_id_in_path_and_encodes_params(self):
        url = _build_url("acme", "/models", {"pageSize": 200, "pageToken": None})
        # account_id lives in the path; None params are dropped before encoding.
        assert url == "https://api.fireworks.ai/v1/accounts/acme/models?pageSize=200"

    def test_no_params(self):
        assert _build_url("acme", "/datasets", {}) == "https://api.fireworks.ai/v1/accounts/acme/datasets"


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected_ok",
        [(200, True), (401, False), (403, False), (500, False)],
    )
    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_status_mapping(self, mock_session, status_code, expected_ok):
        mock_session.return_value.get.return_value = _resp(status_code)
        ok, status = validate_credentials("fw_key", "acme")
        assert ok is expected_ok
        assert status == status_code

    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_network_error_returns_none_status(self, mock_session):
        mock_session.return_value.get.side_effect = requests.ConnectionError("boom")
        assert validate_credentials("fw_key", "acme") == (False, None)


class TestGetRows:
    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_paginates_via_next_page_token(self, mock_session):
        pages = [
            _resp(200, _page("models", [{"name": "a"}, {"name": "b"}], "tok2")),
            _resp(200, _page("models", [{"name": "c"}], None)),
        ]
        mock_session.return_value.get.side_effect = pages

        manager = _make_manager()
        batches = list(get_rows("fw_key", "acme", "models", mock.MagicMock(), manager))

        assert [row["name"] for batch in batches for row in batch] == ["a", "b", "c"]
        # State is saved once, only while another page remains, and carries the next token.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0].page_token == "tok2"

    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_first_page_has_no_page_token(self, mock_session):
        mock_session.return_value.get.side_effect = [_resp(200, _page("models", [{"name": "a"}], None))]
        list(get_rows("fw_key", "acme", "models", mock.MagicMock(), _make_manager()))

        first_url = mock_session.return_value.get.call_args_list[0].args[0]
        assert "pageSize=200" in first_url
        assert "pageToken" not in first_url

    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_resumes_from_saved_page_token(self, mock_session):
        mock_session.return_value.get.side_effect = [_resp(200, _page("models", [{"name": "z"}], None))]
        manager = _make_manager(FireworksAIResumeConfig(page_token="saved-tok"))

        list(get_rows("fw_key", "acme", "models", mock.MagicMock(), manager))

        first_url = mock_session.return_value.get.call_args_list[0].args[0]
        assert "pageToken=saved-tok" in first_url

    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_empty_first_page_stops_without_saving(self, mock_session):
        mock_session.return_value.get.side_effect = [_resp(200, _page("models", [], None))]
        manager = _make_manager()

        batches = list(get_rows("fw_key", "acme", "models", mock.MagicMock(), manager))

        assert batches == []
        manager.save_state.assert_not_called()

    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_empty_page_with_next_token_keeps_paging(self, mock_session):
        # A page can be empty yet still carry a next token; the paginator must follow it.
        mock_session.return_value.get.side_effect = [
            _resp(200, _page("datasets", [], "tok2")),
            _resp(200, _page("datasets", [{"name": "d"}], None)),
        ]
        batches = list(get_rows("fw_key", "acme", "datasets", mock.MagicMock(), _make_manager()))
        assert [row["name"] for batch in batches for row in batch] == ["d"]

    @mock.patch("time.sleep")
    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_retries_retryable_status_then_succeeds(self, mock_session, _mock_sleep):
        mock_session.return_value.get.side_effect = [
            _resp(500),
            _resp(200, _page("models", [{"name": "a"}], None)),
        ]
        batches = list(get_rows("fw_key", "acme", "models", mock.MagicMock(), _make_manager()))
        assert [row["name"] for batch in batches for row in batch] == ["a"]
        assert mock_session.return_value.get.call_count == 2

    @mock.patch("time.sleep")
    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_non_retryable_status_raises_immediately(self, mock_session, _mock_sleep):
        mock_session.return_value.get.side_effect = [_resp(404)]
        with pytest.raises(requests.HTTPError):
            list(get_rows("fw_key", "acme", "models", mock.MagicMock(), _make_manager()))
        # 404 is not retried.
        assert mock_session.return_value.get.call_count == 1


class TestFireworksAISourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint):
        config = FIREWORKS_AI_ENDPOINTS[endpoint]
        response = fireworks_ai_source("fw_key", "acme", endpoint, mock.MagicMock(), _make_manager())

        assert response.name == endpoint
        # Resource `name` is globally unique across the account, so it is the primary key.
        assert response.primary_keys == ["name"]
        assert response.sort_mode == "asc"
        assert response.partition_mode == "datetime"
        assert response.partition_keys == [config.partition_key]

    @pytest.mark.parametrize("config", list(FIREWORKS_AI_ENDPOINTS.values()))
    def test_partition_key_is_stable_creation_field(self, config):
        # Never partition on updateTime — it shifts and rewrites partitions each sync.
        assert config.partition_key == "createTime"
