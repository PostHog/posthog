import json
from collections.abc import Iterable
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.cloudability.cloudability import (
    CloudabilityResumeConfig,
    base_url,
    cloudability_source,
    get_resource,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.cloudability.settings import (
    COST_REPORT_DIMENSIONS,
    COST_REPORT_METRICS,
    ENDPOINTS,
    PRIMARY_KEYS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponseCursorPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import Endpoint
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager


class TestBaseUrl:
    @pytest.mark.parametrize(
        "region, expected",
        [
            ("us", "https://api.cloudability.com/v3"),
            ("eu", "https://api-eu.cloudability.com/v3"),
            # Anything unrecognized falls back to US rather than sending an unpredictable host.
            ("unknown", "https://api.cloudability.com/v3"),
        ],
    )
    def test_base_url(self, region, expected):
        assert base_url(region) == expected


class TestGetResource:
    def test_costs_uses_cursor_paginator_and_documented_dimensions(self):
        resource = get_resource("Costs", view_id=None)

        endpoint = cast(Endpoint, resource["endpoint"])
        assert endpoint["path"] == "/reporting/cost/run"
        assert endpoint["data_selector"] == "results"
        assert isinstance(endpoint["paginator"], JSONResponseCursorPaginator)
        params = cast(dict[str, Any], endpoint["params"])
        assert params["dimensions"] == ",".join(COST_REPORT_DIMENSIONS)
        assert params["metrics"] == ",".join(COST_REPORT_METRICS)
        assert resource["write_disposition"] == "replace"

    def test_costs_date_window_is_start_before_end(self):
        endpoint = cast(Endpoint, get_resource("Costs", view_id=None)["endpoint"])
        params = cast(dict[str, Any], endpoint["params"])
        assert params["start_date"] < params["end_date"]

    @pytest.mark.parametrize(
        "endpoint_name, path",
        [
            ("Views", "/views"),
            ("BusinessMappingDimensions", "/business-mappings/dimensions"),
            ("BusinessMappingMetrics", "/business-mappings/metrics/"),
        ],
    )
    def test_single_page_endpoints(self, endpoint_name, path):
        resource = get_resource(endpoint_name, view_id=None)
        endpoint = cast(Endpoint, resource["endpoint"])

        assert endpoint["path"] == path
        assert endpoint["paginator"] == "single_page"
        assert endpoint["data_selector_required"] is True

    def test_anomalies_omits_view_id_when_not_configured(self):
        endpoint = cast(Endpoint, get_resource("Anomalies", view_id=None)["endpoint"])
        params = cast(dict[str, Any], endpoint["params"])
        assert params["viewId"] is None

    def test_anomalies_passes_configured_view_id(self):
        endpoint = cast(Endpoint, get_resource("Anomalies", view_id="42")["endpoint"])
        params = cast(dict[str, Any], endpoint["params"])
        assert params["viewId"] == "42"

    def test_unknown_endpoint_raises(self):
        with pytest.raises(ValueError, match="Unknown Cloudability endpoint"):
            get_resource("NotARealEndpoint", view_id=None)

    def test_every_declared_endpoint_has_a_primary_key(self):
        for endpoint_name in ENDPOINTS:
            resource = get_resource(endpoint_name, view_id="42")
            assert PRIMARY_KEYS[endpoint_name]
            assert resource["table_format"] == "delta"


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected",
        [(200, True), (401, False), (403, False), (500, False)],
    )
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.cloudability.cloudability.make_tracked_session"
    )
    def test_validate_credentials_checks_status_code(self, mock_make_session, status_code, expected):
        mock_session = mock_make_session.return_value
        mock_session.get.return_value = MagicMock(status_code=status_code)

        assert validate_credentials("api-key", "us") is expected

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.cloudability.cloudability.make_tracked_session"
    )
    def test_validate_credentials_uses_basic_auth_with_empty_password(self, mock_make_session):
        mock_session = mock_make_session.return_value
        mock_session.get.return_value = MagicMock(status_code=200)

        validate_credentials("api-key", "eu")

        mock_session.get.assert_called_once_with(
            "https://api-eu.cloudability.com/v3/views",
            auth=("api-key", ""),
        )


def _make_http_response(body: dict[str, Any], status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    resp.headers["Content-Type"] = "application/json"
    return resp


class TestCloudabilitySourceResumeBehavior:
    """End-to-end resume behaviour of ``cloudability_source`` via ``rest_api_resource``."""

    def _drive(
        self, endpoint: str, manager: MagicMock, responses: list[Response], view_id: str | None = None
    ) -> tuple[MagicMock, list[dict[str, Any]]]:
        sent_params: list[dict[str, Any]] = []
        response_iter = iter(responses)

        def fake_send(request: Any, *_args: Any, **_kwargs: Any) -> Response:
            sent_params.append(dict(request.params or {}))
            return next(response_iter)

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
        ) as MockSession:
            mock_session = MockSession.return_value
            mock_session.headers = {}
            mock_session.prepare_request.side_effect = lambda req: req
            mock_session.send.side_effect = fake_send

            resource = cloudability_source(
                api_key="test-key",
                region="us",
                endpoint=endpoint,
                team_id=123,
                job_id="test_job",
                resumable_source_manager=manager,
                view_id=view_id,
            )
            list(cast(Iterable[Any], resource.items()))
            return mock_session, sent_params

    def test_fresh_run_saves_token_after_non_terminal_page(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [
            _make_http_response({"results": [{"vendor": "AWS"}], "pagination": {"next": "tok-1"}}),
            _make_http_response({"results": [{"vendor": "GCP"}]}),
        ]
        _, sent_params = self._drive("Costs", manager, responses)

        tokens_sent = [p.get("token") for p in sent_params]
        assert tokens_sent == [None, "tok-1"]

        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [CloudabilityResumeConfig(cursor="tok-1")]

    def test_resume_seeds_paginator_with_saved_token(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        manager.load_state.return_value = CloudabilityResumeConfig(cursor="tok-resumed")

        responses = [_make_http_response({"results": [{"vendor": "Azure"}]})]
        _, sent_params = self._drive("Costs", manager, responses)

        assert [p.get("token") for p in sent_params] == ["tok-resumed"]
        manager.load_state.assert_called_once()

    def test_terminal_single_page_does_not_save_state(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [_make_http_response({"results": [{"vendor": "AWS"}]})]
        self._drive("Costs", manager, responses)

        manager.save_state.assert_not_called()

    @pytest.mark.parametrize(
        "endpoint, response_body",
        [
            ("Views", [{"id": "v1", "title": "Default"}]),
            ("BusinessMappingDimensions", [{"name": "team", "index": 1}]),
            ("BusinessMappingMetrics", [{"name": "allocated_cost", "index": 1}]),
            ("Anomalies", [{"id": "a1", "vendor": "AWS"}]),
        ],
    )
    def test_single_page_endpoints_do_not_save_resume_state(self, endpoint, response_body) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [_make_http_response(response_body)]
        _, rows = self._drive(endpoint, manager, responses)

        manager.save_state.assert_not_called()
