import json
from collections.abc import Generator, Iterable
from dataclasses import replace
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

from requests import HTTPError, Response, Session

from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import ValidateDatabaseHostMixin
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.microsoftdefendercloudapps import (
    MicrosoftDefenderCloudAppsSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.microsoft_defender_cloud_apps.microsoft_defender_cloud_apps import (
    DefenderResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.microsoft_defender_cloud_apps.settings import (
    AUTH_ERROR,
    PERMISSION_ERROR,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.microsoft_defender_cloud_apps.source import (
    MicrosoftDefenderCloudAppsSource,
)

PORTAL_URL = "https://defender.example.com"


def response(body: dict[str, Any], status: int = 200) -> Response:
    result = Response()
    result.status_code = status
    result.reason = {200: "OK", 400: "Bad Request", 401: "Unauthorized", 403: "Forbidden"}.get(status, "Error")
    result.url = f"{PORTAL_URL}/api/v1/alerts/"
    result._content = json.dumps(body).encode()
    result.headers["Content-Type"] = "application/json"
    return result


def rows_from(result: SourceResponse) -> list[Any]:
    pages = cast(Iterable[list[Any]], result.items())
    return [row for page in pages for row in page]


@pytest.fixture
def config() -> MicrosoftDefenderCloudAppsSourceConfig:
    return MicrosoftDefenderCloudAppsSourceConfig.from_dict({"portal_url": PORTAL_URL, "api_token": "fake-token"})


@pytest.fixture
def inputs() -> SourceInputs:
    return SourceInputs(
        schema_name="alerts",
        schema_id="schema",
        source_id="source",
        team_id=1,
        should_use_incremental_field=True,
        db_incremental_field_last_value=1700000000000,
        db_incremental_field_earliest_value=None,
        incremental_field="timestamp",
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


@pytest.fixture
def send() -> Generator[MagicMock]:
    session = Session()
    with (
        patch.object(ValidateDatabaseHostMixin, "is_database_host_valid", return_value=(True, None)),
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session",
            return_value=session,
        ),
        patch.object(session, "send") as mocked,
    ):
        yield mocked
    session.close()


@pytest.mark.parametrize(
    ("endpoint", "incremental", "watermark"),
    [
        ("alerts", True, 1700000000000),
        ("alerts", True, 0),
        ("alerts", True, None),
        ("alerts", False, 1700000000000),
        ("files", False, 1700000000000),
        ("entities", False, 1700000000000),
    ],
)
def test_requests_and_pagination(
    config: MicrosoftDefenderCloudAppsSourceConfig,
    inputs: SourceInputs,
    manager: MagicMock,
    send: MagicMock,
    endpoint: str,
    incremental: bool,
    watermark: int | None,
) -> None:
    send.side_effect = [
        response({"data": [{"_id": "first"}, {"_id": "second"}], "hasNext": True, "total": 1}),
        response({"data": [{"_id": "last"}], "hasNext": False, "total": 999}),
    ]
    inputs = replace(
        inputs,
        schema_name=endpoint,
        should_use_incremental_field=incremental,
        db_incremental_field_last_value=watermark,
    )
    result = MicrosoftDefenderCloudAppsSource().source_for_pipeline(config, manager, inputs)
    rows = rows_from(result)
    assert rows == [{"_id": "first"}, {"_id": "second"}, {"_id": "last"}]
    assert send.call_count == 2
    bodies = []
    for call in send.call_args_list:
        request = call.args[0]
        assert request.method == "POST"
        assert request.url == f"{PORTAL_URL}/api/v1/{endpoint}/"
        assert request.headers["Authorization"] == "Token fake-token"
        assert call.kwargs["allow_redirects"] is False
        assert call.kwargs["timeout"] == (10, 60)
        bodies.append(json.loads(request.body))
    assert [body["skip"] for body in bodies] == [0, 2]
    assert [body["limit"] for body in bodies] == [100, 100]
    assert bodies[0]["filters"] == bodies[1]["filters"]
    if endpoint == "alerts":
        assert result.sort_mode == "asc"
        assert bodies[0]["sortField"] == "date"
        assert bodies[0]["sortDirection"] == "asc"
        assert isinstance(bodies[0]["filters"]["date"]["lte"], int)
        if incremental and watermark is not None:
            assert bodies[0]["filters"]["date"]["gte"] == watermark
        else:
            assert "gte" not in bodies[0]["filters"]["date"]
    else:
        assert bodies[0]["filters"] == {}
    if endpoint == "files":
        assert "sortField" not in bodies[0]
    manager.save_state.assert_called_once()
    assert manager.save_state.call_args.args[0].offset == 2


@pytest.mark.parametrize(
    "body",
    [
        {"data": [], "hasNext": True},
        {"data": [{"_id": "one"}]},
        {"data": [{"_id": "one"}], "hasNext": "false"},
        {"hasNext": False},
    ],
)
def test_malformed_pages_fail_instead_of_truncating(
    config: MicrosoftDefenderCloudAppsSourceConfig,
    body: dict[str, Any],
) -> None:
    result = SourceDriver(MicrosoftDefenderCloudAppsSource(), config).run(
        "alerts", [ScriptedResponse(json=body)], incremental_field="timestamp"
    )
    assert isinstance(result.raised, ValueError)


def test_resume_keeps_original_filter_with_offset(
    config: MicrosoftDefenderCloudAppsSourceConfig,
) -> None:
    result = SourceDriver(MicrosoftDefenderCloudAppsSource(), config).run(
        "alerts",
        [ScriptedResponse(json={"data": [{"_id": "resumed"}], "hasNext": False})],
        resume_state=DefenderResumeConfig(offset=200, since=1000, until=2000),
        incremental_field="timestamp",
        db_incremental_field_last_value=1700000000000,
    )
    assert result.raised is None
    assert result.rows == [{"_id": "resumed"}]
    body = result.requests[0].json()
    assert body["skip"] == 200
    assert body["filters"] == {"date": {"gte": 1000, "lte": 2000}}


@pytest.mark.parametrize(("status", "message"), [(200, None), (401, AUTH_ERROR), (403, PERMISSION_ERROR)])
@pytest.mark.parametrize("endpoint", [None, "files"])
def test_credential_probe_and_errors(
    config: MicrosoftDefenderCloudAppsSourceConfig,
    status: int,
    message: str | None,
    endpoint: str | None,
) -> None:
    source = MicrosoftDefenderCloudAppsSource()
    with scripted_network([ScriptedResponse(status=status, json={"data": [], "hasNext": False})]) as network:
        assert source.validate_credentials(config, 1, endpoint) == (status == 200, message)
    assert len(network.requests_log) == 1
    request = network.requests_log[0]
    assert request.url == f"{PORTAL_URL}/api/v1/{endpoint or 'alerts'}/"
    assert request.headers["authorization"] == "Token fake-token"
    assert request.json() == {"limit": 1, "skip": 0}
    if status != 200:
        with pytest.raises(HTTPError) as error:
            response({"data": [], "hasNext": False}, status).raise_for_status()
        mapped = next(value for key, value in source.get_non_retryable_errors().items() if key in str(error.value))
        assert mapped == message


def test_unexpected_http_errors_propagate(config: MicrosoftDefenderCloudAppsSourceConfig) -> None:
    with scripted_network([ScriptedResponse(status=400, json={})]) as network:
        with pytest.raises(HTTPError):
            MicrosoftDefenderCloudAppsSource().validate_credentials(config, 1)
    assert len(network.requests_log) == 1
