from urllib.parse import urlencode

import pytest

from requests.exceptions import HTTPError

from products.warehouse_sources.sources.sdk.testing import ScriptedResponse, SourceDriver, always, scripted_network
from products.warehouse_sources.sources.teamup_fitness._config import TeamupFitnessSourceConfig
from products.warehouse_sources.sources.teamup_fitness.settings import PROVIDER_ERROR
from products.warehouse_sources.sources.teamup_fitness.source import TeamupFitnessSource
from products.warehouse_sources.sources.teamup_fitness.teamup_fitness import TeamupFitnessResumeConfig

BASE_URL = "https://goteamup.com/api/v2"


@pytest.fixture
def config() -> TeamupFitnessSourceConfig:
    return TeamupFitnessSourceConfig(m2m_token="example-m2m-token", provider_id="12345")


@pytest.fixture
def driver(config: TeamupFitnessSourceConfig) -> SourceDriver:
    return SourceDriver(TeamupFitnessSource(), config)


@pytest.mark.parametrize(
    "endpoint,path,sort",
    [
        ("customers", "customers", None),
        ("customer_memberships", "customer_memberships", "start_date"),
        ("memberships", "memberships", None),
        ("events", "events", "start"),
        ("attendances", "attendances", "event_starts_at"),
        ("invoices", "invoices", "due_date"),
        ("venues", "venues", None),
        ("instructors", "instructors", None),
        ("membership_categories", "membership_categories", None),
        ("offering_types", "offering_types", None),
        ("lead_sources", "crm/lead_sources", None),
        ("payment_subscriptions", "payment_subscriptions", None),
        ("membership_payment_plans", "membership_payment_plans", None),
        ("customer_membership_holds", "customer_membership_holds", None),
        ("discount_codes", "discount_codes", None),
        ("crm_status_changes", "crm/status_changes", None),
    ],
)
def test_full_refresh_requests_and_pagination(driver: SourceDriver, endpoint: str, path: str, sort: str | None) -> None:
    params: dict[str, str | int] = {"page_size": 100}
    if sort:
        params["sort"] = sort
    next_url = f"{BASE_URL}/{path}?{urlencode({**params, 'page': 2})}"
    result = driver.run(
        endpoint,
        [
            ScriptedResponse(json={"count": 2, "results": [{"id": 1}], "next": next_url}),
            ScriptedResponse(json={"count": 2, "results": [{"id": 2}], "next": None}),
        ],
    )

    assert result.items == [[{"id": 1}], [{"id": 2}]]
    assert result.saved_states == [TeamupFitnessResumeConfig(next_url=next_url)]
    assert len(result.requests) == 2
    assert result.requests[0].path == f"/api/v2/{path}"
    assert dict(result.requests[0].query) == {key: (str(value),) for key, value in params.items()}
    assert dict(result.requests[1].query) == {**{key: (str(value),) for key, value in params.items()}, "page": ("2",)}
    assert result.requests[1].url == next_url
    for request in result.requests:
        assert request.method == "GET"
        assert request.headers["authorization"] == "Bearer example-m2m-token"
        assert request.headers["teamup-request-mode"] == "provider"
        assert request.headers["teamup-provider-id"] == "12345"
    assert result.response is not None
    assert result.response.primary_keys == ["id"]


@pytest.mark.parametrize("rows", [[], [{"id": 1}]])
def test_credential_validation_uses_one_small_request(
    config: TeamupFitnessSourceConfig, rows: list[dict[str, int]]
) -> None:
    with scripted_network(
        always(ScriptedResponse(json={"count": 2, "results": rows, "next": f"{BASE_URL}/customers?page=2"}))
    ) as network:
        assert TeamupFitnessSource().validate_credentials(config, team_id=1) == (True, None)

    assert len(network.requests_log) == 1
    request = network.requests_log[0]
    assert dict(request.query) == {"page_size": ("1",)}
    assert request.headers["authorization"] == "Bearer example-m2m-token"
    assert request.headers["teamup-provider-id"] == "12345"
    assert request.headers["teamup-request-mode"] == "provider"


@pytest.mark.parametrize(
    "status,code,message",
    [
        (400, "provider_header_missing", PROVIDER_ERROR),
        (400, "provider_header_invalid", PROVIDER_ERROR),
    ],
)
def test_authentication_error_mapping(
    config: TeamupFitnessSourceConfig, driver: SourceDriver, status: int, code: str, message: str
) -> None:
    source = TeamupFitnessSource()
    answer = always(ScriptedResponse(status=status, json={"code": code}))
    with scripted_network(answer) as network:
        assert source.validate_credentials(config, team_id=1) == (False, message)
    result = driver.run("customers", answer)

    assert isinstance(result.raised, HTTPError)
    assert any(
        pattern in str(result.raised) and mapped == message
        for pattern, mapped in source.get_non_retryable_errors().items()
    )
    assert len(network.requests_log) + len(result.requests) == 2


def test_validation_does_not_hide_unexpected_errors(config: TeamupFitnessSourceConfig) -> None:
    with scripted_network(always(ScriptedResponse(status=404, json={"code": "not_found"}))):
        with pytest.raises(HTTPError):
            TeamupFitnessSource().validate_credentials(config, team_id=1)


def test_missing_results_fails_instead_of_erasing_table(driver: SourceDriver) -> None:
    result = driver.run("customers", [ScriptedResponse(json={"unexpected": [], "next": None})])

    assert isinstance(result.raised, ValueError)
    assert "Required data_selector" in str(result.raised)


def test_next_url_cannot_send_token_to_another_host(driver: SourceDriver) -> None:
    result = driver.run(
        "customers",
        [ScriptedResponse(json={"results": [{"id": 1}], "next": "https://example.com/customers?page=2"})],
    )

    assert isinstance(result.raised, ValueError)
    assert len(result.requests) == 1
