import pytest

from requests.exceptions import ConnectionError, HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.kisi import KisiSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.kisi.kisi import KisiResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.kisi.settings import (
    AUTH_ERROR,
    OFFSET_ERROR,
    PERMISSION_ERROR,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.kisi.source import KisiSource


@pytest.fixture
def driver() -> SourceDriver:
    return SourceDriver(KisiSource(), KisiSourceConfig(api_key="test-key"))


@pytest.mark.parametrize("start_offset", [None, 100])
@pytest.mark.parametrize("last_page_size", [0, 1, 100])
@pytest.mark.parametrize("use_header", [False, True])
def test_pagination_and_resume(
    start_offset: int | None, last_page_size: int, use_header: bool, driver: SourceDriver
) -> None:
    offset = start_offset or 0
    first_page: list[dict[str, object]] = [{"id": offset + i} for i in range(100)]
    last_page: list[dict[str, object]] = [{"id": offset + 100 + i} for i in range(last_page_size)]
    total = offset + 100 + last_page_size
    pages = [
        ScriptedResponse(
            json=first_page,
            headers={"X-Collection-Range": f"{offset}-{offset + 99}/{total}"} if use_header else {},
        ),
        ScriptedResponse(
            json=last_page,
            headers={"X-Collection-Range": f"{offset + 100}-{offset + 199}/{total}"} if use_header else {},
        ),
        ScriptedResponse(json=[]),
    ]
    result = driver.run(
        "locks",
        pages,
        resume_state=KisiResumeConfig(offset=offset) if start_offset is not None else None,
    )

    expected_offsets = [offset]
    if not use_header or last_page_size:
        expected_offsets.append(offset + 100)
    if not use_header and last_page_size == 100:
        expected_offsets.append(offset + 200)
    assert result.raised is None
    assert result.rows == first_page + last_page
    assert result.params("offset") == [str(value) for value in expected_offsets]
    assert result.saved_states == [KisiResumeConfig(offset=value) for value in expected_offsets[1:]]


@pytest.mark.parametrize("total,should_fail", [(20_100, False), (20_101, True)])
def test_offset_limit_does_not_silently_truncate(total: int, should_fail: bool, driver: SourceDriver) -> None:
    rows: list[dict[str, object]] = [{"id": 20_000 + i} for i in range(100)]
    result = driver.run(
        "locks",
        [ScriptedResponse(json=rows, headers={"X-Collection-Range": f"20000-20099/{total}"})],
        resume_state=KisiResumeConfig(offset=20_000),
    )

    assert result.params("offset") == ["20000"]
    if should_fail:
        assert isinstance(result.raised, ValueError)
        assert OFFSET_ERROR in str(result.raised)
    else:
        assert result.raised is None
        assert result.items == [rows]


@pytest.mark.parametrize("status,message", [(401, AUTH_ERROR), (403, PERMISSION_ERROR)])
def test_sync_auth_errors(status: int, message: str, driver: SourceDriver) -> None:
    result = driver.run("locks", [ScriptedResponse(status=status, json=[])])

    assert isinstance(result.raised, HTTPError)
    assert message in [
        text for pattern, text in KisiSource().get_non_retryable_errors().items() if pattern in str(result.raised)
    ]
    assert result.paths == ["/locks"]


@pytest.mark.parametrize(
    "status,message",
    [
        (200, None),
        (401, AUTH_ERROR),
        (403, PERMISSION_ERROR),
        (500, "Kisi could not validate the API key. Try again later."),
        (302, "Kisi returned an unexpected response. Try again later."),
    ],
)
def test_validate_credentials(status: int, message: str | None) -> None:
    response = ScriptedResponse(
        status=status,
        json=[],
        headers={"Location": "/redirected"} if status == 302 else {},
    )
    with scripted_network(always(response)) as network:
        assert KisiSource().validate_credentials(KisiSourceConfig(api_key="test-key"), 1) == (status == 200, message)

    assert {request.path for request in network.requests_log} == {"/user"}
    assert network.requests_log[0].url == "https://api.kisi.io/user"
    assert network.requests_log[0].headers["authorization"] == "KISI-LOGIN test-key"
    if status != 500:
        assert len(network.requests_log) == 1


def test_validate_connection_error() -> None:
    with scripted_network(always(ConnectionError("private detail"))) as network:
        assert KisiSource().validate_credentials(KisiSourceConfig(api_key="test-key"), 1) == (
            False,
            "Could not connect to Kisi. Try again later.",
        )

    assert {request.path for request in network.requests_log} == {"/user"}


def test_unsupported_table(driver: SourceDriver) -> None:
    result = driver.run("events", [])

    assert isinstance(result.raised, ValueError)
    assert "Unsupported Kisi table" in str(result.raised)
    assert result.requests == []
