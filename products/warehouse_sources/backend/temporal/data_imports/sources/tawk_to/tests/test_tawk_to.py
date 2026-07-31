from typing import Any

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.tawk_to.settings import (
    ENDPOINTS,
    TAWK_TO_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.tawk_to.tawk_to import (
    PAGE_SIZE,
    TawkToApiError,
    TawkToResumeConfig,
    get_rows,
    tawk_to_source,
    validate_credentials,
)

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.tawk_to.tawk_to"


def _make_manager(resume_state: TawkToResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _response(body: dict[str, Any], status_code: int = 200) -> mock.MagicMock:
    response = mock.MagicMock()
    response.status_code = status_code
    response.ok = status_code < 400
    response.json.return_value = body
    return response


def _page(items: list[dict[str, Any]], total: int) -> dict[str, Any]:
    return {"ok": True, "total": total, "data": items}


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, body, expected",
        [
            (200, {"ok": True, "data": []}, True),
            (200, {"ok": False, "error": "auth_error"}, False),
            (401, {"ok": False, "error": "auth_error", "message": "invalid_auth"}, False),
            (500, {}, False),
        ],
    )
    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_status_and_body_mapping(self, mock_session, status_code, body, expected):
        mock_session.return_value.post.return_value = _response(body, status_code)

        assert validate_credentials("key") is expected

    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_swallows_exceptions(self, mock_session):
        mock_session.return_value.post.side_effect = Exception("boom")

        assert validate_credentials("key") is False


class TestGetRows:
    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_paginates_with_advancing_offset(self, mock_session):
        first_page = [{"id": str(n)} for n in range(PAGE_SIZE)]
        second_page = [{"id": "last"}]
        mock_session.return_value.post.side_effect = [
            _response(_page(first_page, total=PAGE_SIZE + 1)),
            _response(_page(second_page, total=PAGE_SIZE + 1)),
        ]

        manager = _make_manager()
        batches = list(get_rows("key", "prop-1", "chats", mock.MagicMock(), manager))

        bodies = [call.kwargs["json"] for call in mock_session.return_value.post.call_args_list]
        assert bodies[0] == {"propertyId": "prop-1", "size": PAGE_SIZE, "offset": 0}
        assert bodies[1] == {"propertyId": "prop-1", "size": PAGE_SIZE, "offset": PAGE_SIZE}
        assert sum(len(batch) for batch in batches) == PAGE_SIZE + 1
        # State is saved only while more pages remain, after the batch is yielded.
        manager.save_state.assert_called_once()
        saved = manager.save_state.call_args.args[0]
        assert saved.offset == PAGE_SIZE
        assert saved.property_id == "prop-1"

    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_short_page_terminates_without_saving_state(self, mock_session):
        mock_session.return_value.post.return_value = _response(_page([{"id": "1"}], total=1))

        manager = _make_manager()
        batches = list(get_rows("key", "prop-1", "chats", mock.MagicMock(), manager))

        assert mock_session.return_value.post.call_count == 1
        assert [item["id"] for batch in batches for item in batch] == ["1"]
        manager.save_state.assert_not_called()

    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_repeated_page_stops_instead_of_looping(self, mock_session):
        page = [{"id": str(n)} for n in range(PAGE_SIZE)]
        mock_session.return_value.post.side_effect = [
            _response(_page(page, total=10_000)),
            _response(_page(page, total=10_000)),
        ]

        logger = mock.MagicMock()
        batches = list(get_rows("key", "prop-1", "chats", logger, _make_manager()))

        assert mock_session.return_value.post.call_count == 2
        assert sum(len(batch) for batch in batches) == PAGE_SIZE
        logger.warning.assert_called_once()

    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_rows_carry_property_id(self, mock_session):
        mock_session.return_value.post.return_value = _response(
            _page([{"id": "1"}, {"id": "2", "propertyId": "original"}], total=2)
        )

        batches = list(get_rows("key", "prop-1", "chats", mock.MagicMock(), _make_manager()))

        rows = [item for batch in batches for item in batch]
        assert rows[0]["propertyId"] == "prop-1"
        # An API-provided propertyId is never overwritten.
        assert rows[1]["propertyId"] == "original"

    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_fans_out_over_all_properties_when_none_configured(self, mock_session):
        mock_session.return_value.post.side_effect = [
            _response({"ok": True, "data": [{"propertyId": "prop-1"}, {"propertyId": "prop-2"}]}),
            _response(_page([{"id": "a"}], total=1)),
            _response(_page([{"id": "b"}], total=1)),
        ]

        manager = _make_manager()
        batches = list(get_rows("key", None, "chats", mock.MagicMock(), manager))

        bodies = [call.kwargs["json"] for call in mock_session.return_value.post.call_args_list]
        assert bodies[0] == {}
        assert bodies[1]["propertyId"] == "prop-1"
        assert bodies[2]["propertyId"] == "prop-2"
        assert [item["id"] for batch in batches for item in batch] == ["a", "b"]
        # The bookmark advances to the next property so a crash in between resumes there.
        saved = manager.save_state.call_args.args[0]
        assert saved.property_id == "prop-2"
        assert saved.offset == 0

    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_resumes_from_saved_property_and_offset(self, mock_session):
        mock_session.return_value.post.side_effect = [
            _response({"ok": True, "data": [{"propertyId": "prop-1"}, {"propertyId": "prop-2"}]}),
            _response(_page([{"id": "b"}], total=100)),
        ]

        manager = _make_manager(TawkToResumeConfig(offset=50, property_id="prop-2"))
        list(get_rows("key", None, "chats", mock.MagicMock(), manager))

        bodies = [call.kwargs["json"] for call in mock_session.return_value.post.call_args_list]
        # prop-1 is skipped entirely; prop-2 starts at the saved offset.
        assert len(bodies) == 2
        assert bodies[1] == {"propertyId": "prop-2", "size": PAGE_SIZE, "offset": 50}

    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_missing_bookmarked_property_starts_over(self, mock_session):
        mock_session.return_value.post.side_effect = [
            _response({"ok": True, "data": [{"propertyId": "prop-1"}]}),
            _response(_page([{"id": "a"}], total=1)),
        ]

        manager = _make_manager(TawkToResumeConfig(offset=50, property_id="gone"))
        list(get_rows("key", None, "chats", mock.MagicMock(), manager))

        bodies = [call.kwargs["json"] for call in mock_session.return_value.post.call_args_list]
        assert bodies[1] == {"propertyId": "prop-1", "size": PAGE_SIZE, "offset": 0}

    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_properties_endpoint_is_a_single_unscoped_call(self, mock_session):
        mock_session.return_value.post.return_value = _response(
            {"ok": True, "data": [{"propertyId": "prop-1", "name": "Site"}]}
        )

        manager = _make_manager()
        batches = list(get_rows("key", None, "properties", mock.MagicMock(), manager))

        assert mock_session.return_value.post.call_count == 1
        assert mock_session.return_value.post.call_args.kwargs["json"] == {}
        assert batches == [[{"propertyId": "prop-1", "name": "Site"}]]
        manager.save_state.assert_not_called()

    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_unpaginated_scoped_endpoint_sends_only_property_id(self, mock_session):
        mock_session.return_value.post.return_value = _response({"ok": True, "data": [{"role": "admin"}]})

        batches = list(get_rows("key", "prop-1", "members", mock.MagicMock(), _make_manager()))

        assert mock_session.return_value.post.call_count == 1
        assert mock_session.return_value.post.call_args.kwargs["json"] == {"propertyId": "prop-1"}
        assert batches == [[{"role": "admin", "propertyId": "prop-1"}]]

    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_ok_false_body_raises(self, mock_session):
        mock_session.return_value.post.return_value = _response(
            {"ok": False, "error": "validation_error", "message": "body"}
        )

        with pytest.raises(TawkToApiError, match="validation_error"):
            list(get_rows("key", "prop-1", "chats", mock.MagicMock(), _make_manager()))


class TestTawkToSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint):
        config = TAWK_TO_ENDPOINTS[endpoint]
        response = tawk_to_source("key", None, endpoint, mock.MagicMock(), _make_manager())

        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        assert response.sort_mode == "desc"
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None

    @pytest.mark.parametrize("config", list(TAWK_TO_ENDPOINTS.values()))
    def test_partition_keys_are_stable_creation_fields(self, config):
        if config.partition_key:
            assert config.partition_key == "createdOn"
