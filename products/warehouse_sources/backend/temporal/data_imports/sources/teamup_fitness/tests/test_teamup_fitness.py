from dataclasses import replace
from typing import cast
from urllib.parse import urlencode

import pytest
from unittest.mock import MagicMock

import requests_mock
from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import UnknownResourceError
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.teamupfitness import (
    TeamupFitnessSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.teamup_fitness.settings import (
    AUTH_ERROR,
    PERMISSION_ERROR,
    PROVIDER_ERROR,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.teamup_fitness.source import TeamupFitnessSource
from products.warehouse_sources.backend.temporal.data_imports.sources.teamup_fitness.teamup_fitness import (
    TeamupFitnessResumeConfig,
)

BASE_URL = "https://goteamup.com/api/v2"


@pytest.fixture
def config() -> TeamupFitnessSourceConfig:
    return TeamupFitnessSourceConfig(m2m_token="example-m2m-token", provider_id="12345")


@pytest.fixture
def inputs() -> SourceInputs:
    return SourceInputs(
        schema_name="customers",
        schema_id="schema",
        source_id="source",
        team_id=1,
        should_use_incremental_field=False,
        db_incremental_field_last_value="2026-01-01T00:00:00Z",
        db_incremental_field_earliest_value=None,
        incremental_field=None,
        incremental_field_type=None,
        job_id="job",
        logger=MagicMock(),
        reset_pipeline=False,
    )


@pytest.fixture
def manager() -> MagicMock:
    result = MagicMock(spec=ResumableSourceManager)
    result.can_resume.return_value = False
    return result


@pytest.mark.parametrize(
    "endpoint,sort",
    [
        ("customers", None),
        ("customer_memberships", "start_date"),
        ("memberships", None),
        ("events", "start"),
        ("attendances", "event_starts_at"),
        ("invoices", "due_date"),
        ("venues", None),
        ("instructors", None),
    ],
)
def test_full_refresh_requests_and_pagination(
    config: TeamupFitnessSourceConfig, inputs: SourceInputs, manager: MagicMock, endpoint: str, sort: str | None
) -> None:
    inputs = replace(inputs, schema_name=endpoint)
    params: dict[str, str | int] = {"page_size": 100}
    if sort:
        params["sort"] = sort
    next_url = f"{BASE_URL}/{endpoint}?{urlencode({**params, 'page': 2})}"
    with requests_mock.Mocker() as http:
        http.get(
            f"{BASE_URL}/{endpoint}",
            [
                {"json": {"count": 2, "results": [{"id": 1}], "next": next_url}},
                {"json": {"count": 2, "results": [{"id": 2}], "next": None}},
            ],
        )
        response = TeamupFitnessSource().source_for_pipeline(config, manager, inputs)
        pages = iter(cast(Resource, response.items()))
        assert next(pages) == [{"id": 1}]
        assert list(pages) == [[{"id": 2}]]
        manager.save_state.assert_called_once_with(TeamupFitnessResumeConfig(next_url=next_url))
        assert len(http.request_history) == 2
        assert http.request_history[0].qs == {key: [str(value)] for key, value in params.items()}
        assert http.request_history[1].qs == {**{key: [str(value)] for key, value in params.items()}, "page": ["2"]}
        assert http.request_history[1].url == next_url
        for request in http.request_history:
            assert request.method == "GET"
            assert request.headers["Authorization"] == "Bearer example-m2m-token"
            assert request.headers["TeamUp-Request-Mode"] == "provider"
            assert request.headers["TeamUp-Provider-ID"] == "12345"
        assert response.primary_keys == ["id"]


@pytest.mark.parametrize("rows", [[], [{"id": 1}]])
def test_credential_validation_uses_one_small_request(
    config: TeamupFitnessSourceConfig, rows: list[dict[str, int]]
) -> None:
    with requests_mock.Mocker() as http:
        http.get(
            f"{BASE_URL}/customers",
            json={"count": 2, "results": rows, "next": f"{BASE_URL}/customers?page=2"},
        )
        assert TeamupFitnessSource().validate_credentials(config, team_id=1) == (True, None)
        assert len(http.request_history) == 1
        assert http.last_request is not None
        assert http.last_request.qs == {"page_size": ["1"]}
        assert http.last_request.headers["Authorization"] == "Bearer example-m2m-token"
        assert http.last_request.headers["TeamUp-Provider-ID"] == "12345"
        assert http.last_request.headers["TeamUp-Request-Mode"] == "provider"


@pytest.mark.parametrize(
    "status,code,message",
    [
        (401, "authentication_failed", AUTH_ERROR),
        (403, "provider_invalid", PERMISSION_ERROR),
        (400, "provider_header_missing", PROVIDER_ERROR),
        (400, "provider_header_invalid", PROVIDER_ERROR),
    ],
)
def test_authentication_error_mapping(
    config: TeamupFitnessSourceConfig,
    inputs: SourceInputs,
    manager: MagicMock,
    status: int,
    code: str,
    message: str,
) -> None:
    source = TeamupFitnessSource()
    with requests_mock.Mocker() as http:
        http.get(f"{BASE_URL}/customers", status_code=status, json={"code": code})
        assert source.validate_credentials(config, team_id=1) == (False, message)
        response = source.source_for_pipeline(config, manager, inputs)
        with pytest.raises(HTTPError) as error:
            list(cast(Resource, response.items()))
        assert any(
            pattern in str(error.value) and mapped == message
            for pattern, mapped in source.get_non_retryable_errors().items()
        )
        assert len(http.request_history) == 2


def test_validation_does_not_hide_unexpected_errors(config: TeamupFitnessSourceConfig) -> None:
    with requests_mock.Mocker() as http:
        http.get(f"{BASE_URL}/customers", status_code=404, json={"code": "not_found"})
        with pytest.raises(HTTPError):
            TeamupFitnessSource().validate_credentials(config, team_id=1)


def test_missing_results_fails_instead_of_erasing_table(
    config: TeamupFitnessSourceConfig, inputs: SourceInputs, manager: MagicMock
) -> None:
    with requests_mock.Mocker() as http:
        http.get(f"{BASE_URL}/customers", json={"unexpected": [], "next": None})
        response = TeamupFitnessSource().source_for_pipeline(config, manager, inputs)
        with pytest.raises(ValueError, match="Required data_selector"):
            list(cast(Resource, response.items()))


def test_next_url_cannot_send_token_to_another_host(
    config: TeamupFitnessSourceConfig, inputs: SourceInputs, manager: MagicMock
) -> None:
    with requests_mock.Mocker() as http:
        http.get(
            f"{BASE_URL}/customers",
            json={"results": [{"id": 1}], "next": "https://example.com/customers?page=2"},
        )
        response = TeamupFitnessSource().source_for_pipeline(config, manager, inputs)
        with pytest.raises(ValueError):
            list(cast(Resource, response.items()))
        assert len(http.request_history) == 1


def test_unknown_endpoint_fails_before_request(
    config: TeamupFitnessSourceConfig, inputs: SourceInputs, manager: MagicMock
) -> None:
    with requests_mock.Mocker() as http:
        with pytest.raises(UnknownResourceError):
            TeamupFitnessSource().source_for_pipeline(config, manager, replace(inputs, schema_name="unknown"))
        assert http.call_count == 0
