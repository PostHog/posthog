import json
import datetime as dt
from collections.abc import Callable
from typing import Any, Optional

import pytest
from unittest import mock

import requests
import structlog

from products.warehouse_sources.backend.temporal.data_imports.sources.aws_organizations import aws_organizations
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_organizations.aws_organizations import (
    AwsOrganizationsClient,
    AwsOrganizationsError,
    AwsOrganizationsResumeConfig,
    AwsOrganizationsRetryableError,
    error_for_response,
    get_rows,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

LOGGER = structlog.get_logger()

ACCOUNTS = AWS_ORGANIZATIONS_ENDPOINTS["accounts"]
ORGANIZATION = AWS_ORGANIZATIONS_ENDPOINTS["organization"]
ORGANIZATIONAL_UNITS = AWS_ORGANIZATIONS_ENDPOINTS["organizational_units"]
POLICIES = AWS_ORGANIZATIONS_ENDPOINTS["policies"]
RESOURCE_TAGS = AWS_ORGANIZATIONS_ENDPOINTS["resource_tags"]
ROOTS = AWS_ORGANIZATIONS_ENDPOINTS["roots"]

JAN_2025 = 1735689600.0  # 2025-01-01T00:00:00Z

Responder = Callable[[str, dict[str, Any]], dict[str, Any]]


class FakeResumeManager(ResumableSourceManager[AwsOrganizationsResumeConfig]):
    def __init__(self, state: Optional[AwsOrganizationsResumeConfig] = None) -> None:
        self.state = state
        self.saved: list[AwsOrganizationsResumeConfig] = []
        self.cleared = False

    def can_resume(self) -> bool:
        return self.state is not None

    def load_state(self) -> Optional[AwsOrganizationsResumeConfig]:
        return self.state

    def save_state(self, data: AwsOrganizationsResumeConfig) -> None:
        self.saved.append(data)

    def clear_state(self) -> None:
        self.cleared = True


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


def install_api(responder: Responder) -> list[tuple[str, dict[str, Any]]]:
    calls: list[tuple[str, dict[str, Any]]] = []

    def request(self: AwsOrganizationsClient, operation: str, payload: dict[str, Any]) -> dict[str, Any]:
        calls.append((operation, dict(payload)))
        return responder(operation, dict(payload))

    patcher = mock.patch.object(AwsOrganizationsClient, "request", request)
    patcher.start()
    return calls


@pytest.fixture(autouse=True)
def stop_patches():
    yield
    mock.patch.stopall()


def run_endpoint(
    endpoint: str, responder: Responder, manager: Optional[FakeResumeManager] = None
) -> tuple[list[list[dict[str, Any]]], list[tuple[str, dict[str, Any]]], FakeResumeManager]:
    calls = install_api(responder)
    resume_manager = manager if manager is not None else FakeResumeManager()
    batches = list(
        get_rows(
            aws_access_key_id="AKIAEXAMPLE",
            aws_secret_access_key="secret",
            aws_session_token=None,
            endpoint=endpoint,
            api_version=None,
            resumable_source_manager=resume_manager,
            logger=LOGGER,
        )
    )
    return batches, calls, resume_manager


def flatten(batches: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    return [row for batch in batches for row in batch]


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

    def test_organization_row_drops_the_deprecated_available_policy_types_member(self) -> None:
        row = normalize_row(
            ORGANIZATION,
            {
                "Id": "o-example",
                "Arn": "arn:aws:organizations::111111111111:organization/o-example",
                "FeatureSet": "ALL",
                "MasterAccountArn": "arn:aws:organizations::111111111111:account/o-example/111111111111",
                "MasterAccountEmail": "owner@example.com",
                "MasterAccountId": "111111111111",
                "AvailablePolicyTypes": [{"Type": "SERVICE_CONTROL_POLICY", "Status": "ENABLED"}],
            },
        )

        assert row == {
            "id": "o-example",
            "arn": "arn:aws:organizations::111111111111:organization/o-example",
            "feature_set": "ALL",
            "master_account_arn": "arn:aws:organizations::111111111111:account/o-example/111111111111",
            "master_account_email": "owner@example.com",
            "master_account_id": "111111111111",
        }

    def test_root_row_keeps_the_policy_type_list_whole(self) -> None:
        row = normalize_row(
            ROOTS,
            {
                "Id": "r-exam",
                "Name": "Root",
                "PolicyTypes": [{"Type": "TAG_POLICY", "Status": "ENABLED"}],
            },
        )

        assert row == {
            "id": "r-exam",
            "name": "Root",
            "policy_types": [{"Type": "TAG_POLICY", "Status": "ENABLED"}],
        }


class TestSignedRequest:
    def test_request_is_signed_for_the_global_endpoint_and_names_the_operation(self) -> None:
        sent: list[dict[str, Any]] = []

        class FakeSession:
            def post(
                self,
                url: str,
                data: Optional[bytes] = None,
                headers: Optional[dict[str, str]] = None,
                timeout: Optional[int] = None,
            ) -> requests.Response:
                sent.append({"url": url, "data": data, "headers": headers or {}})
                return make_response(200, {"Organization": {"Id": "o-example"}})

        with mock.patch.object(aws_organizations, "make_tracked_session", return_value=FakeSession()):
            client = AwsOrganizationsClient("AKIAEXAMPLE", "secret", None)
            body = client.send("DescribeOrganization", {})

        assert body == {"Organization": {"Id": "o-example"}}
        assert sent[0]["url"] == ORGANIZATIONS_ENDPOINT_URL
        assert sent[0]["headers"]["X-Amz-Target"] == "AWSOrganizationsV20161128.DescribeOrganization"
        assert sent[0]["headers"]["Content-Type"] == "application/x-amz-json-1.1"
        # Organizations is global: a signature scoped anywhere but us-east-1/organizations is
        # rejected as SignatureDoesNotMatch, which reads to the user as a bad key.
        assert "/us-east-1/organizations/aws4_request" in sent[0]["headers"]["Authorization"]

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
    def test_walk_continues_past_an_empty_page_and_stops_only_on_a_null_token(self) -> None:
        pages = [
            page("Accounts", [{"Id": "111111111111"}], next_token="one"),
            # Documented behavior: a list operation can return an empty page while more
            # results are still available.
            page("Accounts", [], next_token="two"),
            page("Accounts", [{"Id": "222222222222"}]),
        ]

        def responder(operation: str, payload: dict[str, Any]) -> dict[str, Any]:
            token = payload.get("NextToken")
            index = {None: 0, "one": 1, "two": 2}[token]
            return pages[index]

        batches, calls, _ = run_endpoint("accounts", responder)

        assert [row["id"] for row in flatten(batches)] == ["111111111111", "222222222222"]
        assert [call[1].get("NextToken") for call in calls] == [None, "one", "two"]

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
        def responder(called_operation: str, payload: dict[str, Any]) -> dict[str, Any]:
            if called_operation == "ListAccounts":
                return page("Accounts", [{"Id": "111111111111"}])
            if called_operation == "ListRoots":
                return page("Roots", [{"Id": "r-exam"}])
            if called_operation == "ListOrganizationalUnitsForParent":
                return page("OrganizationalUnits", [])
            if called_operation == "ListPolicies":
                return page("Policies", [])
            return page("Tags", [{"Key": "team", "Value": "growth"}])

        _, calls, _ = run_endpoint(endpoint, responder)

        payloads = [payload for called_operation, payload in calls if called_operation == operation]
        assert payloads
        for payload in payloads:
            assert ("MaxResults" in payload) is expects_max_results
            if expects_max_results:
                assert payload["MaxResults"] == MAX_RESULTS

    def test_single_object_endpoint_issues_one_call_and_one_row(self) -> None:
        def responder(operation: str, payload: dict[str, Any]) -> dict[str, Any]:
            return {"Organization": {"Id": "o-example", "FeatureSet": "ALL"}}

        batches, calls, _ = run_endpoint("organization", responder)

        assert calls == [("DescribeOrganization", {})]
        assert flatten(batches) == [{"id": "o-example", "feature_set": "ALL"}]


class TestPolicies:
    def test_one_walk_per_policy_type(self) -> None:
        def responder(operation: str, payload: dict[str, Any]) -> dict[str, Any]:
            return page("Policies", [{"Id": f"p-{payload['Filter'].lower()}", "Type": payload["Filter"]}])

        batches, calls, _ = run_endpoint("policies", responder)

        assert [payload["Filter"] for _, payload in calls] == list(POLICY_FILTERS)
        assert len(flatten(batches)) == len(POLICY_FILTERS)

    @pytest.mark.parametrize(
        "code,message",
        [
            ("UnsupportedAPIEndpointException", "This action isn't available in the current AWS Region."),
            ("InvalidInputException", "INVALID_ENUM_POLICY_TYPE: You specified an invalid policy type string."),
        ],
    )
    def test_a_policy_type_this_organization_does_not_offer_is_skipped(self, code: str, message: str) -> None:
        def responder(operation: str, payload: dict[str, Any]) -> dict[str, Any]:
            if payload["Filter"] == "SERVICE_CONTROL_POLICY":
                raise AwsOrganizationsError(code, message)
            return page("Policies", [{"Id": "p-example", "Type": payload["Filter"]}])

        batches, _, _ = run_endpoint("policies", responder)

        assert len(flatten(batches)) == len(POLICY_FILTERS) - 1

    def test_a_denied_policy_type_fails_the_sync(self) -> None:
        def responder(operation: str, payload: dict[str, Any]) -> dict[str, Any]:
            raise AwsOrganizationsError("AccessDeniedException", "not authorized for organizations:ListPolicies")

        with pytest.raises(AwsOrganizationsError, match="AccessDeniedException"):
            run_endpoint("policies", responder)


class TestOrganizationalUnits:
    def test_nested_units_are_discovered_and_stamped_with_their_parent(self) -> None:
        children = {
            "r-exam": [{"Id": "ou-exam-aaaaaaaa", "Name": "Engineering"}],
            "ou-exam-aaaaaaaa": [{"Id": "ou-exam-bbbbbbbb", "Name": "Platform"}],
            "ou-exam-bbbbbbbb": [],
        }

        def responder(operation: str, payload: dict[str, Any]) -> dict[str, Any]:
            if operation == "ListRoots":
                return page("Roots", [{"Id": "r-exam"}])
            return page("OrganizationalUnits", children[payload["ParentId"]])

        batches, _, _ = run_endpoint("organizational_units", responder)

        assert [(row["id"], row["parent_id"], row["parent_type"]) for row in flatten(batches)] == [
            ("ou-exam-aaaaaaaa", "r-exam", "ROOT"),
            ("ou-exam-bbbbbbbb", "ou-exam-aaaaaaaa", "ORGANIZATIONAL_UNIT"),
        ]

    def test_a_unit_returned_twice_does_not_walk_the_same_subtree_forever(self) -> None:
        def responder(operation: str, payload: dict[str, Any]) -> dict[str, Any]:
            if operation == "ListRoots":
                return page("Roots", [{"Id": "r-exam"}])
            if payload["ParentId"] == "r-exam":
                return page("OrganizationalUnits", [{"Id": "ou-exam-aaaaaaaa"}, {"Id": "ou-exam-aaaaaaaa"}])
            return page("OrganizationalUnits", [])

        batches, calls, _ = run_endpoint("organizational_units", responder)

        assert len(flatten(batches)) == 2
        assert [payload["ParentId"] for operation, payload in calls if operation.startswith("ListOrg")] == [
            "r-exam",
            "ou-exam-aaaaaaaa",
        ]


class TestResourceTags:
    def _responder(self, missing: Optional[str] = None) -> Responder:
        def responder(operation: str, payload: dict[str, Any]) -> dict[str, Any]:
            if operation == "ListAccounts":
                return page("Accounts", [{"Id": "111111111111"}])
            if operation == "ListRoots":
                return page("Roots", [{"Id": "r-exam"}])
            if operation == "ListOrganizationalUnitsForParent":
                if payload["ParentId"] == "r-exam":
                    return page("OrganizationalUnits", [{"Id": "ou-exam-aaaaaaaa"}])
                return page("OrganizationalUnits", [])
            if operation == "ListPolicies":
                if payload["Filter"] == "SERVICE_CONTROL_POLICY":
                    return page("Policies", [{"Id": "p-example"}])
                return page("Policies", [])
            if payload["ResourceId"] == missing:
                raise AwsOrganizationsError("TargetNotFoundException", "We can't find that target.")
            return page("Tags", [{"Key": "team", "Value": payload["ResourceId"]}])

        return responder

    def test_tags_are_collected_from_every_taggable_resource_type(self) -> None:
        batches, _, _ = run_endpoint("resource_tags", self._responder())

        assert [(row["resource_id"], row["resource_type"], row["key"], row["value"]) for row in flatten(batches)] == [
            ("111111111111", "ACCOUNT", "team", "111111111111"),
            ("r-exam", "ROOT", "team", "r-exam"),
            ("ou-exam-aaaaaaaa", "ORGANIZATIONAL_UNIT", "team", "ou-exam-aaaaaaaa"),
            ("p-example", "POLICY", "team", "p-example"),
        ]

    def test_a_resource_deleted_mid_sync_is_skipped(self) -> None:
        batches, _, _ = run_endpoint("resource_tags", self._responder(missing="r-exam"))

        assert [row["resource_id"] for row in flatten(batches)] == [
            "111111111111",
            "ou-exam-aaaaaaaa",
            "p-example",
        ]

    def test_primary_key_is_unique_per_resource_and_tag_key(self) -> None:
        rows = flatten(run_endpoint("resource_tags", self._responder())[0])
        keys = [tuple(row[column] for column in RESOURCE_TAGS.primary_key or []) for row in rows]

        assert len(set(keys)) == len(keys)


class TestResume:
    def test_a_saved_token_starts_the_walk_where_the_last_attempt_stopped(self) -> None:
        def responder(operation: str, payload: dict[str, Any]) -> dict[str, Any]:
            assert payload["NextToken"] == "page-two"
            return page("Accounts", [{"Id": "222222222222"}])

        manager = FakeResumeManager(AwsOrganizationsResumeConfig(next_token="page-two"))
        batches, calls, _ = run_endpoint("accounts", responder, manager=manager)

        assert len(calls) == 1
        assert [row["id"] for row in flatten(batches)] == ["222222222222"]

    def test_state_is_saved_after_every_page_and_cleared_once_the_walk_completes(self) -> None:
        def responder(operation: str, payload: dict[str, Any]) -> dict[str, Any]:
            if payload.get("NextToken") is None:
                return page("Accounts", [{"Id": "111111111111"}], next_token="page-two")
            return page("Accounts", [{"Id": "222222222222"}])

        _, _, manager = run_endpoint("accounts", responder)

        assert [state.next_token for state in manager.saved] == ["page-two", None]
        assert manager.cleared is True

    def test_an_expired_saved_token_restarts_the_walk_instead_of_failing(self) -> None:
        def responder(operation: str, payload: dict[str, Any]) -> dict[str, Any]:
            if payload.get("NextToken") == "stale":
                raise AwsOrganizationsError(
                    "InvalidInputException", "INVALID_PAGINATION_TOKEN: Get the value for the NextToken parameter"
                )
            return page("Accounts", [{"Id": "111111111111"}])

        manager = FakeResumeManager(AwsOrganizationsResumeConfig(next_token="stale"))
        batches, calls, _ = run_endpoint("accounts", responder, manager=manager)

        assert [payload.get("NextToken") for _, payload in calls] == ["stale", None]
        assert [row["id"] for row in flatten(batches)] == ["111111111111"]

    def test_policies_resume_picks_up_at_the_policy_type_after_the_completed_one(self) -> None:
        def responder(operation: str, payload: dict[str, Any]) -> dict[str, Any]:
            return page("Policies", [{"Id": f"p-{payload['Filter'].lower()}"}])

        manager = FakeResumeManager(AwsOrganizationsResumeConfig(work_key=POLICY_FILTERS[0]))
        _, calls, _ = run_endpoint("policies", responder, manager=manager)

        assert [payload["Filter"] for _, payload in calls] == list(POLICY_FILTERS[1:])

    def test_policies_resume_continues_a_half_walked_policy_type(self) -> None:
        def responder(operation: str, payload: dict[str, Any]) -> dict[str, Any]:
            return page("Policies", [{"Id": "p-example"}])

        manager = FakeResumeManager(AwsOrganizationsResumeConfig(next_token="page-two", work_key=POLICY_FILTERS[1]))
        _, calls, _ = run_endpoint("policies", responder, manager=manager)

        assert calls[0] == (
            "ListPolicies",
            {"Filter": POLICY_FILTERS[1], "MaxResults": MAX_RESULTS, "NextToken": "page-two"},
        )
        assert [payload["Filter"] for _, payload in calls] == list(POLICY_FILTERS[1:])


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
        def responder(operation: str, payload: dict[str, Any]) -> dict[str, Any]:
            raise AwsOrganizationsError(code, "message")

        install_api(responder)
        valid, reason = validate_credentials("AKIAEXAMPLE", "secret", None)

        assert valid is expected_valid
        assert (reason is None) is expected_valid

    def test_a_reachable_organization_validates(self) -> None:
        def responder(operation: str, payload: dict[str, Any]) -> dict[str, Any]:
            assert operation == "DescribeOrganization"
            return {"Organization": {"Id": "o-example"}}

        install_api(responder)

        assert validate_credentials("AKIAEXAMPLE", "secret", None) == (True, None)

    @pytest.mark.parametrize(
        "access_key_id,secret_access_key",
        [("", "secret"), ("AKIAEXAMPLE", ""), ("", "")],
    )
    def test_missing_credentials_are_rejected_without_a_request(
        self, access_key_id: str, secret_access_key: str
    ) -> None:
        calls = install_api(lambda operation, payload: {})

        valid, reason = validate_credentials(access_key_id, secret_access_key, None)

        assert valid is False
        assert reason == "AWS access key ID and secret access key are required"
        assert calls == []

    def test_a_schema_name_probes_that_table_rather_than_the_organization(self) -> None:
        def responder(operation: str, payload: dict[str, Any]) -> dict[str, Any]:
            if operation == "ListAccounts":
                raise AwsOrganizationsError(
                    "AccessDeniedException", "not authorized to perform organizations:ListAccounts"
                )
            return page("Accounts", [])

        install_api(responder)
        valid, reason = validate_credentials("AKIAEXAMPLE", "secret", None, schema_name="accounts")

        assert valid is False
        assert reason is not None
        assert "organizations:ListAccounts" in reason


class TestProbeEndpointPermissions:
    def test_a_denied_table_names_the_missing_action_and_the_rest_stay_reachable(self) -> None:
        def responder(operation: str, payload: dict[str, Any]) -> dict[str, Any]:
            if operation == "ListPolicies":
                raise AwsOrganizationsError(
                    "AccessDeniedException", "not authorized to perform organizations:ListPolicies"
                )
            if operation == "ListAccounts":
                return page("Accounts", [{"Id": "111111111111"}])
            if operation == "ListRoots":
                return page("Roots", [{"Id": "r-exam"}])
            if operation == "ListTagsForResource":
                return page("Tags", [])
            if operation == "ListOrganizationalUnitsForParent":
                return page("OrganizationalUnits", [])
            return {"Organization": {"Id": "o-example"}}

        install_api(responder)
        reasons = probe_endpoint_permissions(
            "AKIAEXAMPLE", "secret", None, ["accounts", "organization", "organizational_units", "policies"]
        )

        assert reasons["accounts"] is None
        assert reasons["organization"] is None
        assert reasons["organizational_units"] is None
        assert reasons["policies"] is not None
        assert "organizations:ListPolicies" in reasons["policies"]

    @pytest.mark.parametrize("error", [AwsOrganizationsRetryableError("TooManyRequestsException", "slow down")])
    def test_a_transient_failure_is_not_reported_as_a_permission_problem(self, error: Exception) -> None:
        def responder(operation: str, payload: dict[str, Any]) -> dict[str, Any]:
            raise error

        install_api(responder)

        assert probe_endpoint_permissions("AKIAEXAMPLE", "secret", None, ["accounts"]) == {"accounts": None}
