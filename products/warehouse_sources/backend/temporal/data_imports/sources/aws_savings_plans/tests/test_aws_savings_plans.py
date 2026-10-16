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
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_savings_plans.source import (
    AwsSavingsPlansSource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
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


def driver(start_date: str | None = "2025-01-01") -> SourceDriver:
    return SourceDriver(AwsSavingsPlansSource(), config(start_date))


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


FAN_OUT_ENDPOINTS = [name for name, endpoint in ENDPOINTS.items() if endpoint.fan_out]
RECOMMENDED_OPTIONS = ("COMPUTE_SP", "ONE_YEAR", "NO_UPFRONT", "THIRTY_DAYS")


def operation(request: RecordedRequest) -> str:
    return request.headers.get("x-amz-target", request.path).rsplit(".", 1)[-1].lstrip("/")


def assert_matches_service_model(request: RecordedRequest) -> None:
    service = "ce" if "x-amz-target" in request.headers else "savingsplans"
    input_shape = get_session().get_service_model(service).operation_model(operation(request)).input_shape
    assert input_shape is not None
    assert set(input_shape.required_members) <= set(request.json()) <= set(input_shape.members)


def fan_out_answer(request: RecordedRequest) -> ScriptedResponse:
    payload = request.json()
    match operation(request):
        case "DescribeSavingsPlans":
            return ScriptedResponse(json={"savingsPlans": [{"savingsPlanId": "plan-b"}, {"savingsPlanId": "plan-a"}]})
        case "DescribeSavingsPlanRates":
            rate = {"rate": "0.05", "usageType": "USE1-BoxUsage:c5.large", "operation": "RunInstances"}
            if "nextToken" in payload:
                return ScriptedResponse(json={"searchResults": [{**rate, "usageType": "USE1-Fargate-vCPU-Hours"}]})
            return ScriptedResponse(json={"searchResults": [rate], "nextToken": "page-2"})
        case "GetSavingsPlansPurchaseRecommendation":
            options = tuple(
                payload[key] for key in ("SavingsPlansType", "TermInYears", "PaymentOption", "LookbackPeriodInDays")
            )
            if options != RECOMMENDED_OPTIONS:
                return ScriptedResponse(json={"Metadata": {"RecommendationId": "empty"}})
            detail_id = "detail-2" if "NextPageToken" in payload else "detail-1"
            return ScriptedResponse(
                json={
                    "Metadata": {"RecommendationId": "rec", "GenerationTimestamp": "2025-01-11T00:00:00Z"},
                    "SavingsPlansPurchaseRecommendation": {
                        "SavingsPlansType": options[0],
                        "LookbackPeriodInDays": options[3],
                        "SavingsPlansPurchaseRecommendationSummary": {"EstimatedROI": "1"},
                        "SavingsPlansPurchaseRecommendationDetails": [
                            {
                                "RecommendationDetailId": detail_id,
                                "SavingsPlansDetails": {"Region": "us-east-1", "OfferingId": "offering"},
                                "AccountId": "001234567890",
                                "EstimatedROI": "12.5",
                                "UpfrontCost": "",
                            }
                        ],
                    },
                    **({} if "NextPageToken" in payload else {"NextPageToken": "page-2"}),
                }
            )
        case "GetSavingsPlanPurchaseRecommendationDetails":
            return ScriptedResponse(
                json={
                    "RecommendationDetailId": payload["RecommendationDetailId"],
                    "RecommendationDetailData": {
                        "CurrentAverageCoverage": "40.5",
                        "LatestUsageTimestamp": "2025-01-10T23:00:00Z",
                        "MetricsOverLookbackPeriod": [{"StartTime": "2025-01-10T00:00:00Z", "CurrentCoverage": "40"}],
                    },
                }
            )
    raise AssertionError(f"unexpected request {request.path}")


@pytest.mark.parametrize(
    "name,expected",
    [
        (
            "savings_plan_rates",
            [
                ("plan-a", "USE1-BoxUsage:c5.large", Decimal("0.05")),
                ("plan-a", "USE1-Fargate-vCPU-Hours", Decimal("0.05")),
                ("plan-b", "USE1-BoxUsage:c5.large", Decimal("0.05")),
                ("plan-b", "USE1-Fargate-vCPU-Hours", Decimal("0.05")),
            ],
        ),
        (
            "purchase_recommendations",
            [
                ("detail-1", "COMPUTE_SP", "us-east-1", "001234567890", Decimal("12.5"), None, "rec"),
                ("detail-2", "COMPUTE_SP", "us-east-1", "001234567890", Decimal("12.5"), None, "rec"),
            ],
        ),
        (
            "purchase_recommendation_details",
            [
                ("detail-1", Decimal("40.5"), dt.datetime(2025, 1, 10, 23, tzinfo=dt.UTC), "40"),
                ("detail-2", Decimal("40.5"), dt.datetime(2025, 1, 10, 23, tzinfo=dt.UTC), "40"),
            ],
        ),
    ],
)
def test_fan_out_walks_every_parent_and_child_page(name: str, expected: list[tuple[Any, ...]]) -> None:
    result = driver().run(name, fan_out_answer)
    assert result.raised is None
    for request in result.requests:
        assert_matches_service_model(request)
    rows = result.rows
    actual: list[tuple[Any, ...]]
    if name == "savings_plan_rates":
        actual = [(row["savings_plan_id"], row["usage_type"], row["rate"]) for row in rows]
    elif name == "purchase_recommendations":
        assert rows[0]["generation_timestamp"] == dt.datetime(2025, 1, 11, tzinfo=dt.UTC)
        assert "savings_plans_purchase_recommendation_summary" not in rows[0]
        actual = [
            (
                row["recommendation_detail_id"],
                row["savings_plans_type"],
                row["region"],
                row["account_id"],
                row["estimated_roi"],
                row["upfront_cost"],
                row["recommendation_id"],
            )
            for row in rows
        ]
    else:
        actual = [
            (
                row["recommendation_detail_id"],
                row["current_average_coverage"],
                row["latest_usage_timestamp"],
                row["metrics_over_lookback_period"][0]["CurrentCoverage"],
            )
            for row in rows
        ]
    assert actual == expected
    assert result.committed_states[-1].completed


@pytest.mark.parametrize(
    "resume_token,expected",
    [
        ("page-2", [("plan-a", "page-2"), ("plan-b", None), ("plan-b", "page-2")]),
        (None, [("plan-b", None), ("plan-b", "page-2")]),
    ],
)
def test_fan_out_resumes_after_finished_parents(resume_token: str | None, expected: list[tuple[str, Any]]) -> None:
    result = driver().run(
        "savings_plan_rates",
        fan_out_answer,
        resume_state=AwsSavingsPlansResumeConfig(parent_id="plan-a", next_token=resume_token),
    )
    assert result.raised is None
    rate_requests = [request.json() for request in result.requests if operation(request) == "DescribeSavingsPlanRates"]
    assert [(payload["savingsPlanId"], payload.get("nextToken")) for payload in rate_requests] == expected


@pytest.mark.parametrize(
    "name,answer,expected",
    [
        ("savings_plan_rates", fan_out_answer, ["DescribeSavingsPlans", "DescribeSavingsPlanRates"]),
        ("savings_plan_rates", lambda _: ScriptedResponse(json={}), ["DescribeSavingsPlans"]),
        ("purchase_recommendations", fan_out_answer, ["GetSavingsPlansPurchaseRecommendation"]),
        (
            "purchase_recommendation_details",
            lambda _: ScriptedResponse(json={}),
            ["GetSavingsPlansPurchaseRecommendation"],
        ),
    ],
)
def test_fan_out_validation_probes_child_with_a_parent(name: str, answer: Any, expected: list[str]) -> None:
    with scripted_network(answer) as network:
        assert validate_credentials(config(), name) == (True, None)
    assert [operation(request) for request in network.requests_log] == expected
    for request in network.requests_log:
        assert_matches_service_model(request)


@pytest.mark.parametrize("name", [name for name in ENDPOINTS if name not in FAN_OUT_ENDPOINTS])
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
        assert call.args[0] == f"https://savingsplans.amazonaws.com/{endpoint.operation}"
        assert headers["Content-Type"] == "application/json"
        assert "X-Amz-Target" not in headers
        assert payload == {"maxResults": endpoint.page_size}
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
def test_pagination_continues_after_empty_page(name: str, key: str, token: str, terminal: str | None) -> None:
    item = (
        {"savingsPlanArn": "arn:aws:savingsplans::123456789012:savingsplan/example"}
        if name == "savings_plans"
        else {"TimePeriod": {"Start": "2025-01-10", "End": "2025-01-11"}}
    )
    result = driver("2025-01-10").run(
        name,
        [ScriptedResponse(json={key: [], token: "next"}), ScriptedResponse(json={key: [item], token: terminal})],
    )
    assert result.raised is None
    assert len(result.rows) == 1
    first, second = [request.json() for request in result.requests]
    assert token not in first
    assert second == {**first, token: "next"}
    assert len(result.saved_states) == 2
    assert result.saved_states[-1].completed
    assert result.committed_states[-1].completed
    assert result.final_state == result.saved_states[-1]


@pytest.mark.parametrize(
    "incremental,last_value,expected",
    [
        (False, "2025-01-10", "2025-01-01"),
        (True, None, "2025-01-01"),
        (True, "2025-01-10T00:00:00Z", "2025-01-03"),
        (True, dt.datetime(2025, 1, 5, tzinfo=dt.UTC), "2025-01-01"),
    ],
)
def test_time_filter_and_restatement(incremental: bool, last_value: Any, expected: str) -> None:
    result = driver().run(
        "coverage_daily",
        [ScriptedResponse(json={})],
        should_use_incremental_field=incremental,
        db_incremental_field_last_value=last_value,
    )
    assert result.raised is None
    payload = result.requests[0].json()
    assert payload["TimePeriod"] == {"Start": expected, "End": "2025-01-11"}
    assert "GroupBy" not in payload


def test_details_use_daily_windows_and_preserve_attributes() -> None:
    def answer(request: RecordedRequest) -> ScriptedResponse:
        return ScriptedResponse(
            json={
                "TimePeriod": request.json()["TimePeriod"],
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

    result = driver("2025-01-09").run("utilization_details_daily", answer)
    assert result.raised is None
    rows = result.rows
    assert [row["period_start"] for row in rows] == [dt.datetime(2025, 1, day, tzinfo=dt.UTC) for day in (9, 10)]
    assert rows[0]["attributes"] == {"AccountId": "001234567890"}
    assert rows[0]["utilization_total_commitment"] == Decimal("1.234567890123456789")
    assert rows[0]["savings_net_savings"] is None
    assert rows[0]["savings_plan_arn"] == rows[1]["savings_plan_arn"]


def test_plan_inventory_ignores_incremental_cursor() -> None:
    result = driver().run(
        "savings_plans",
        [
            ScriptedResponse(
                json={
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
        ],
        should_use_incremental_field=True,
        db_incremental_field_last_value="invalid",
    )
    assert result.raised is None
    rows = result.rows
    assert result.requests[0].json() == {"maxResults": 100}
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
def test_completed_or_future_window_makes_no_requests(completed: bool, start_date: str) -> None:
    result = driver(start_date).run(
        "coverage_daily", [], resume_state=AwsSavingsPlansResumeConfig(completed=True) if completed else None
    )
    assert result.raised is None
    assert result.rows == []
    assert result.requests == []


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
        ("AccessDeniedException", "savings_plan_rates", False, "savingsplans:DescribeSavingsPlans"),
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
def test_validation_probe_is_one_small_request(schema: str | None, key: str) -> None:
    with scripted_network([ScriptedResponse(json={})]) as network:
        assert validate_credentials(config(), schema) == (True, None)
    assert len(network.requests_log) == 1
    assert network.requests_log[0].json()[key] == 1


@pytest.mark.parametrize("start_date", [None, "2020-01-01"])
def test_history_is_bounded(start_date: str | None) -> None:
    result = driver(start_date).run("utilization_daily", always(ScriptedResponse(json={})))
    assert result.raised is None
    calls = [request.json() for request in result.requests]
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
def test_invalid_configuration_makes_no_requests(start_date: str, schema: str | None, expected: str) -> None:
    with scripted_network([]) as network:
        valid, message = validate_credentials(config(start_date), schema)
    assert not valid
    assert expected in (message or "")
    assert network.requests_log == []


def test_network_failure_closes_session(transport: MagicMock) -> None:
    transport.return_value.post.side_effect = requests.Timeout("private connection detail")
    assert validate_credentials(config()) == (False, "Could not reach AWS. Try again later.")
    transport.return_value.close.assert_called_once()
