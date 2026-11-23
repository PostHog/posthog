from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest

import requests

from products.warehouse_sources.sources.aws_end_user_messaging._config import AwsEndUserMessagingSourceConfig
from products.warehouse_sources.sources.aws_end_user_messaging.aws_end_user_messaging import (
    AwsEndUserMessagingError,
    AwsEndUserMessagingResumeConfig,
    validate_credentials,
)
from products.warehouse_sources.sources.aws_end_user_messaging.source import AwsEndUserMessagingSource
from products.warehouse_sources.sources.sdk.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    always,
    error_message_matches,
    scripted_network,
)

LIST_A = "arn:aws:sms-voice:us-east-1:123456789012:opt-out-list/list-a"
LIST_B = "arn:aws:sms-voice:us-east-1:123456789012:opt-out-list/list-b"
NUMBER = "arn:aws:sms-voice:us-east-1:123456789012:phone-number/phone-1"
POOL = "arn:aws:sms-voice:us-east-1:123456789012:pool/pool-1"
REGISTRATION = "arn:aws:sms-voice:us-east-1:123456789012:registration/registration-1"

ACCESS_DENIED = ScriptedResponse(
    status=400,
    json={
        "__type": "com.amazonaws.pinpointsmsvoicev2#AccessDeniedException",
        "Message": "User: arn:aws:iam::123456789012:user/example is not authorized to perform: "
        "sms-voice:DescribePhoneNumbers",
    },
)
BAD_TOKEN = ScriptedResponse(
    status=400,
    json={"__type": "UnrecognizedClientException", "message": "The security token included in the request is invalid."},
)
BAD_SIGNATURE = ScriptedResponse(
    status=403,
    headers={
        "x-amzn-ErrorType": "InvalidSignatureException:http://internal.amazon.com/coral/com.amazon.coral.service/"
    },
    json={"message": "The request signature we calculated does not match the signature you provided."},
)
EXPIRED = ScriptedResponse(
    status=400,
    json={"__type": "ExpiredTokenException", "message": "The security token included in the request is expired"},
)
THROTTLED = ScriptedResponse(
    status=400,
    json={"__type": "com.amazonaws.pinpointsmsvoicev2#ThrottlingException", "Message": "Rate exceeded"},
)
NOT_FOUND = ScriptedResponse(
    status=400,
    json={
        "__type": "com.amazonaws.pinpointsmsvoicev2#ResourceNotFoundException",
        "Message": "Resource not found",
        "ResourceType": "opt-out-list",
    },
)


def _config(region: str = "us-east-1", session_token: str | None = None) -> AwsEndUserMessagingSourceConfig:
    return AwsEndUserMessagingSourceConfig(
        aws_access_key_id="AKIAEXAMPLE",
        aws_secret_access_key="example-secret",
        aws_region=region,
        aws_session_token=session_token,
    )


def _driver(config: AwsEndUserMessagingSourceConfig | None = None) -> SourceDriver:
    return SourceDriver(AwsEndUserMessagingSource(), config or _config())


def _operation(request: RecordedRequest) -> str:
    return request.headers["x-amz-target"].removeprefix("PinpointSMSVoiceV2.")


def by_operation(table: Mapping[str, Sequence[ScriptedResponse]]) -> Callable[[RecordedRequest], ScriptedResponse]:
    # Every operation posts to the same path, so the X-Amz-Target header picks the queue.
    queues = {operation: list(responses) for operation, responses in table.items()}

    def answer(request: RecordedRequest) -> ScriptedResponse:
        queue = queues.get(_operation(request))
        if not queue:
            raise AssertionError(f"No answer left for {_operation(request)}")
        return queue.pop(0)

    return answer


def _state(state: Any) -> AwsEndUserMessagingResumeConfig:
    # A stored cursor comes back with its tuple as a list.
    return replace(state, pending=tuple(state.pending))


def _calls(requests_log: Sequence[RecordedRequest]) -> list[tuple[str, dict[str, Any]]]:
    return [(_operation(request), request.json()) for request in requests_log]


