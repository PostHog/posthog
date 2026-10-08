import json
from collections.abc import Iterable, Iterator
from datetime import UTC, date, datetime
from http import HTTPStatus
from types import SimpleNamespace
from typing import Any, cast
from urllib.parse import parse_qs, urlsplit

import pytest
from unittest.mock import MagicMock, patch

from requests import PreparedRequest, Response
from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import UnknownResourceError
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.promptingcompany import (
    PromptingCompanySourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.prompting_company.prompting_company import (
    PromptingCompanyResumeConfig,
    prompting_company_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.prompting_company.source import (
    PromptingCompanySource,
)

TRANSPORT = "products.warehouse_sources.backend.temporal.data_imports.sources.prompting_company.prompting_company"


@pytest.fixture
def config() -> PromptingCompanySourceConfig:
    return PromptingCompanySourceConfig(api_key="fake-test-key", product_id="product_example", start_date="2025-01-01")


@pytest.fixture
def manager() -> MagicMock:
    manager = MagicMock()
    manager.can_resume.return_value = False
    return manager


def inputs(name: str, incremental: bool = False, watermark: object = None) -> SourceInputs:
    return cast(
        SourceInputs,
        SimpleNamespace(
            schema_name=name,
            team_id=1,
            job_id="test-job",
            should_use_incremental_field=incremental,
            db_incremental_field_last_value=watermark,
        ),
    )


def sync_items(response: SourceResponse) -> Iterable[Any]:
    return cast(Iterable[Any], response.items())


class MockAPI:
    def __init__(self) -> None:
        self.responses: list[tuple[int, dict[str, Any]]] = []
        self.requests: list[PreparedRequest] = []

    def send(self, request: PreparedRequest, **kwargs: Any) -> Response:
        self.requests.append(request)
        status, body = self.responses.pop(0)
        response = Response()
        response.status_code = status
        response.reason = HTTPStatus(status).phrase
        assert request.url is not None
        response.url = request.url
        response.request = request
        response.headers["Content-Type"] = "application/json"
        response._content = json.dumps(body).encode()
        return response

    def params(self, index: int = 0) -> dict[str, list[str]]:
        return parse_qs(urlsplit(self.requests[index].url or "").query)


@pytest.fixture
def api() -> Iterator[MockAPI]:
    api = MockAPI()
    with patch("requests.sessions.Session.send", side_effect=api.send):
        yield api


@pytest.mark.parametrize("resumed", [False, True])
def test_content_pagination_and_resume(
    config: PromptingCompanySourceConfig, manager: MagicMock, api: MockAPI, resumed: bool
) -> None:
    first_page = 3 if resumed else 1
    manager.can_resume.return_value = resumed
    manager.load_state.return_value = PromptingCompanyResumeConfig(page=first_page)
    api.responses = [
        (200, {"ok": True, "data": {"items": [{"id": "doc-a"}], "totalPages": first_page + 1}}),
        (200, {"ok": True, "data": {"items": [{"id": "doc-b"}], "totalPages": first_page + 1}}),
    ]
    response = prompting_company_source(config, inputs("published_content"), manager)
    pages = iter(sync_items(response))
    assert next(pages) == [{"id": "doc-a"}]
    assert list(pages) == [[{"id": "doc-b"}]]
    manager.save_state.assert_called_once_with(PromptingCompanyResumeConfig(page=first_page + 1))
    assert response.on_complete is not None
    response.on_complete()
    manager.clear_state.assert_called_once_with()
    assert len(api.requests) == 2
    assert api.params() == {
        "productId": ["product_example"],
        "pageSize": ["100"],
        "page": [str(first_page)],
        "status": ["published"],
        "orderBy": ["createdAt"],
        "orderByDirection": ["asc"],
    }
    assert api.params(1)["page"] == [str(first_page + 1)]
    for request in api.requests:
        assert request.headers["x-api-key"] == "fake-test-key"
        assert "Authorization" not in request.headers
        assert urlsplit(request.url or "").path == "/api/v1/content"


@pytest.mark.parametrize(
    "incremental, watermark, expected_start",
    [
        (False, "2025-02-01", "2025-01-01"),
        (True, None, "2025-01-01"),
        (True, "2025-02-01T12:00:00Z", "2025-02-01"),
        (True, date(2025, 2, 1), "2025-02-01"),
        (True, datetime(2025, 2, 1, tzinfo=UTC), "2025-02-01"),
        (True, "2024-12-01", "2025-01-01"),
    ],
)
def test_sov_date_filter(
    config: PromptingCompanySourceConfig,
    manager: MagicMock,
    api: MockAPI,
    incremental: bool,
    watermark: object,
    expected_start: str,
) -> None:
    rows = [{"date": "2025-02-01", "sov": 50, "mentions": 1, "runs": 2}]
    api.responses = [(200, {"ok": True, "data": {"timeSeries": rows}})]
    with patch(TRANSPORT + ".datetime") as clock:
        clock.now.return_value = datetime(2025, 2, 2, tzinfo=UTC)
        response = prompting_company_source(config, inputs("share_of_voice", incremental, watermark), manager)
        assert list(sync_items(response)) == [rows]
    assert api.params() == {
        "productId": ["product_example"],
        "start": [expected_start],
        "end": ["2025-02-02"],
        "granularity": ["day"],
        "rollingWindow": ["1"],
    }
    assert response.sort_mode == "desc"
    assert len(api.requests) == 1
    manager.save_state.assert_not_called()


def test_validation_rejects_redirects(config: PromptingCompanySourceConfig) -> None:
    with patch(TRANSPORT + ".make_tracked_session") as make_session:
        response = make_session.return_value.__enter__.return_value.get.return_value
        response.status_code = 200

        assert validate_credentials(config, None) == (True, None)

    assert make_session.call_args.kwargs["allow_redirects"] is False
    assert make_session.return_value.__enter__.return_value.get.call_args.kwargs["allow_redirects"] is False


def test_sync_rejects_redirects(config: PromptingCompanySourceConfig, manager: MagicMock) -> None:
    with patch(TRANSPORT + ".rest_api_resource", return_value=[]) as make_resource:
        prompting_company_source(config, inputs("published_content"), manager)

    rest_config = make_resource.call_args.args[0]
    assert rest_config["client"]["allow_redirects"] is False


@pytest.mark.parametrize(
    "status, schema, valid, error",
    [
        (200, None, True, None),
        (401, None, False, "invalid or expired"),
        (403, None, True, None),
        (403, "published_content", False, "content:read"),
        (403, "prompt_suggestions", False, "prompts:read"),
        (403, "simulation_runs", False, "simulations:read"),
        (403, "share_of_voice", False, "analytics:read"),
        (404, None, False, "product was not found"),
    ],
)
def test_credential_status_mapping(
    config: PromptingCompanySourceConfig,
    api: MockAPI,
    status: int,
    schema: str | None,
    valid: bool,
    error: str | None,
) -> None:
    api.responses = [(status, {"ok": status == 200})]
    result, message = validate_credentials(config, schema)
    assert result is valid
    if error is None:
        assert message is None
    else:
        assert error in (message or "")
    assert len(api.requests) == 1
    assert api.requests[0].headers["x-api-key"] == "fake-test-key"
    if schema is None or schema in ("published_content", "simulation_runs"):
        assert api.params()["pageSize"] == ["1"]
    if schema == "share_of_voice":
        assert api.params()["start"] == api.params()["end"]


@pytest.mark.parametrize("status", [429, 500])
def test_credential_transient_errors_propagate(config: PromptingCompanySourceConfig, api: MockAPI, status: int) -> None:
    api.responses = [(status, {"ok": False})]
    with pytest.raises(HTTPError):
        validate_credentials(config, None)


@pytest.mark.parametrize("status, code", [(401, "UNAUTHORIZED"), (403, "FORBIDDEN")])
def test_sync_auth_errors_are_terminal(
    config: PromptingCompanySourceConfig, manager: MagicMock, api: MockAPI, status: int, code: str
) -> None:
    api.responses = [(status, {"ok": False, "code": code, "message": "authentication required"})]
    with pytest.raises(HTTPError) as exc:
        list(sync_items(prompting_company_source(config, inputs("published_content"), manager)))
    assert len(api.requests) == 1
    assert any(pattern in str(exc.value) for pattern in PromptingCompanySource().get_non_retryable_errors())


def test_unknown_table_fails_before_request(
    config: PromptingCompanySourceConfig, manager: MagicMock, api: MockAPI
) -> None:
    with pytest.raises(UnknownResourceError):
        prompting_company_source(config, inputs("unknown"), manager)
    assert api.requests == []
