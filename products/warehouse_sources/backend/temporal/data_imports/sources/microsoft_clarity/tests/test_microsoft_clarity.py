from typing import Any

import time_machine

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.microsoftclarity import (
    MicrosoftClaritySourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.microsoft_clarity.microsoft_clarity import (
    CLARITY_UNREACHABLE_ERROR,
    INSIGHTS_PATH,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.microsoft_clarity.settings import ENDPOINT_NAME
from products.warehouse_sources.backend.temporal.data_imports.sources.microsoft_clarity.source import (
    MicrosoftClaritySource,
)


def _driver() -> SourceDriver:
    return SourceDriver(MicrosoftClaritySource(), MicrosoftClaritySourceConfig(api_token="token"))


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, [], True, None, {}),
            (
                "unauthorized",
                401,
                None,
                False,
                "Your Microsoft Clarity API token is invalid or expired. Generate a new token in Clarity "
                "under Settings -> Data Export and reconnect.",
                {},
            ),
            (
                "forbidden",
                403,
                None,
                False,
                "Your Microsoft Clarity API token isn't authorized for this project. Generate one in the "
                "Clarity project you want to sync, under Settings -> Data Export, then reconnect.",
                {},
            ),
            ("quota_exceeded_still_valid", 429, None, True, None, {"Retry-After": "3600"}),
            ("server_error", 503, None, False, CLARITY_UNREACHABLE_ERROR, {"Retry-After": "120"}),
            (
                "unexpected_status",
                400,
                None,
                False,
                "Microsoft Clarity rejected the connection check. Confirm the token is still listed in Clarity "
                "under Settings -> Data Export, then reconnect.",
                {},
            ),
        ]
    )
    def test_status_mapping(
        self,
        _name: str,
        status: int,
        json_body: Any,
        expected_valid: bool,
        expected_error: str | None,
        headers: dict[str, str],
    ) -> None:
        with scripted_network(always(ScriptedResponse(status=status, json=json_body, headers=headers))) as network:
            valid, error = validate_credentials("token")

        assert valid is expected_valid
        assert error == expected_error
        assert len(network.requests_log) == 1
        assert network.elapsed == 0
        assert {request.path for request in network.requests_log} == {INSIGHTS_PATH}
        assert {request.param("numOfDays") for request in network.requests_log} == {"1"}
        assert {request.headers["authorization"] for request in network.requests_log} == {"Bearer token"}
        assert network.session_options[0]["redact_values"] == ("token",)

    def test_transport_exception_is_invalid(self) -> None:
        with scripted_network(always(requests.ConnectionError("down"))) as network:
            valid, error = validate_credentials("token")

        assert valid is False
        assert error == CLARITY_UNREACHABLE_ERROR
        assert {request.path for request in network.requests_log} == {INSIGHTS_PATH}


SAMPLE_PAYLOAD = [
    {
        "metricName": "Traffic",
        "information": [
            {
                "totalSessionCount": "9554",
                "totalBotSessionCount": "8369",
                "distantUserCount": "189733",
                "PagesPerSessionPercentage": 1.0931,
                "OS": "Other",
            },
            {
                "totalSessionCount": "291942",
                "totalBotSessionCount": "31076",
                "distantUserCount": "212836",
                "PagesPerSessionPercentage": 2.2609,
                "OS": "Android",
            },
        ],
    },
    {
        "metricName": "ScrollDepth",
        "information": [{"averageScrollDepthPercentage": 45.2, "OS": "Other"}],
    },
]


class TestMicrosoftClaritySource:
    @time_machine.travel("2026-07-23T12:00:00Z", tick=False)
    def test_flattens_every_metric_and_information_row(self) -> None:
        driver = SourceDriver(
            MicrosoftClaritySource(), MicrosoftClaritySourceConfig(api_token="token", dimension1="OS")
        )
        result = driver.run(ENDPOINT_NAME, [ScriptedResponse(json=SAMPLE_PAYLOAD)])

        assert result.raised is None
        assert result.paths == [INSIGHTS_PATH]
        assert result.requests[0].param("dimension1") == "OS"
        assert result.requests[0].param("numOfDays") == "1"
        rows = result.rows
        assert len(rows) == 3
        assert rows[0]["metric_name"] == "Traffic"
        assert rows[0]["row_index"] == 0
        assert rows[0]["OS"] == "Other"
        assert rows[0]["synced_at"] == "2026-07-23T12:00:00+00:00"
        assert rows[1]["metric_name"] == "Traffic"
        assert rows[1]["row_index"] == 1
        assert rows[1]["OS"] == "Android"
        assert rows[2]["metric_name"] == "ScrollDepth"
        assert rows[2]["row_index"] == 0

    def test_non_list_payload_yields_no_rows(self) -> None:
        result = _driver().run(ENDPOINT_NAME, [ScriptedResponse(json={"unexpected": "shape"})])

        assert result.raised is None
        assert result.rows == []

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("quota_exceeded", 429), ("server_error", 500)])
    def test_error_status_raises(self, _name: str, status: int) -> None:
        answer = ScriptedResponse(status=status, body=b"boom")
        script = always(answer) if status in (429, 500) else [answer]
        result = _driver().run(ENDPOINT_NAME, script)

        assert isinstance(result.raised, requests.HTTPError)
        assert {request.path for request in result.requests} == {INSIGHTS_PATH}