@pytest.mark.parametrize(
    ("region", "host"),
    [
        ("us-east-1", "sms-voice.us-east-1.amazonaws.com"),
        ("us-gov-west-1", "sms-voice.us-gov-west-1.amazonaws.com"),
        ("cn-north-1", "sms-voice.cn-north-1.amazonaws.com.cn"),
    ],
)
@pytest.mark.parametrize("session_token", [None, "example-session-token"])
def test_walks_pages_with_signed_requests(region: str, host: str, session_token: str | None) -> None:
    script = [
        ScriptedResponse(
            json={
                "PhoneNumbers": [
                    {
                        "PhoneNumberArn": NUMBER,
                        "PhoneNumber": "+12065550100",
                        "NumberCapabilities": ["SMS", "VOICE"],
                        "TwoWayEnabled": False,
                        "CreatedTimestamp": 1700000000.5,
                    }
                ],
                "NextToken": "page-2",
            }
        ),
        ScriptedResponse(json={"PhoneNumbers": [{"PhoneNumberArn": f"{NUMBER}-2", "CreatedTimestamp": None}]}),
    ]

    result = _driver(_config(region, session_token)).run("phone_numbers", script)

    assert result.raised is None
    assert _calls(result.requests) == [
        ("DescribePhoneNumbers", {"MaxResults": 100}),
        ("DescribePhoneNumbers", {"MaxResults": 100, "NextToken": "page-2"}),
    ]
    request = result.requests[0]
    assert request.origin == f"https://{host}"
    assert request.headers["content-type"] == "application/x-amz-json-1.0"
    assert "Credential=AKIAEXAMPLE/" in request.headers["authorization"]
    assert f"/{region}/sms-voice/aws4_request" in request.headers["authorization"]
    assert request.headers.get("x-amz-security-token") == session_token
    assert result.rows == [
        {
            "phone_number_arn": NUMBER,
            "phone_number": "+12065550100",
            "number_capabilities": ["SMS", "VOICE"],
            "two_way_enabled": False,
            "created_timestamp": datetime(2023, 11, 14, 22, 13, 20, 500000, tzinfo=UTC),
        },
        {"phone_number_arn": f"{NUMBER}-2", "created_timestamp": None},
    ]
    assert _state(result.committed_states[0]) == AwsEndUserMessagingResumeConfig(next_token="page-2")
    assert result.completed_state is None


def test_opted_out_numbers_fan_out_over_every_opt_out_list() -> None:
    script = by_operation(
        {
            "DescribeOptOutLists": [
                ScriptedResponse(json={"OptOutLists": [{"OptOutListArn": LIST_A}], "NextToken": "lists-2"}),
                ScriptedResponse(json={"OptOutLists": [{"OptOutListArn": LIST_B}]}),
            ],
            "DescribeOptedOutNumbers": [
                ScriptedResponse(
                    json={
                        "OptOutListArn": LIST_A,
                        "OptOutListName": "list-a",
                        "OptedOutNumbers": [
                            {"OptedOutNumber": "+12065550101", "OptedOutTimestamp": 1700000000, "EndUserOptedOut": True}
                        ],
                        "NextToken": "numbers-2",
                    }
                ),
                ScriptedResponse(
                    json={
                        "OptOutListArn": LIST_A,
                        "OptOutListName": "list-a",
                        "OptedOutNumbers": [
                            {
                                "OptedOutNumber": "+12065550102",
                                "OptedOutTimestamp": 1700000060,
                                "EndUserOptedOut": False,
                            }
                        ],
                    }
                ),
                # The list was deleted after the parent listing.
                NOT_FOUND,
            ],
        }
    )

    result = _driver().run("opted_out_numbers", script)

    assert result.raised is None
    assert _calls(result.requests) == [
        ("DescribeOptOutLists", {"MaxResults": 100}),
        ("DescribeOptedOutNumbers", {"MaxResults": 100, "OptOutListName": LIST_A}),
        ("DescribeOptedOutNumbers", {"MaxResults": 100, "OptOutListName": LIST_A, "NextToken": "numbers-2"}),
        ("DescribeOptOutLists", {"MaxResults": 100, "NextToken": "lists-2"}),
        ("DescribeOptedOutNumbers", {"MaxResults": 100, "OptOutListName": LIST_B}),
    ]
    assert result.rows == [
        {
            "opt_out_list_arn": LIST_A,
            "opt_out_list_name": "list-a",
            "opted_out_number": "+12065550101",
            "opted_out_timestamp": datetime(2023, 11, 14, 22, 13, 20, tzinfo=UTC),
            "end_user_opted_out": True,
        },
        {
            "opt_out_list_arn": LIST_A,
            "opt_out_list_name": "list-a",
            "opted_out_number": "+12065550102",
            "opted_out_timestamp": datetime(2023, 11, 14, 22, 14, 20, tzinfo=UTC),
            "end_user_opted_out": False,
        },
    ]
    # The cursor names the pending parents and the page token inside the first one.
    assert [_state(state) for state in result.committed_states[:2]] == [
        AwsEndUserMessagingResumeConfig(next_token="lists-2", pending=(LIST_A,)),
        AwsEndUserMessagingResumeConfig(next_token="lists-2", pending=(LIST_A,), child_token="numbers-2"),
    ]
    assert result.saved_states[-1].complete is True


