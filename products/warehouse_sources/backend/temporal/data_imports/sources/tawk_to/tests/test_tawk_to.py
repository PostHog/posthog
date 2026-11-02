from typing import Any

import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.tawkto import TawkToSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.tawk_to.settings import (
    ENDPOINTS,
    TAWK_TO_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.tawk_to.source import TawkToSource
from products.warehouse_sources.backend.temporal.data_imports.sources.tawk_to.tawk_to import (
    API_KEY_FORBIDDEN_MESSAGE,
    INVALID_API_KEY_MESSAGE,
    PAGE_SIZE,
    TawkToApiError,
    TawkToCredentialsError,
    TawkToResumeConfig,
    TawkToRetryableError,
    get_rows,
    validate_credentials,
)

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.tawk_to.tawk_to"


def _make_manager(resume_state: TawkToResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _mock_response(body: dict[str, Any], status_code: int = 200) -> mock.MagicMock:
    response = mock.MagicMock()
    response.status_code = status_code
    response.ok = status_code < 400
    response.json.return_value = body
    return response


def _driver(property_id: str | None = None) -> SourceDriver:
    return SourceDriver(TawkToSource(), TawkToSourceConfig(api_key="key", property_id=property_id))


def _response(body: dict[str, Any], status_code: int = 200) -> ScriptedResponse:
    return ScriptedResponse(status=status_code, json=body)


def _page(items: list[dict[str, Any]], total: int) -> dict[str, Any]:
    return {"ok": True, "total": total, "data": items}


class TestValidateCredentials:
    def test_accepts_a_working_key(self):
        with scripted_network(always(_response({"ok": True, "data": []}))):
            assert validate_credentials("key") is True

    @pytest.mark.parametrize(
        "status_code, body, expected_message",
        [
            (200, {"ok": False, "error": "auth_error"}, INVALID_API_KEY_MESSAGE),
            (401, {"ok": False, "error": "auth_error", "message": "invalid_auth"}, INVALID_API_KEY_MESSAGE),
            (403, {"ok": False, "error": "forbidden"}, API_KEY_FORBIDDEN_MESSAGE),
        ],
    )
    def test_rejected_key_raises_credentials_error(self, status_code, body, expected_message):
        with scripted_network(always(_response(body, status_code))):
            with pytest.raises(TawkToCredentialsError) as exc:
                validate_credentials("key")
        assert str(exc.value) == expected_message

    @pytest.mark.parametrize("status_code", [429, 500, 503])
    def test_rate_limit_and_server_errors_are_retryable(self, status_code):
        with scripted_network(always(_response({}, status_code))):
            with pytest.raises(TawkToRetryableError):
                validate_credentials("key")

    def test_transport_errors_propagate(self):
        with scripted_network(always(requests.ConnectionError("boom"))):
            with pytest.raises(requests.ConnectionError):
                validate_credentials("key")


class TestGetRows:
    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_repeated_page_stops_instead_of_looping(self, mock_session):
        page = [{"id": str(n)} for n in range(PAGE_SIZE)]
        mock_session.return_value.post.side_effect = [
            _mock_response(_page(page, total=10_000)),
            _mock_response(_page(page, total=10_000)),
        ]

        logger = mock.MagicMock()
        batches = list(get_rows("key", "prop-1", "chats", logger, _make_manager()))

        assert mock_session.return_value.post.call_count == 2
        assert sum(len(batch) for batch in batches) == PAGE_SIZE
        logger.warning.assert_called_once()

    def test_fans_out_over_all_properties_when_none_configured(self):
        result = _driver().run(
            "chats",
            [
                _response({"ok": True, "data": [{"propertyId": "prop-1"}, {"propertyId": "prop-2"}]}),
                _response(_page([{"id": "a"}], total=1)),
                _response(_page([{"id": "b"}], total=1)),
            ],
        )

        bodies = [request.json() for request in result.requests]
        assert bodies[0] == {}
        assert bodies[1]["propertyId"] == "prop-1"
        assert bodies[2]["propertyId"] == "prop-2"
        assert [item["id"] for item in result.rows] == ["a", "b"]
        # The bookmark advances to the next property so a crash in between resumes there.
        saved = result.saved_states[-1]
        assert saved.property_id == "prop-2"
        assert saved.offset == 0

    def test_resumes_from_saved_property_and_offset(self):
        result = _driver().run(
            "chats",
            [
                _response({"ok": True, "data": [{"propertyId": "prop-1"}, {"propertyId": "prop-2"}]}),
                _response(_page([{"id": "b"}], total=100)),
            ],
            resume_state=TawkToResumeConfig(offset=50, property_id="prop-2"),
        )

        bodies = [request.json() for request in result.requests]
        # prop-1 is skipped entirely; prop-2 starts at the saved offset.
        assert len(bodies) == 2
        assert bodies[1] == {"propertyId": "prop-2", "size": PAGE_SIZE, "offset": 50}

    def test_properties_endpoint_is_a_single_unscoped_call(self):
        result = _driver().run(
            "properties", [_response({"ok": True, "data": [{"propertyId": "prop-1", "name": "Site"}]})]
        )

        assert len(result.requests) == 1
        assert result.requests[0].json() == {}
        assert result.items == [[{"propertyId": "prop-1", "name": "Site"}]]
        assert result.saved_states == []

    def test_unpaginated_scoped_endpoint_sends_only_property_id(self):
        result = _driver("prop-1").run("members", [_response({"ok": True, "data": [{"role": "admin"}]})])

        assert len(result.requests) == 1
        assert result.requests[0].json() == {"propertyId": "prop-1"}
        assert result.items == [[{"role": "admin", "propertyId": "prop-1"}]]

    def test_ok_false_body_raises(self):
        result = _driver("prop-1").run(
            "chats", [_response({"ok": False, "error": "validation_error", "message": "body"})]
        )

        assert isinstance(result.raised, TawkToApiError)
        assert "validation_error" in str(result.raised)


class TestTawkToSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint):
        config = TAWK_TO_ENDPOINTS[endpoint]
        response = _driver().run(endpoint, always(_response({"ok": True, "data": []}))).response

        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        assert response.sort_mode == "desc"
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None
