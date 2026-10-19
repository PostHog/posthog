import json
import datetime as dt
from typing import Any, Optional

import pytest

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.aws_organizations.aws_organizations import (
    AwsOrganizationsClient,
    AwsOrganizationsError,
    AwsOrganizationsResumeConfig,
    AwsOrganizationsRetryableError,
    error_for_response,
    normalize_row,
    probe_endpoint_permissions,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_organizations.settings import (
    AWS_ORGANIZATIONS_ENDPOINTS,
    MAX_RESULTS,
    ORGANIZATIONS_ENDPOINT_URL,
    POLICY_FILTERS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_organizations.source import (
    AwsOrganizationsSource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.awsorganizations import (
    AwsOrganizationsSourceConfig,
)

ACCOUNTS = AWS_ORGANIZATIONS_ENDPOINTS["accounts"]

JAN_2025 = 1735689600.0  # 2025-01-01T00:00:00Z


def make_response(
    status_code: int, payload: Optional[dict[str, Any]] = None, headers: Optional[dict[str, str]] = None
) -> requests.Response:
    response = requests.Response()
    response.status_code = status_code
    response.headers.update(headers or {})
    response._content = json.dumps(payload if payload is not None else {}).encode()
    return response


def page(key: str, items: list[dict[str, Any]], next_token: Optional[str] = None) -> dict[str, Any]:
    body: dict[str, Any] = {key: items}
    if next_token is not None:
        body["NextToken"] = next_token
    return body


def driver() -> SourceDriver:
    return SourceDriver(
        AwsOrganizationsSource(),
        AwsOrganizationsSourceConfig(aws_access_key_id="AKIAEXAMPLE", aws_secret_access_key="secret"),
    )


def request_operation(request: RecordedRequest) -> str:
    return request.headers["x-amz-target"].rsplit(".", 1)[-1]


def aws_error(code: str, message: str, status: int = 400) -> ScriptedResponse:
    return ScriptedResponse(status=status, json={"__type": f"com.amazonaws.organizations#{code}", "message": message})


class TestNormalizeRow:
    def test_account_row_parses_the_epoch_timestamp_and_drops_the_retiring_status_member(self) -> None:
        row = normalize_row(
            ACCOUNTS,
            {
                "Id": "111111111111",
                "Arn": "arn:aws:organizations::111111111111:account/o-example/111111111111",
                "Email": "owner@example.com",
                "Name": "Production Account",
                "JoinedMethod": "INVITED",
                "JoinedTimestamp": JAN_2025,
                "State": "ACTIVE",
                "Status": "ACTIVE",
                "Paths": ["o-example/r-exam/111111111111/"],
            },
        )

        assert row == {
            "id": "111111111111",
            "arn": "arn:aws:organizations::111111111111:account/o-example/111111111111",
            "email": "owner@example.com",
            "name": "Production Account",
            "joined_method": "INVITED",
            "joined_timestamp": dt.datetime(2025, 1, 1, tzinfo=dt.UTC),
            "state": "ACTIVE",
            "paths": ["o-example/r-exam/111111111111/"],
        }


class TestSignedRequest:
    def test_request_is_signed_for_the_global_endpoint_and_names_the_operation(self) -> None:
        with scripted_network([ScriptedResponse(json={"Organization": {"Id": "o-example"}})]) as network:
            client = AwsOrganizationsClient("AKIAEXAMPLE", "secret", None)
            body = client.send("DescribeOrganization", {})

        assert body == {"Organization": {"Id": "o-example"}}
        request = network.requests_log[0]
        assert request.url == ORGANIZATIONS_ENDPOINT_URL
        assert request.method == "POST"
        assert request.json() == {}
        assert request.headers["x-amz-target"] == "AWSOrganizationsV20161128.DescribeOrganization"
        assert request.headers["content-type"] == "application/x-amz-json-1.1"
        # Organizations is global: a signature scoped anywhere but us-east-1/organizations is
        # rejected as SignatureDoesNotMatch, which reads to the user as a bad key.
        assert "/us-east-1/organizations/aws4_request" in request.headers["authorization"]

    @pytest.mark.parametrize(
        "status_code,code,retryable",
        [
            (400, "AccessDeniedException", False),
            (400, "AWSOrganizationsNotInUseException", False),
            (400, "UnrecognizedClientException", False),
            (400, "TooManyRequestsException", True),
            (400, "ConcurrentModificationException", True),
            (500, "ServiceException", True),
        ],
    )
    def test_error_responses_carry_the_code_and_only_transient_ones_are_retryable(
        self, status_code: int, code: str, retryable: bool
    ) -> None:
        response = make_response(
            status_code, {"__type": f"com.amazonaws.organizations#{code}", "message": "denied for organizations:Foo"}
        )

        error = error_for_response(response)

        assert error.code == code
        assert isinstance(error, AwsOrganizationsRetryableError) is retryable
        assert str(error) == f"AWS Organizations request failed: {code} - denied for organizations:Foo"

    def test_error_type_header_wins_over_the_body(self) -> None:
        response = make_response(
            400,
            {"message": "nope"},
            headers={"x-amzn-ErrorType": "AccessDeniedException:http://internal.amazon.com/coral/"},
        )

        assert error_for_response(response).code == "AccessDeniedException"


class TestPagination:
    @pytest.mark.parametrize(
        "endpoint,operation,expects_max_results",
        [
            ("accounts", "ListAccounts", True),
            ("roots", "ListRoots", True),
            ("resource_tags", "ListTagsForResource", False),
        ],
    )
    def test_max_results_is_sent_only_where_the_operation_accepts_it(
        self, endpoint: str, operation: str, expects_max_results: bool
    ) -> None:
        def responder(request: RecordedRequest) -> ScriptedResponse:
            match request_operation(request):
                case "ListAccounts":
                    return ScriptedResponse(json=page("Accounts", [{"Id": "111111111111"}]))
                case "ListRoots":
                    return ScriptedResponse(json=page("Roots", [{"Id": "r-exam"}]))
                case "ListOrganizationalUnitsForParent":
                    return ScriptedResponse(json=page("OrganizationalUnits", []))
                case "ListPolicies":
                    return ScriptedResponse(json=page("Policies", []))
                case _:
                    return ScriptedResponse(json=page("Tags", [{"Key": "team", "Value": "growth"}]))

        result = driver().run(endpoint, responder)

        assert result.raised is None
        payloads = [request.json() for request in result.requests if request_operation(request) == operation]
        assert payloads
        for payload in payloads:
            assert ("MaxResults" in payload) is expects_max_results
            if expects_max_results:
                assert payload["MaxResults"] == MAX_RESULTS

    def test_single_object_endpoint_issues_one_call_and_one_row(self) -> None:
        result = driver().run(
            "organization", [ScriptedResponse(json={"Organization": {"Id": "o-example", "FeatureSet": "ALL"}})]
        )

        assert result.raised is None
        assert [(request_operation(request), request.json()) for request in result.requests] == [
            ("DescribeOrganization", {})
        ]
        assert result.rows == [{"id": "o-example", "feature_set": "ALL"}]


class TestPolicies:
    @pytest.mark.parametrize(
        "code,message",
        [
            ("UnsupportedAPIEndpointException", "This action isn't available in the current AWS Region."),
            ("InvalidInputException", "INVALID_ENUM_POLICY_TYPE: You specified an invalid policy type string."),
        ],
    )
    def test_a_policy_type_this_organization_does_not_offer_is_skipped(self, code: str, message: str) -> None:
        def responder(request: RecordedRequest) -> ScriptedResponse:
            policy_filter = request.json()["Filter"]
            if policy_filter == "SERVICE_CONTROL_POLICY":
                return aws_error(code, message)
            return ScriptedResponse(json=page("Policies", [{"Id": "p-example", "Type": policy_filter}]))

        result = driver().run("policies", responder)

        assert result.raised is None
        assert len(result.rows) == len(POLICY_FILTERS) - 1

    def test_a_denied_policy_type_fails_the_sync(self) -> None:
        result = driver().run(
            "policies", always(aws_error("AccessDeniedException", "not authorized for organizations:ListPolicies"))
        )

        assert isinstance(result.raised, AwsOrganizationsError)
        assert "AccessDeniedException" in str(result.raised)


class TestOrganizationalUnits:
    def test_a_unit_returned_twice_does_not_walk_the_same_subtree_forever(self) -> None:
        def responder(request: RecordedRequest) -> ScriptedResponse:
            if request_operation(request) == "ListRoots":
                return ScriptedResponse(json=page("Roots", [{"Id": "r-exam"}]))
            if request.json()["ParentId"] == "r-exam":
                return ScriptedResponse(
                    json=page("OrganizationalUnits", [{"Id": "ou-exam-aaaaaaaa"}, {"Id": "ou-exam-aaaaaaaa"}])
                )
            return ScriptedResponse(json=page("OrganizationalUnits", []))

        result = driver().run("organizational_units", responder)

        assert result.raised is None
        assert len(result.rows) == 2
        assert [
            request.json()["ParentId"]
            for request in result.requests
            if request_operation(request).startswith("ListOrg")
        ] == [
            "r-exam",
            "ou-exam-aaaaaaaa",
        ]


class TestResourceTags:
    def test_a_resource_deleted_mid_sync_is_skipped(self) -> None:
        def responder(request: RecordedRequest) -> ScriptedResponse:
            payload = request.json()
            match request_operation(request):
                case "ListAccounts":
                    return ScriptedResponse(json=page("Accounts", [{"Id": "111111111111"}]))
                case "ListRoots":
                    return ScriptedResponse(json=page("Roots", [{"Id": "r-exam"}]))
                case "ListOrganizationalUnitsForParent":
                    units = [{"Id": "ou-exam-aaaaaaaa"}] if payload["ParentId"] == "r-exam" else []
                    return ScriptedResponse(json=page("OrganizationalUnits", units))
                case "ListPolicies":
                    policies = [{"Id": "p-example"}] if payload["Filter"] == "SERVICE_CONTROL_POLICY" else []
                    return ScriptedResponse(json=page("Policies", policies))
                case _:
                    if payload["ResourceId"] == "r-exam":
                        return aws_error("TargetNotFoundException", "We can't find that target.")
                    return ScriptedResponse(json=page("Tags", [{"Key": "team", "Value": payload["ResourceId"]}]))

        result = driver().run("resource_tags", responder)

        assert result.raised is None
        assert [row["resource_id"] for row in result.rows] == [
            "111111111111",
            "ou-exam-aaaaaaaa",
            "p-example",
        ]


class TestFanOut:
    @pytest.mark.parametrize(
        "endpoint,parent_operation,parent_key,child_operation,child_param,child_key,child_item,missing_code,parent_column",
        [
            (
                "account_parents",
                "ListAccounts",
                "Accounts",
                "ListParents",
                "ChildId",
                "Parents",
                {"Id": "ou-exam-aaaaaaaa", "Type": "ORGANIZATIONAL_UNIT"},
                "ChildNotFoundException",
                "account_id",
            ),
            (
                "policy_targets",
                "ListPolicies",
                "Policies",
                "ListTargetsForPolicy",
                "PolicyId",
                "Targets",
                {"TargetId": "111111111111", "Type": "ACCOUNT", "Name": "prod"},
                "PolicyNotFoundException",
                "policy_id",
            ),
            (
                "delegated_services",
                "ListDelegatedAdministrators",
                "DelegatedAdministrators",
                "ListDelegatedServicesForAccount",
                "AccountId",
                "DelegatedServices",
                {"ServicePrincipal": "guardduty.amazonaws.com", "DelegationEnabledDate": JAN_2025},
                "AccountNotRegisteredException",
                "account_id",
            ),
        ],
    )
    def test_every_child_page_is_kept_with_its_parent_and_a_parent_removed_mid_sync_is_skipped(
        self,
        endpoint: str,
        parent_operation: str,
        parent_key: str,
        child_operation: str,
        child_param: str,
        child_key: str,
        child_item: dict[str, Any],
        missing_code: str,
        parent_column: str,
    ) -> None:
        def responder(request: RecordedRequest) -> ScriptedResponse:
            payload = request.json()
            operation = request_operation(request)
            if operation == parent_operation:
                if endpoint == "policy_targets" and payload["Filter"] != "SERVICE_CONTROL_POLICY":
                    return ScriptedResponse(json=page(parent_key, []))
                if payload.get("NextToken") is None:
                    return ScriptedResponse(json=page(parent_key, [{"Id": "parent-a"}], next_token="parents-2"))
                return ScriptedResponse(json=page(parent_key, [{"Id": "parent-gone"}, {"Id": "parent-b"}]))
            assert operation == child_operation
            if payload[child_param] == "parent-gone":
                return aws_error(missing_code, "The entity no longer exists.")
            if payload[child_param] == "parent-a" and payload.get("NextToken") is None:
                return ScriptedResponse(json=page(child_key, [child_item], next_token="children-2"))
            return ScriptedResponse(json=page(child_key, [child_item]))

        result = driver().run(endpoint, responder)

        assert result.raised is None
        assert [[row[parent_column] for row in item] for item in result.items] == [
            ["parent-a", "parent-a"],
            ["parent-b"],
        ]
        child_payloads = [
            request.json() for request in result.requests if request_operation(request) == child_operation
        ]
        assert all(payload["MaxResults"] == MAX_RESULTS for payload in child_payloads)

    def test_account_parents_rows_name_the_parent_and_resume_the_account_walk(self) -> None:
        def responder(request: RecordedRequest) -> ScriptedResponse:
            if request_operation(request) == "ListAccounts":
                return ScriptedResponse(json=page("Accounts", [{"Id": "222222222222"}]))
            return ScriptedResponse(json=page("Parents", [{"Id": "r-exam", "Type": "ROOT"}]))

        result = driver().run(
            "account_parents", responder, resume_state=AwsOrganizationsResumeConfig(next_token="accounts-2")
        )

        assert result.raised is None
        assert result.requests[0].json() == {"MaxResults": MAX_RESULTS, "NextToken": "accounts-2"}
        assert result.rows == [{"account_id": "222222222222", "parent_id": "r-exam", "parent_type": "ROOT"}]

    @pytest.mark.parametrize("endpoint", ["account_parents", "delegated_services"])
    def test_a_walk_saved_as_complete_is_not_read_again(self, endpoint: str) -> None:
        result = driver().run(
            endpoint,
            always(aws_error("ServiceException", "unexpected request")),
            resume_state=AwsOrganizationsResumeConfig(next_token=None),
        )

        assert result.raised is None
        assert result.requests == []
        assert result.rows == []


class TestResume:
    def test_an_expired_saved_token_restarts_the_walk_instead_of_failing(self) -> None:
        def responder(request: RecordedRequest) -> ScriptedResponse:
            if request.json().get("NextToken") == "stale":
                return aws_error(
                    "InvalidInputException", "INVALID_PAGINATION_TOKEN: Get the value for the NextToken parameter"
                )
            return ScriptedResponse(json=page("Accounts", [{"Id": "111111111111"}]))

        result = driver().run("accounts", responder, resume_state=AwsOrganizationsResumeConfig(next_token="stale"))

        assert result.raised is None
        assert [request.json().get("NextToken") for request in result.requests] == ["stale", None]
        assert [row["id"] for row in result.rows] == ["111111111111"]

    def test_policies_resume_picks_up_at_the_policy_type_after_the_completed_one(self) -> None:
        def responder(request: RecordedRequest) -> ScriptedResponse:
            return ScriptedResponse(json=page("Policies", [{"Id": f"p-{request.json()['Filter'].lower()}"}]))

        result = driver().run(
            "policies", responder, resume_state=AwsOrganizationsResumeConfig(work_key=POLICY_FILTERS[0])
        )

        assert result.raised is None
        assert [request.json()["Filter"] for request in result.requests] == list(POLICY_FILTERS[1:])

    @pytest.mark.parametrize("endpoint", ["policies", "policy_targets"])
    def test_policies_resume_continues_a_half_walked_policy_type(self, endpoint: str) -> None:
        result = driver().run(
            endpoint,
            always(ScriptedResponse(json=page("Policies", [{"Id": "p-example"}]))),
            resume_state=AwsOrganizationsResumeConfig(next_token="page-two", work_key=POLICY_FILTERS[1]),
        )

        assert result.raised is None
        assert (request_operation(result.requests[0]), result.requests[0].json()) == (
            "ListPolicies",
            {"Filter": POLICY_FILTERS[1], "MaxResults": MAX_RESULTS, "NextToken": "page-two"},
        )
        assert [
            request.json()["Filter"] for request in result.requests if request_operation(request) == "ListPolicies"
        ] == list(POLICY_FILTERS[1:])


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "code,expected_valid",
        [
            # A denied DescribeOrganization still proves the key is genuine.
            ("AccessDeniedException", True),
            ("AWSOrganizationsNotInUseException", False),
            ("UnrecognizedClientException", False),
            ("SignatureDoesNotMatch", False),
        ],
    )
    def test_only_a_bad_key_or_a_missing_organization_blocks_source_creation(
        self, code: str, expected_valid: bool
    ) -> None:
        with scripted_network([aws_error(code, "message")]) as network:
            valid, reason = validate_credentials("AKIAEXAMPLE", "secret", None)

        assert valid is expected_valid
        assert (reason is None) is expected_valid
        assert [request_operation(request) for request in network.requests_log] == ["DescribeOrganization"]

    def test_a_reachable_organization_validates(self) -> None:
        with scripted_network([ScriptedResponse(json={"Organization": {"Id": "o-example"}})]) as network:
            assert validate_credentials("AKIAEXAMPLE", "secret", None) == (True, None)

        assert [request_operation(request) for request in network.requests_log] == ["DescribeOrganization"]

    @pytest.mark.parametrize(
        "access_key_id,secret_access_key",
        [("", "secret"), ("AKIAEXAMPLE", ""), ("", "")],
    )
    def test_missing_credentials_are_rejected_without_a_request(
        self, access_key_id: str, secret_access_key: str
    ) -> None:
        with scripted_network([]) as network:
            valid, reason = validate_credentials(access_key_id, secret_access_key, None)

        assert valid is False
        assert reason == "AWS access key ID and secret access key are required"
        assert network.requests_log == []

    def test_a_schema_name_probes_that_table_rather_than_the_organization(self) -> None:
        with scripted_network(
            [aws_error("AccessDeniedException", "not authorized to perform organizations:ListAccounts")]
        ) as network:
            valid, reason = validate_credentials("AKIAEXAMPLE", "secret", None, schema_name="accounts")

        assert valid is False
        assert reason is not None
        assert "organizations:ListAccounts" in reason
        assert [request_operation(request) for request in network.requests_log] == ["ListAccounts"]


class TestProbeEndpointPermissions:
    def test_a_denied_table_names_the_missing_action_and_the_rest_stay_reachable(self) -> None:
        def responder(request: RecordedRequest) -> ScriptedResponse:
            match request_operation(request):
                case "ListPolicies":
                    return aws_error("AccessDeniedException", "not authorized to perform organizations:ListPolicies")
                case "ListParents":
                    return aws_error("AccessDeniedException", "not authorized to perform organizations:ListParents")
                case "ListAccounts":
                    if request.json().get("NextToken") is None:
                        return ScriptedResponse(json=page("Accounts", [], next_token="accounts-2"))
                    return ScriptedResponse(json=page("Accounts", [{"Id": "111111111111"}]))
                case "ListRoots":
                    return ScriptedResponse(json=page("Roots", [{"Id": "r-exam"}]))
                case "ListOrganizationalUnitsForParent":
                    return ScriptedResponse(json=page("OrganizationalUnits", []))
                case _:
                    return ScriptedResponse(json={"Organization": {"Id": "o-example"}})

        with scripted_network(responder) as network:
            reasons = probe_endpoint_permissions(
                "AKIAEXAMPLE",
                "secret",
                None,
                ["accounts", "organization", "organizational_units", "policies", "account_parents"],
            )

        assert reasons["accounts"] is None
        assert reasons["account_parents"] is not None
        assert "organizations:ListParents" in reasons["account_parents"]
        assert reasons["organization"] is None
        assert reasons["organizational_units"] is None
        assert reasons["policies"] is not None
        assert "organizations:ListPolicies" in reasons["policies"]
        assert [request_operation(request) for request in network.requests_log] == [
            "ListAccounts",
            "DescribeOrganization",
            "ListRoots",
            "ListOrganizationalUnitsForParent",
            "ListPolicies",
            "ListAccounts",
            "ListAccounts",
            "ListParents",
        ]

    @pytest.mark.parametrize("error", [AwsOrganizationsRetryableError("TooManyRequestsException", "slow down")])
    def test_a_transient_failure_is_not_reported_as_a_permission_problem(self, error: Exception) -> None:
        assert isinstance(error, AwsOrganizationsRetryableError)
        with scripted_network(always(aws_error(error.code, error.message))) as network:
            assert probe_endpoint_permissions("AKIAEXAMPLE", "secret", None, ["accounts"]) == {"accounts": None}

        assert {request_operation(request) for request in network.requests_log} == {"ListAccounts"}
