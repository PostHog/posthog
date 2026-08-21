from typing import Any

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.customerly.customerly import (
    PAGE_SIZE,
    CustomerlyAuthenticationError,
    CustomerlyResumeConfig,
    _build_url,
    _is_auth_error_body,
    customerly_source,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.customerly.settings import (
    CUSTOMERLY_ENDPOINTS,
    ENDPOINTS,
)

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.customerly.customerly"


def _make_manager(resume_state: CustomerlyResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _response(body: dict[str, Any] | None = None, status_code: int = 200, text: str = "") -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.status_code = status_code
    resp.ok = status_code < 400
    resp.text = text
    resp.json.return_value = body or {}
    return resp


def _users_page(count: int, start: int = 0) -> dict[str, Any]:
    return {"data": {"users": [{"crmhero_user_id": start + i} for i in range(count)]}}


class TestBuildUrl:
    def test_no_params(self):
        assert _build_url("/tags", {}) == "https://api.customerly.io/v1/tags"

    def test_drops_none_values_and_encodes(self):
        url = _build_url("/users/list", {"page": 0, "per_page": 50, "sort": None})
        assert url == "https://api.customerly.io/v1/users/list?page=0&per_page=50"


class TestAuthErrorDetection:
    @pytest.mark.parametrize(
        "body, expected",
        [
            ('{"error":{"message":"Access token not found.","code":0}}', True),
            ('{"error":{"message":"You must provide a valid header Authorization: Bearer <TOKEN>","code":0}}', True),
            ('{"error":{"message":"Internal server error","code":0}}', False),
            ("", False),
        ],
    )
    def test_is_auth_error_body(self, body, expected):
        assert _is_auth_error_body(body) is expected

    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_auth_failure_masquerading_as_500_is_not_retried(self, mock_session):
        # Customerly reports bad tokens as HTTP 500; treating that as a retryable server
        # error would retry a permanent credential failure forever.
        mock_session.return_value.get.return_value = _response(
            status_code=500, text='{"error":{"message":"Access token not found.","code":0}}'
        )

        with pytest.raises(CustomerlyAuthenticationError):
            list(get_rows("bad-token", "users", mock.MagicMock(), _make_manager()))

        assert mock_session.return_value.get.call_count == 1


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
    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_status_mapping(self, mock_session, status_code, expected):
        mock_session.return_value.get.return_value = _response(status_code=status_code)
        assert validate_credentials("token") is expected

    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_swallows_exceptions(self, mock_session):
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("token") is False


class TestGetRows:
    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_paginates_until_short_page(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _response(_users_page(PAGE_SIZE)),
            _response(_users_page(3, start=PAGE_SIZE)),
        ]

        manager = _make_manager()
        batches = list(get_rows("token", "users", mock.MagicMock(), manager))

        assert [len(batch) for batch in batches] == [PAGE_SIZE, 3]
        urls = [call.args[0] for call in mock_session.return_value.get.call_args_list]
        assert "page=0" in urls[0]
        assert "page=1" in urls[1]
        # State is saved only after a full page, pointing at the next page to fetch.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == CustomerlyResumeConfig(page=1)

    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_empty_first_page_yields_nothing(self, mock_session):
        mock_session.return_value.get.return_value = _response(_users_page(0))

        manager = _make_manager()
        batches = list(get_rows("token", "users", mock.MagicMock(), manager))

        assert batches == []
        manager.save_state.assert_not_called()

    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_resumes_from_saved_page(self, mock_session):
        mock_session.return_value.get.return_value = _response(_users_page(1))

        manager = _make_manager(CustomerlyResumeConfig(page=7))
        list(get_rows("token", "users", mock.MagicMock(), manager))

        assert "page=7" in mock_session.return_value.get.call_args_list[0].args[0]

    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_leads_read_from_leads_data_key(self, mock_session):
        mock_session.return_value.get.return_value = _response({"data": {"leads": [{"crmhero_user_id": 5}]}})

        batches = list(get_rows("token", "leads", mock.MagicMock(), _make_manager()))

        assert batches == [[{"crmhero_user_id": 5}]]

    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_tags_are_normalized_into_rows(self, mock_session):
        mock_session.return_value.get.return_value = _response({"data": ["onboarding", "remarketing"]})

        batches = list(get_rows("token", "tags", mock.MagicMock(), _make_manager()))

        assert batches == [[{"name": "onboarding"}, {"name": "remarketing"}]]
        assert mock_session.return_value.get.call_count == 1

    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_collections_returned_as_is(self, mock_session):
        collections = [{"knowledge_base_collection_id": 4517, "title": "Getting Started"}]
        mock_session.return_value.get.return_value = _response({"data": collections})

        batches = list(get_rows("token", "knowledge_base_collections", mock.MagicMock(), _make_manager()))

        assert batches == [collections]


class TestArticlesFanOut:
    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_fans_out_over_collections_in_ascending_id_order(self, mock_session):
        collections = {"data": [{"knowledge_base_collection_id": 6050}, {"knowledge_base_collection_id": 4517}]}
        articles_4517 = {"data": [{"knowledge_base_article_id": 1, "knowledge_base_collection_id": 4517}]}
        articles_6050 = {"data": [{"knowledge_base_article_id": 2, "knowledge_base_collection_id": 6050}]}
        mock_session.return_value.get.side_effect = [
            _response(collections),
            _response(articles_4517),
            _response(articles_6050),
        ]

        manager = _make_manager()
        batches = list(get_rows("token", "knowledge_base_articles", mock.MagicMock(), manager))

        urls = [call.args[0] for call in mock_session.return_value.get.call_args_list]
        assert "knowledge/collections" in urls[0]
        assert "knowledge_base_collection_id=4517" in urls[1]
        assert "knowledge_base_collection_id=6050" in urls[2]
        assert [item["knowledge_base_article_id"] for batch in batches for item in batch] == [1, 2]

    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_checkpoints_next_collection_after_each_collection(self, mock_session):
        collections = {"data": [{"knowledge_base_collection_id": 4517}]}
        mock_session.return_value.get.side_effect = [
            _response(collections),
            _response({"data": [{"knowledge_base_article_id": 1}]}),
        ]

        manager = _make_manager()
        list(get_rows("token", "knowledge_base_articles", mock.MagicMock(), manager))

        manager.save_state.assert_called_with(CustomerlyResumeConfig(page=0, collection_id=4518))

    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_resume_skips_completed_collections_and_starts_at_saved_page(self, mock_session):
        collections = {"data": [{"knowledge_base_collection_id": 4517}, {"knowledge_base_collection_id": 6050}]}
        mock_session.return_value.get.side_effect = [
            _response(collections),
            _response({"data": [{"knowledge_base_article_id": 9}]}),
        ]

        manager = _make_manager(CustomerlyResumeConfig(page=3, collection_id=6050))
        list(get_rows("token", "knowledge_base_articles", mock.MagicMock(), manager))

        urls = [call.args[0] for call in mock_session.return_value.get.call_args_list]
        assert len(urls) == 2
        assert "knowledge_base_collection_id=6050" in urls[1]
        assert "page=3" in urls[1]


class TestCustomerlySourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint):
        config = CUSTOMERLY_ENDPOINTS[endpoint]
        response = customerly_source("token", endpoint, mock.MagicMock(), _make_manager())

        assert response.name == endpoint
        assert response.primary_keys == [config.primary_key]
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None

    @pytest.mark.parametrize("config", list(CUSTOMERLY_ENDPOINTS.values()))
    def test_partition_keys_are_stable_creation_fields(self, config):
        if config.partition_key:
            assert config.partition_key in {"first_seen_at", "created_at"}