def test_keywords_fan_out_over_phone_numbers_then_pools() -> None:
    script = by_operation(
        {
            "DescribePhoneNumbers": [ScriptedResponse(json={"PhoneNumbers": [{"PhoneNumberArn": NUMBER}]})],
            "DescribePools": [
                ScriptedResponse(json={"Pools": [], "NextToken": "pools-2"}),
                ScriptedResponse(json={"Pools": [{"PoolArn": POOL}]}),
            ],
            "DescribeKeywords": [
                ScriptedResponse(
                    json={"OriginationIdentityArn": NUMBER, "OriginationIdentity": "phone-1", "Keywords": []}
                ),
                # Without the ARN in the response, the row keeps the identity that the request sent.
                ScriptedResponse(
                    json={"Keywords": [{"Keyword": "STOP", "KeywordMessage": "Bye", "KeywordAction": "OPT_OUT"}]}
                ),
            ],
        }
    )

    result = _driver().run("keywords", script)

    assert result.raised is None
    assert _calls(result.requests) == [
        ("DescribePhoneNumbers", {"MaxResults": 100}),
        ("DescribeKeywords", {"MaxResults": 100, "OriginationIdentity": NUMBER}),
        ("DescribePools", {"MaxResults": 100}),
        ("DescribePools", {"MaxResults": 100, "NextToken": "pools-2"}),
        ("DescribeKeywords", {"MaxResults": 100, "OriginationIdentity": POOL}),
    ]
    assert result.rows == [
        {
            "origination_identity_arn": POOL,
            "origination_identity": None,
            "keyword": "STOP",
            "keyword_message": "Bye",
            "keyword_action": "OPT_OUT",
        }
    ]


