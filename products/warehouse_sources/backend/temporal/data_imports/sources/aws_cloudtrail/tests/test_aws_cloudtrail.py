import json
import datetime as dt
from collections.abc import Iterable, Iterator
from typing import Any, cast

import pytest
import time_machine
from unittest.mock import Mock, patch

import requests
import structlog
from botocore.loaders import Loader

from products.warehouse_sources.backend.temporal.data_imports.sources.aws_cloudtrail import aws_cloudtrail as transport
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_cloudtrail.aws_cloudtrail import (
    AwsCloudTrailClient,
    AwsCloudTrailError,
    AwsCloudTrailResumeConfig,
    AwsCloudTrailThrottled,
    error_for_response,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_cloudtrail.settings import (
    AWS_CLOUDTRAIL_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_cloudtrail.source import AwsCloudTrailSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.awscloudtrail import (
    AwsCloudTrailSourceConfig,
)

NOW = dt.datetime(2026, 10, 1, tzinfo=dt.UTC)


def driver(region: str = "eu-west-1", token: str | None = "fake-token") -> SourceDriver:
    return SourceDriver(
        AwsCloudTrailSource(),
        AwsCloudTrailSourceConfig(
            aws_access_key_id="AKIAEXAMPLE",
            aws_secret_access_key="fake-secret",
            aws_session_token=token,
            region=region,
        ),
    )


def request_payloads(requests_log: list[RecordedRequest]) -> list[dict[str, Any]]:
    return [cast(dict[str, Any], request.json()) for request in requests_log]


def response(body: object, status: int = 200, headers: dict[str, str] | None = None) -> requests.Response:
    result = requests.Response()
    result.status_code = status
    result._content = json.dumps(body).encode()
    result.headers.update(headers or {})
    return result


@pytest.fixture
def session() -> Iterator[Mock]:
    with patch.object(transport, "make_tracked_session") as factory, patch.object(transport.time, "sleep"):
        factory.return_value.post.return_value = response({})
        yield factory.return_value


def manager(state: AwsCloudTrailResumeConfig | None = None) -> Mock:
    result = Mock(spec=ResumableSourceManager)
    result.load_state.return_value = state
    return result


def client(
    region: str = "eu-west-1", version: str = "2013-11-01", token: str | None = "fake-token"
) -> AwsCloudTrailClient:
    return AwsCloudTrailClient("AKIAEXAMPLE", "fake-secret", token, region, version)


def payloads(session: Mock) -> list[dict[str, Any]]:
    return [json.loads(call.kwargs["data"]) for call in session.post.call_args_list]


@pytest.mark.parametrize(
    "region,suffix",
    [("eu-west-1", "amazonaws.com"), ("cn-north-1", "amazonaws.com.cn"), ("us-gov-west-1", "amazonaws.com")],
)
@pytest.mark.parametrize("token", [None, "fake-session-token"])
def test_signed_json_request_matches_aws_service_model(region: str, suffix: str, token: str | None) -> None:
    with scripted_network([ScriptedResponse(json={})]) as network:
        assert client(region, token=token).request("LookupEvents", {"MaxResults": 50}) == {}
    assert len(network.requests_log) == 1
    request = network.requests_log[0]
    headers = request.headers
    metadata = Loader().load_service_model("cloudtrail", "service-2")["metadata"]
    assert request.url == f"https://cloudtrail.{region}.{suffix}/"
    assert headers["x-amz-target"] == f"{metadata['targetPrefix']}.LookupEvents"
    assert headers["content-type"] == f"application/x-amz-json-{metadata['jsonVersion']}"
    assert f"/{region}/cloudtrail/aws4_request" in headers["authorization"]
    assert headers["authorization"].startswith("AWS4-HMAC-SHA256 Credential=AKIAEXAMPLE/")
    assert headers.get("x-amz-security-token") == token
    assert "x-amz-date" in headers
    assert request_payloads(network.requests_log) == [{"MaxResults": 50}]

    with scripted_network([ScriptedResponse(status=302, headers={"Location": "https://example.com/"})]) as redirects:
        with pytest.raises(AwsCloudTrailError):
            client(region, token=token).request("LookupEvents", {"MaxResults": 50})
    assert len(redirects.requests_log) == 1


@pytest.mark.parametrize("region", ["https://example.com", "us-east-1.example.com", "us-east-1/", "us-east-1@evil", ""])
def test_invalid_region_never_sends_credentials(region: str) -> None:
    with scripted_network([]) as network:
        with pytest.raises(ValueError, match="valid AWS region"):
            client(region)
    assert network.requests_log == []


def test_unsupported_version_never_sends_request() -> None:
    with scripted_network([]) as network:
        with pytest.raises(ValueError, match="Unsupported AWS CloudTrail API version"):
            client(version="2099-01-01")
    assert network.requests_log == []


@pytest.mark.parametrize(
    "last_value",
    [
        NOW - dt.timedelta(days=1),
        "2026-09-30T00:00:00Z",
        (NOW - dt.timedelta(days=1)).timestamp(),
        dt.datetime(2026, 9, 30),
    ],
)
@time_machine.travel(NOW, tick=False)
def test_incremental_filter_is_identical_on_each_page(last_value: dt.datetime | str | float) -> None:
    result = driver().run(
        "events",
        [ScriptedResponse(json={"Events": [], "NextToken": "next"}), ScriptedResponse(json={"Events": []})],
        incremental_field="event_time",
        db_incremental_field_last_value=last_value,
    )
    assert result.raised is None
    expected = {"MaxResults": 50, "StartTime": (NOW - dt.timedelta(days=1)).timestamp(), "EndTime": NOW.timestamp()}
    assert request_payloads(result.requests) == [expected, {**expected, "NextToken": "next"}]


@time_machine.travel(NOW, tick=False)
def test_incremental_filter_respects_retention_limit() -> None:
    result = driver().run(
        "events",
        [ScriptedResponse(json={"Events": []})],
        incremental_field="event_time",
        db_incremental_field_last_value=NOW - dt.timedelta(days=365),
    )
    assert result.raised is None
    assert result.requests[0].json()["StartTime"] == (NOW - dt.timedelta(days=90)).timestamp()


@pytest.mark.parametrize("endpoint", ["events", "insight_events", "trails", "event_data_stores"])
def test_full_refresh_omits_watermark_through_pipeline(session: Mock, endpoint: str) -> None:
    source = AwsCloudTrailSource()
    inputs = SourceInputs(
        schema_name=endpoint,
        schema_id="schema",
        source_id="source",
        team_id=1,
        should_use_incremental_field=False,
        db_incremental_field_last_value=NOW,
        db_incremental_field_earliest_value=None,
        incremental_field="event_time",
        incremental_field_type=None,
        job_id="job",
        logger=structlog.get_logger(),
        reset_pipeline=False,
    )
    config = AwsCloudTrailSourceConfig(
        aws_access_key_id="AKIAEXAMPLE", aws_secret_access_key="fake-secret", region="eu-west-1"
    )
    resume = manager()
    result = source.source_for_pipeline(config, resume, inputs)
    list(cast(Iterable[Any], result.items()))
    assert "StartTime" not in payloads(session)[0]
    resume.clear_state.assert_not_called()
    assert result.on_complete is not None
    result.on_complete()
    resume.clear_state.assert_called_once()


def test_event_rows_preserve_event_details_and_parse_time() -> None:
    raw = '{"eventSource":"example.amazonaws.com","requestParameters":{}}'
    result = driver().run(
        "events",
        [ScriptedResponse(json={"Events": [{"EventId": "one", "EventTime": NOW.timestamp(), "CloudTrailEvent": raw}]})],
    )
    assert result.raised is None
    assert result.items == [[{"event_id": "one", "event_time": NOW, "cloud_trail_event": raw, "region": "eu-west-1"}]]
    assert result.saved_states[0].finished


def test_store_timestamps_are_normalized() -> None:
    result = driver().run(
        "event_data_stores",
        [
            ScriptedResponse(
                json={
                    "EventDataStores": [
                        {
                            "EventDataStoreArn": "store",
                            "CreatedTimestamp": NOW.timestamp(),
                            "UpdatedTimestamp": NOW.timestamp(),
                        }
                    ]
                }
            )
        ],
    )
    assert result.raised is None
    assert len(result.items) == 1
    assert result.rows[0]["created_timestamp"] == NOW
    assert result.rows[0]["updated_timestamp"] == NOW
    assert result.rows[0]["event_data_store_arn"] == "store"


@time_machine.travel(NOW, tick=False)
def test_resume_preserves_original_time_window() -> None:
    state = AwsCloudTrailResumeConfig(next_token="saved", start_time=100, end_time=200)
    result = driver().run(
        "events",
        [ScriptedResponse(json={"Events": []})],
        resume_state=state,
        incremental_field="event_time",
        db_incremental_field_last_value=NOW,
    )
    assert result.raised is None
    assert request_payloads(result.requests) == [
        {"MaxResults": 50, "StartTime": 100, "EndTime": 200, "NextToken": "saved"}
    ]


def test_completed_checkpoint_does_not_fetch_again(session: Mock) -> None:
    assert (
        list(
            get_rows(
                client(), AWS_CLOUDTRAIL_ENDPOINTS["events"], manager(AwsCloudTrailResumeConfig(finished=True)), None
            )
        )
        == []
    )
    session.post.assert_not_called()
    session.close.assert_called_once()


def test_expired_resume_token_restarts_same_window() -> None:
    state = AwsCloudTrailResumeConfig(next_token="expired", start_time=100, end_time=200)
    result = driver().run(
        "events",
        [
            ScriptedResponse(status=400, json={"__type": "InvalidNextTokenException"}),
            ScriptedResponse(json={"Events": []}),
        ],
        resume_state=state,
    )
    assert result.raised is None
    assert request_payloads(result.requests) == [
        {"MaxResults": 50, "StartTime": 100, "EndTime": 200, "NextToken": "expired"},
        {"MaxResults": 50, "StartTime": 100, "EndTime": 200},
    ]


def test_fresh_invalid_token_is_not_silently_restarted() -> None:
    result = driver().run("events", [ScriptedResponse(status=400, json={"__type": "InvalidNextTokenException"})])
    assert isinstance(result.raised, AwsCloudTrailError)
    assert "InvalidNextTokenException" in str(result.raised)
    assert len(result.requests) == 1


def test_repeated_token_fails_without_infinite_loop() -> None:
    result = driver().run(
        "events",
        [ScriptedResponse(json={"Events": [], "NextToken": "same"})] * 2,
    )
    assert isinstance(result.raised, ValueError)
    assert "repeated page token" in str(result.raised)
    assert len(result.requests) == 2


@pytest.mark.parametrize(
    "code,status,retryable",
    [
        ("ThrottlingException", 400, True),
        ("Throttling", 400, True),
        ("ThrottlingException", 429, False),
        ("InternalError", 500, False),
        ("AccessDeniedException", 400, False),
        ("UnrecognizedClientException", 400, False),
    ],
)
def test_only_body_throttles_get_application_retries(code: str, status: int, retryable: bool) -> None:
    error = error_for_response(response({"__type": f"com.amazonaws.cloudtrail#{code}"}, status))
    assert error.code == code
    assert isinstance(error, AwsCloudTrailThrottled) is retryable


def test_error_header_takes_precedence_and_handles_non_json() -> None:
    result = response({}, 403, {"x-amzn-ErrorType": "AccessDeniedException:http"})
    result._content = b"not JSON"
    assert error_for_response(result).code == "AccessDeniedException"


def test_throttle_retries_then_succeeds() -> None:
    result = driver().run(
        "events",
        [ScriptedResponse(status=400, json={"__type": "ThrottlingException"}), ScriptedResponse(json={"Events": []})],
    )
    assert result.raised is None
    assert request_payloads(result.requests)[0]["MaxResults"] == 50
    assert len(result.requests) == 2


def test_lookup_requests_are_spaced(session: Mock) -> None:
    with (
        patch.object(transport.time, "monotonic", return_value=10.0) as monotonic,
        patch.object(transport.time, "sleep") as sleep,
    ):
        api = client()
        api.request("LookupEvents", {})
        monotonic.return_value = 10.1
        api.request("LookupEvents", {})
    sleep.assert_called_once()
    assert sleep.call_args.args[0] == pytest.approx(0.4)


@pytest.mark.parametrize("code", ["AccessDenied", "AccessDeniedException"])
@pytest.mark.parametrize(
    "schema_name,valid",
    [(None, True), ("events", False), ("insight_events", False), ("trails", False), ("event_data_stores", False)],
)
def test_access_denial_only_accepts_source_creation(
    session: Mock, code: str, schema_name: str | None, valid: bool
) -> None:
    session.post.return_value = response({"__type": code}, 400)
    ok, reason = validate_credentials("key", "secret", None, "eu-west-1", "2013-11-01", schema_name)
    assert ok is valid
    if schema_name is not None:
        assert reason is not None
        assert f"cloudtrail:{AWS_CLOUDTRAIL_ENDPOINTS[schema_name].operation}" in reason
    else:
        assert reason is None
    assert session.post.call_count == 1
    session.close.assert_called_once()


@pytest.mark.parametrize(
    "code,message",
    [
        ("UnrecognizedClientException", "access key"),
        ("InvalidSignatureException", "signature"),
        ("ExpiredTokenException", "expired"),
        ("SubscriptionRequiredException", "subscription"),
        ("OptInRequired", "Enable access"),
        ("OperationNotPermittedException", "permissions"),
    ],
)
def test_credentials_errors_are_actionable_and_terminal(code: str, message: str) -> None:
    with scripted_network([ScriptedResponse(status=400, json={"__type": code})]) as network:
        valid, reason = validate_credentials("key", "secret", None, "eu-west-1", "2013-11-01")
    assert not valid
    assert reason is not None and message in reason
    assert len(network.requests_log) == 1
    error = error_for_response(response({"__type": code}, 400))
    mapped = [
        value for pattern, value in AwsCloudTrailSource().get_non_retryable_errors().items() if pattern in str(error)
    ]
    assert mapped and all(mapped)


@pytest.mark.parametrize(
    "schema_name,target,params",
    [
        (None, "DescribeTrails", {"includeShadowTrails": True}),
        ("events", "LookupEvents", {"MaxResults": 1}),
        ("insight_events", "LookupEvents", {"MaxResults": 1, "EventCategory": "insight"}),
        ("event_data_stores", "ListEventDataStores", {"MaxResults": 1}),
    ],
)
def test_validation_uses_one_cheap_probe(schema_name: str | None, target: str, params: dict[str, Any]) -> None:
    with scripted_network([ScriptedResponse(json={})]) as network:
        assert validate_credentials("key", "secret", None, "eu-west-1", "2013-11-01", schema_name) == (True, None)
    assert len(network.requests_log) == 1
    assert network.requests_log[0].headers["x-amz-target"].endswith(f".{target}")
    assert request_payloads(network.requests_log) == [params]


@pytest.mark.parametrize(
    "key,secret,region,schema,message",
    [
        ("", "secret", "eu-west-1", None, "access key"),
        ("key", "", "eu-west-1", None, "access key"),
        ("key", "secret", "bad", None, "region"),
        ("key", "secret", "eu-west-1", "missing", "Unknown"),
    ],
)
def test_invalid_setup_fails_before_network(
    key: str, secret: str, region: str, schema: str | None, message: str
) -> None:
    with scripted_network([]) as network:
        valid, reason = validate_credentials(key, secret, None, region, "2013-11-01", schema)
    assert not valid
    assert reason is not None and message in reason
    assert network.requests_log == []


def test_connection_error_has_useful_message(session: Mock) -> None:
    session.post.side_effect = requests.ConnectionError("offline")
    valid, reason = validate_credentials("key", "secret", None, "eu-west-1", "2013-11-01")
    assert not valid
    assert reason is not None and "region" in reason
    session.close.assert_called_once()


def test_unknown_pipeline_table_fails_before_network() -> None:
    result = driver().run("missing", [])
    assert isinstance(result.raised, ValueError)
    assert "Unknown AWS CloudTrail table" in str(result.raised)
    assert result.requests == []
