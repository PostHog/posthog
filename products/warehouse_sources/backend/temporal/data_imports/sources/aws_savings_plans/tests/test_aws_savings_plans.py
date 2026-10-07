import json
import datetime as dt
from collections.abc import Iterable
from decimal import Decimal
from typing import Any, cast

import pytest
import time_machine
from unittest.mock import MagicMock, patch

import requests
from botocore.session import get_session

from products.warehouse_sources.backend.temporal.data_imports.sources.aws_savings_plans.aws_savings_plans import (
    AwsSavingsPlansClient,
    AwsSavingsPlansError,
    AwsSavingsPlansResumeConfig,
    AwsSavingsPlansThrottledError,
    aws_savings_plans_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_savings_plans.settings import (
    ENDPOINTS,
    SAVINGS_PLANS_API_VERSION,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.awssavingsplans import (
    AwsSavingsPlansSourceConfig,
)

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.aws_savings_plans.aws_savings_plans"


def config(start_date: str | None = "2025-01-01") -> AwsSavingsPlansSourceConfig:
    return AwsSavingsPlansSourceConfig(
        aws_access_key_id="AKIAEXAMPLE",
        aws_secret_access_key="example-secret",
        aws_session_token="example-session",
        start_date=start_date,
    )


def response(body: Any, status: int = 200, headers: dict[str, str] | None = None) -> requests.Response:
    result = requests.Response()
    result.status_code = status
    result._content = json.dumps(body).encode()
    result.headers.update(headers or {})
    return result


@pytest.fixture
def transport():
    with patch(f"{MODULE}.make_tracked_session") as factory:
        factory.return_value.post.return_value = response({})
        yield factory


@pytest.fixture
def manager() -> MagicMock:
    result = MagicMock(spec=ResumableSourceManager)
    result.can_resume.return_value = False
    return result


@pytest.fixture(autouse=True)
def frozen_time():
    with time_machine.travel("2025-01-12T12:00:00Z", tick=False):
        yield


def run_source(
    manager: MagicMock,
    name: str,
    incremental: bool = False,
    last_value: Any = None,
    start_date: str | None = "2025-01-01",
) -> list[dict[str, Any]]:
    source = aws_savings_plans_source(
        config(start_date), name, manager, incremental, last_value, SAVINGS_PLANS_API_VERSION
    )
    return [row for batch in cast(Iterable[Any], source.items()) for row in batch]


@pytest.mark.parametrize("name", list(ENDPOINTS))
def test_signed_protocol_and_payload_match_service_model(transport: MagicMock, manager: MagicMock, name: str) -> None:
    run_source(manager, name, start_date="2025-01-10")
    call = transport.return_value.post.call_args
    headers = call.kwargs["headers"]
    payload = json.loads(call.kwargs["data"])
    endpoint = ENDPOINTS[name]
    model = get_session().get_service_model(endpoint.service)
    operation = model.operation_model(endpoint.operation)
    assert operation.input_shape is not None
    assert set(payload).issubset(operation.input_shape.members)
    assert headers["X-Amz-Api-Version"] == model.api_version
    assert f"/us-east-1/{endpoint.service}/aws4_request" in headers["Authorization"]
    assert headers["X-Amz-Security-Token"] == "example-session"
    assert headers["X-Amz-Date"]
    assert call.kwargs["timeout"] == 60
    if endpoint.service == "savingsplans":
        assert call.args[0] == "https://savingsplans.amazonaws.com/DescribeSavingsPlans"
        assert headers["Content-Type"] == "application/json"
        assert "X-Amz-Target" not in headers
        assert payload == {"maxResults": 100}
    else:
        assert call.args[0] == "https://ce.us-east-1.amazonaws.com/"
        assert headers["Content-Type"] == "application/x-amz-json-1.1"
        assert headers["X-Amz-Target"] == f"AWSInsightsIndexService.{endpoint.operation}"
        assert payload["TimePeriod"] == {"Start": "2025-01-10", "End": "2025-01-11"}
        if name == "utilization_details_daily":
            assert "Granularity" not in payload
            assert payload["DataType"] == ["ATTRIBUTES", "UTILIZATION", "AMORTIZED_COMMITMENT", "SAVINGS"]
        else:
            assert payload["Granularity"] == "DAILY"
    assert set(transport.call_args.kwargs["redact_values"]) == {"AKIAEXAMPLE", "example-secret", "example-session"}
    transport.return_value.close.assert_called_once()


@pytest.mark.parametrize(
    "name,key,token",
    [
        ("savings_plans", "savingsPlans", "nextToken"),
        ("coverage_daily", "SavingsPlansCoverages", "NextToken"),
        ("utilization_details_daily", "SavingsPlansUtilizationDetails", "NextToken"),
    ],
)
@pytest.mark.parametrize("terminal", [None, ""])
def test_pagination_continues_after_empty_page(
    transport: MagicMock, manager: MagicMock, name: str, key: str, token: str, terminal: str | None
) -> None:
    item = (
        {"savingsPlanArn": "arn:aws:savingsplans::123456789012:savingsplan/example"}
        if name == "savings_plans"
        else {"TimePeriod": {"Start": "2025-01-10", "End": "2025-01-11"}}
    )
    transport.return_value.post.side_effect = [
        response({key: [], token: "next"}),
        response({key: [item], token: terminal}),
    ]
    rows = run_source(manager, name, start_date="2025-01-10")
    assert len(rows) == 1
    calls = transport.return_value.post.call_args_list
    first, second = [json.loads(call.kwargs["data"]) for call in calls]
    assert token not in first
    assert second == {**first, token: "next"}
    assert manager.save_state.call_args.args[0].completed
    manager.clear_state.assert_not_called()
    assert manager.safe_point.call_count == 2


@pytest.mark.parametrize(
    "incremental,last_value,expected",
    [
        (False, "2025-01-10", "2025-01-01"),
        (True, None, "2025-01-01"),
        (True, "2025-01-10T00:00:00Z", "2025-01-03"),
        (True, dt.datetime(2025, 1, 5, tzinfo=dt.UTC), "2025-01-01"),
    ],
)
def test_time_filter_and_restatement(
    transport: MagicMock, manager: MagicMock, incremental: bool, last_value: Any, expected: str
) -> None:
    run_source(manager, "coverage_daily", incremental, last_value)
    payload = json.loads(transport.return_value.post.call_args.kwargs["data"])
    assert payload["TimePeriod"] == {"Start": expected, "End": "2025-01-11"}
    assert "GroupBy" not in payload


def test_details_use_daily_windows_and_preserve_attributes(transport: MagicMock, manager: MagicMock) -> None:
    def answer(url: str, *, data: bytes, **kwargs: Any) -> requests.Response:
        payload = json.loads(data)
        return response(
            {
                "TimePeriod": payload["TimePeriod"],
                "SavingsPlansUtilizationDetails": [
                    {
                        "SavingsPlanArn": "arn:aws:savingsplans::123456789012:savingsplan/example",
                        "Attributes": {"AccountId": "001234567890"},
                        "Utilization": {"TotalCommitment": "1.234567890123456789"},
                        "Savings": {"NetSavings": ""},
                    }
                ],
            }
        )

    transport.return_value.post.side_effect = answer
    rows = run_source(manager, "utilization_details_daily", start_date="2025-01-09")
    assert [row["period_start"] for row in rows] == [dt.datetime(2025, 1, day, tzinfo=dt.UTC) for day in (9, 10)]
    assert rows[0]["attributes"] == {"AccountId": "001234567890"}
    assert rows[0]["utilization_total_commitment"] == Decimal("1.234567890123456789")
    assert rows[0]["savings_net_savings"] is None
    assert rows[0]["savings_plan_arn"] == rows[1]["savings_plan_arn"]


def test_plan_inventory_ignores_incremental_cursor(transport: MagicMock, manager: MagicMock) -> None:
    transport.return_value.post.return_value = response(
        {
            "savingsPlans": [
                {
                    "savingsPlanArn": "arn:aws:savingsplans::123456789012:savingsplan/example",
                    "start": "2025-01-01T00:00:00Z",
                    "commitment": "0.1234567890123456789",
                    "tags": {"account": "001"},
                }
            ]
        }
    )
    rows = run_source(manager, "savings_plans", True, "invalid")
    assert json.loads(transport.return_value.post.call_args.kwargs["data"]) == {"maxResults": 100}
    assert rows[0]["start"] == dt.datetime(2025, 1, 1, tzinfo=dt.UTC)
    assert rows[0]["commitment"] == Decimal("0.1234567890123456789")
    assert rows[0]["tags"] == {"account": "001"}


def test_resume_keeps_original_window_and_stages_before_yield(transport: MagicMock, manager: MagicMock) -> None:
    manager.can_resume.return_value = True
    manager.load_state.return_value = AwsSavingsPlansResumeConfig(
        next_token="resume",
        window_start="2025-01-02",
        window_end="2025-01-03",
        end_date="2025-01-03",
    )
    transport.return_value.post.return_value = response(
        {"SavingsPlansCoverages": [{"TimePeriod": {"Start": "2025-01-02", "End": "2025-01-03"}}]}
    )
    source = aws_savings_plans_source(
        config(), "coverage_daily", manager, True, "2025-01-10", SAVINGS_PLANS_API_VERSION
    )
    iterator = iter(cast(Iterable[Any], source.items()))
    next(iterator)
    assert json.loads(transport.return_value.post.call_args.kwargs["data"]) == {
        "TimePeriod": {"Start": "2025-01-02", "End": "2025-01-03"},
        "MaxResults": 100,
        "Granularity": "DAILY",
        "NextToken": "resume",
    }
    assert manager.save_state.call_args.args[0].completed
    assert list(iterator) == []
    manager.clear_state.assert_not_called()
    assert source.on_complete is not None
    source.on_complete()
    manager.clear_state.assert_called_once()


@pytest.mark.parametrize("completed,start_date", [(True, "2025-01-01"), (False, "2025-01-12")])
def test_completed_or_future_window_makes_no_requests(
    transport: MagicMock, manager: MagicMock, completed: bool, start_date: str
) -> None:
    if completed:
        manager.can_resume.return_value = True
        manager.load_state.return_value = AwsSavingsPlansResumeConfig(completed=True)
    assert run_source(manager, "coverage_daily", start_date=start_date) == []
    transport.return_value.post.assert_not_called()


def test_repeated_token_fails_instead_of_looping(transport: MagicMock, manager: MagicMock) -> None:
    transport.return_value.post.return_value = response({"savingsPlans": [], "nextToken": "same"})
    with pytest.raises(ValueError, match="repeated pagination token"):
        run_source(manager, "savings_plans")
    assert transport.return_value.post.call_count == 2
    transport.return_value.close.assert_called_once()


@pytest.mark.parametrize(
    "body,headers,status,code,error_type",
    [
        (
            {"__type": "vendor#AccessDeniedException", "message": "private detail"},
            {},
            400,
            "AccessDeniedException",
            AwsSavingsPlansError,
        ),
        (
            {},
            {"x-amzn-ErrorType": "InvalidSignatureException:detail"},
            403,
            "InvalidSignatureException",
            AwsSavingsPlansError,
        ),
        ({"code": "UnrecognizedClientException"}, {}, 400, "UnrecognizedClientException", AwsSavingsPlansError),
        ([], {}, 502, "HTTP 502", AwsSavingsPlansError),
        ({"__type": "LimitExceededException"}, {}, 400, "LimitExceededException", AwsSavingsPlansThrottledError),
        ({"__type": "LimitExceededException"}, {}, 429, "LimitExceededException", AwsSavingsPlansError),
    ],
)
def test_error_parsing_and_no_duplicate_status_retry(
    transport: MagicMock, body: Any, headers: dict[str, str], status: int, code: str, error_type: type[Exception]
) -> None:
    transport.return_value.post.return_value = response(body, status, headers)
    client = AwsSavingsPlansClient(config(), SAVINGS_PLANS_API_VERSION)
    with pytest.raises(error_type) as error:
        cast(Any, AwsSavingsPlansClient.request).__wrapped__(client, ENDPOINTS["savings_plans"], {})
    assert type(error.value) is error_type
    assert str(error.value) == f"AWS Savings Plans request failed: {code}"
    assert transport.return_value.post.call_count == 1


@pytest.mark.parametrize(
    "code,schema,valid,message",
    [
        ("AccessDeniedException", None, True, None),
        ("AccessDeniedException", "coverage_daily", False, "ce:GetSavingsPlansCoverage"),
        ("UnauthorizedException", None, True, None),
        ("UnauthorizedException", "savings_plans", False, "savingsplans:DescribeSavingsPlans"),
        ("InvalidSignatureException", None, False, "signature"),
        ("UnrecognizedClientException", None, False, "credentials"),
        ("ExpiredTokenException", None, False, "expired"),
        ("SubscriptionRequiredException", None, False, "Enable Cost Explorer"),
        ("DataUnavailableException", "utilization_daily", False, "no data"),
    ],
)
def test_credential_errors(
    transport: MagicMock, code: str, schema: str | None, valid: bool, message: str | None
) -> None:
    transport.return_value.post.return_value = response({"__type": code, "message": "private IAM ARN"}, 400)
    result, reason = validate_credentials(config(), schema)
    assert result is valid
    assert reason is None if message is None else message in (reason or "")
    assert "private" not in (reason or "")
    assert transport.return_value.post.call_count == 1
    transport.return_value.close.assert_called_once()


@pytest.mark.parametrize("schema,key", [(None, "maxResults"), ("coverage_daily", "MaxResults")])
def test_validation_probe_is_one_small_request(transport: MagicMock, schema: str | None, key: str) -> None:
    assert validate_credentials(config(), schema) == (True, None)
    assert transport.return_value.post.call_count == 1
    assert json.loads(transport.return_value.post.call_args.kwargs["data"])[key] == 1


@pytest.mark.parametrize("start_date", [None, "2020-01-01"])
def test_history_is_bounded(transport: MagicMock, manager: MagicMock, start_date: str | None) -> None:
    run_source(manager, "utilization_daily", start_date=start_date)
    calls = [json.loads(call.kwargs["data"]) for call in transport.return_value.post.call_args_list]
    assert calls[0]["TimePeriod"]["Start"] == "2024-01-12"
    assert calls[-1]["TimePeriod"]["End"] == "2025-01-11"
    assert all(first["TimePeriod"]["End"] == second["TimePeriod"]["Start"] for first, second in zip(calls, calls[1:]))


@pytest.mark.parametrize(
    "start_date,schema,expected",
    [
        ("invalid", None, "YYYY-MM-DD"),
        ("2025-01-01", "unknown", "Unknown"),
    ],
)
def test_invalid_configuration_makes_no_requests(
    transport: MagicMock, start_date: str, schema: str | None, expected: str
) -> None:
    valid, message = validate_credentials(config(start_date), schema)
    assert not valid
    assert expected in (message or "")
    transport.return_value.post.assert_not_called()


def test_network_failure_closes_session(transport: MagicMock) -> None:
    transport.return_value.post.side_effect = requests.Timeout("private connection detail")
    assert validate_credentials(config()) == (False, "Could not reach AWS. Try again later.")
    transport.return_value.close.assert_called_once()