@pytest.mark.parametrize(
    ("schema", "parent_response", "child_response", "expected_child_request", "expected_row"),
    [
        (
            "registration_associations",
            {"Registrations": [{"RegistrationArn": REGISTRATION, "RegistrationId": "registration-1"}]},
            {
                "RegistrationArn": REGISTRATION,
                "RegistrationId": "registration-1",
                "RegistrationType": "US_TEN_DLC_CAMPAIGN_REGISTRATION",
                "RegistrationAssociations": [
                    {"ResourceArn": NUMBER, "ResourceId": "phone-1", "ResourceType": "phone-number"}
                ],
            },
            ("ListRegistrationAssociations", {"MaxResults": 100, "RegistrationId": "registration-1"}),
            {
                "registration_arn": REGISTRATION,
                "registration_id": "registration-1",
                "registration_type": "US_TEN_DLC_CAMPAIGN_REGISTRATION",
                "resource_arn": NUMBER,
                "resource_id": "phone-1",
                "resource_type": "phone-number",
            },
        ),
        (
            "registration_versions",
            {"Registrations": [{"RegistrationArn": REGISTRATION, "RegistrationId": "registration-1"}]},
            {
                "RegistrationArn": REGISTRATION,
                "RegistrationId": "registration-1",
                "RegistrationVersions": [
                    {
                        "VersionNumber": 2,
                        "RegistrationVersionStatus": "DENIED",
                        "RegistrationVersionStatusHistory": {"DraftTimestamp": 1700000000},
                        "DeniedReasons": [{"Reason": "x", "ShortDescription": "y"}],
                    }
                ],
            },
            ("DescribeRegistrationVersions", {"MaxResults": 100, "RegistrationId": "registration-1"}),
            {
                "registration_arn": REGISTRATION,
                "registration_id": "registration-1",
                "version_number": 2,
                "registration_version_status": "DENIED",
                "registration_version_status_history": {"DraftTimestamp": 1700000000},
                "denied_reasons": [{"Reason": "x", "ShortDescription": "y"}],
            },
        ),
        (
            # The version number is only at the top level of the response.
            "registration_field_values",
            {"Registrations": [{"RegistrationArn": REGISTRATION, "RegistrationId": "registration-1"}]},
            {
                "RegistrationArn": REGISTRATION,
                "RegistrationId": "registration-1",
                "VersionNumber": 3,
                "RegistrationFieldValues": [{"FieldPath": "companyInfo.companyName", "TextValue": "Example"}],
            },
            ("DescribeRegistrationFieldValues", {"MaxResults": 100, "RegistrationId": "registration-1"}),
            {
                "registration_arn": REGISTRATION,
                "registration_id": "registration-1",
                "version_number": 3,
                "field_path": "companyInfo.companyName",
                "text_value": "Example",
            },
        ),
        (
            "pool_origination_identities",
            {"Pools": [{"PoolArn": POOL, "PoolId": "pool-1"}]},
            {
                "PoolArn": POOL,
                "PoolId": "pool-1",
                "OriginationIdentities": [
                    {
                        "OriginationIdentityArn": NUMBER,
                        "OriginationIdentity": "phone-1",
                        "IsoCountryCode": "US",
                        "NumberCapabilities": ["SMS"],
                    }
                ],
            },
            ("ListPoolOriginationIdentities", {"MaxResults": 100, "PoolId": POOL}),
            {
                "pool_arn": POOL,
                "pool_id": "pool-1",
                "origination_identity_arn": NUMBER,
                "origination_identity": "phone-1",
                "iso_country_code": "US",
                "number_capabilities": ["SMS"],
            },
        ),
    ],
)
def test_child_tables_send_the_parent_identity_and_keep_parent_columns(
    schema: str,
    parent_response: dict[str, Any],
    child_response: dict[str, Any],
    expected_child_request: tuple[str, dict[str, Any]],
    expected_row: dict[str, Any],
) -> None:
    result = _driver().run(schema, [ScriptedResponse(json=parent_response), ScriptedResponse(json=child_response)])

    assert result.raised is None
    assert _calls(result.requests)[1] == expected_child_request
    assert result.rows == [expected_row]


@pytest.mark.parametrize(
    ("schema", "state", "script", "expected_calls"),
    [
        (
            "pools",
            AwsEndUserMessagingResumeConfig(next_token="pools-3"),
            [ScriptedResponse(json={"Pools": [{"PoolArn": POOL}]})],
            [("DescribePools", {"MaxResults": 100, "NextToken": "pools-3"})],
        ),
        (
            "opted_out_numbers",
            AwsEndUserMessagingResumeConfig(pending=(LIST_B,), child_token="numbers-4"),
            [ScriptedResponse(json={"OptOutListArn": LIST_B, "OptedOutNumbers": [{"OptedOutNumber": "+1"}]})],
            [("DescribeOptedOutNumbers", {"MaxResults": 100, "OptOutListName": LIST_B, "NextToken": "numbers-4"})],
        ),
        (
            # The phone numbers are done, so the sync goes on with the first page of pools.
            "keywords",
            AwsEndUserMessagingResumeConfig(parent_index=1),
            [ScriptedResponse(json={"Pools": []})],
            [("DescribePools", {"MaxResults": 100})],
        ),
        ("pools", AwsEndUserMessagingResumeConfig(complete=True), [], []),
    ],
)
def test_resumes_from_saved_state(
    schema: str,
    state: AwsEndUserMessagingResumeConfig,
    script: list[ScriptedResponse],
    expected_calls: list[tuple[str, dict[str, Any]]],
) -> None:
    result = _driver().run(schema, script, resume_state=state)

    assert result.raised is None
    assert _calls(result.requests) == expected_calls
    assert result.saved_states == [] or result.saved_states[-1].complete is True


def test_retries_a_throttled_request() -> None:
    result = _driver().run("spend_limits", [THROTTLED, ScriptedResponse(json={"SpendLimits": [{"Name": "X"}]})])

    assert result.raised is None
    assert result.rows == [{"name": "X"}]
    assert len(result.requests) == 2


@pytest.mark.parametrize(
    ("answer", "code"),
    [
        (ACCESS_DENIED, "AccessDeniedException"),
        (BAD_TOKEN, "UnrecognizedClientException"),
        (BAD_SIGNATURE, "InvalidSignatureException"),
        (EXPIRED, "ExpiredTokenException"),
        (ScriptedResponse(status=403), "HTTP 403"),
    ],
)
def test_credential_failures_stop_the_sync(answer: ScriptedResponse, code: str) -> None:
    result = _driver().run("account_limits", always(answer))

    assert isinstance(result.raised, AwsEndUserMessagingError)
    assert result.raised.code == code
    assert error_message_matches(str(result.raised), AwsEndUserMessagingSource().get_non_retryable_errors())


@pytest.mark.parametrize(
    ("answer", "code"),
    [
        (THROTTLED, "ThrottlingException"),
        (
            ScriptedResponse(status=500, json={"__type": "InternalServerException", "Message": "x"}),
            "InternalServerException",
        ),
    ],
)
def test_transient_failures_stay_retryable(answer: ScriptedResponse, code: str) -> None:
    result = _driver().run("account_attributes", always(answer))

    assert isinstance(result.raised, AwsEndUserMessagingError)
    assert result.raised.code == code
    assert not error_message_matches(str(result.raised), AwsEndUserMessagingSource().get_non_retryable_errors())


def test_repeated_page_token_stops_the_sync() -> None:
    script = [
        ScriptedResponse(json={"Registrations": [], "NextToken": "same"}),
        ScriptedResponse(json={"Registrations": [], "NextToken": "same"}),
    ]

    result = _driver().run("registrations", script)

    assert isinstance(result.raised, AwsEndUserMessagingError)
    assert result.raised.code == "RepeatedNextToken"


@pytest.mark.parametrize(
    ("config", "schema", "script", "expected", "expected_operations"),
    [
        (
            _config(),
            None,
            [ScriptedResponse(json={"AccountAttributes": []})],
            (True, None),
            ["DescribeAccountAttributes"],
        ),
        # AWS checks the signature before the permissions, so a denial at create proves the credentials.
        (_config(), None, [ACCESS_DENIED], (True, None), ["DescribeAccountAttributes"]),
        (
            _config(),
            "pools",
            [ACCESS_DENIED],
            (False, "AWS denied access. Grant sms-voice:DescribePools to the IAM user or role to sync this table."),
            ["DescribePools"],
        ),
        (
            _config(),
            None,
            [BAD_TOKEN],
            (
                False,
                "AWS rejected the credentials. Check the access key ID, the secret access key, and the session token.",
            ),
            ["DescribeAccountAttributes"],
        ),
        (
            _config(),
            None,
            [EXPIRED],
            (False, "The AWS session token expired. Connect again with current credentials."),
            ["DescribeAccountAttributes"],
        ),
        (
            _config(),
            "opted_out_numbers",
            [ScriptedResponse(json={"OptOutLists": [{"OptOutListArn": LIST_A}]}), ACCESS_DENIED],
            (
                False,
                "AWS denied access. Grant sms-voice:DescribeOptedOutNumbers to the IAM user or role to sync this table.",
            ),
            ["DescribeOptOutLists", "DescribeOptedOutNumbers"],
        ),
        (
            _config(),
            "keywords",
            [ScriptedResponse(json={"PhoneNumbers": []}), ScriptedResponse(json={"Pools": []})],
            (True, None),
            ["DescribePhoneNumbers", "DescribePools"],
        ),
        (
            _config(),
            "opted_out_numbers",
            [ScriptedResponse(json={"OptOutLists": [{"OptOutListArn": LIST_A}]}), NOT_FOUND],
            (True, None),
            ["DescribeOptOutLists", "DescribeOptedOutNumbers"],
        ),
        (_config(region="not a region"), None, [], (False, "Enter an AWS region, such as us-east-1."), []),
        (_config(), "messages", [], (False, "Unknown AWS End User Messaging table: messages"), []),
    ],
)
def test_validate_credentials(
    config: AwsEndUserMessagingSourceConfig,
    schema: str | None,
    script: list[ScriptedResponse],
    expected: tuple[bool, str | None],
    expected_operations: list[str],
) -> None:
    with scripted_network(script) as network:
        assert validate_credentials(config, schema) == expected

    assert [_operation(request) for request in network.requests_log] == expected_operations


def test_validate_credentials_reports_an_unreachable_region() -> None:
    with scripted_network(always(requests.ConnectionError("Name or service not known"))):
        valid, message = validate_credentials(_config(region="ap-southeast-7"))

    assert valid is False
    assert message is not None and "Check that the region is correct" in message
