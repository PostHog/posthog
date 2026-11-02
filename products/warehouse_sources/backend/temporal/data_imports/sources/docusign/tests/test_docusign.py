import time
import datetime as dt
from collections.abc import Iterable
from typing import Any, Optional, cast

import pytest
from unittest import mock

import requests
from structlog.types import FilteringBoundLogger

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.docusign.docusign import (
    PAGE_SIZE,
    DocusignAuthError,
    DocusignCredentials,
    DocusignResumeConfig,
    _default_from_date,
    _to_iso8601,
    docusign_source,
    mint_access_token,
    resolve_account,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.docusign.source import DocusignSource
from products.warehouse_sources.backend.temporal.data_imports.sources.docusign.tests.conftest import (
    PRIVATE_KEY_PEM,
    FakeResponse,
    FakeResumeManager,
    FakeSession,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.docusign import (
    DocusignAuthTypeConfig,
    DocusignSourceConfig,
)

_DOCUSIGN_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.docusign.docusign"
_SESSION_FACTORY = f"{_DOCUSIGN_MODULE}.make_tracked_session"

USERINFO_PAYLOAD: dict[str, Any] = {
    "sub": "user-guid",
    "accounts": [
        {"account_id": "111", "is_default": False, "account_name": "Old", "base_uri": "https://na2.docusign.net"},
        {"account_id": "222", "is_default": True, "account_name": "Main", "base_uri": "https://na3.docusign.net/"},
    ],
}

TOKEN_PAYLOAD: dict[str, Any] = {"access_token": "tok-1", "expires_in": 3600, "token_type": "Bearer"}


def jwt_credentials(**overrides: Any) -> DocusignCredentials:
    defaults: dict[str, Any] = {
        "environment": "production",
        "selection": "jwt",
        "integration_key": "int-key",
        "user_id": "user-guid",
        "private_key": PRIVATE_KEY_PEM,
    }
    defaults.update(overrides)
    return DocusignCredentials(**defaults)


def refresh_credentials(**overrides: Any) -> DocusignCredentials:
    defaults: dict[str, Any] = {
        "environment": "demo",
        "selection": "refresh_token",
        "integration_key": "int-key",
        "secret_key": "sek-ret",
        "refresh_token": "ref-tok",
    }
    defaults.update(overrides)
    return DocusignCredentials(**defaults)


def envelope_page(count: int, offset: int = 0, next_uri: Optional[str] = None) -> dict[str, Any]:
    body: dict[str, Any] = {
        "envelopes": [
            {
                "envelopeId": f"env-{offset + i}",
                "status": "completed",
                "createdDateTime": "2024-01-01T00:00:00.0000000Z",
                "statusChangedDateTime": "2024-02-01T00:00:00.0000000Z",
            }
            for i in range(count)
        ],
        "resultSetSize": str(count),
        "startPosition": str(offset),
    }
    if next_uri is not None:
        body["nextUri"] = next_uri
    return body


def driver() -> SourceDriver:
    return SourceDriver(
        DocusignSource(),
        DocusignSourceConfig(
            auth_type=DocusignAuthTypeConfig(
                selection="jwt", integration_key="int-key", user_id="user-guid", private_key=PRIVATE_KEY_PEM
            ),
            environment="production",
        ),
    )


def auth_responses() -> list[ScriptedResponse]:
    return [ScriptedResponse(json=TOKEN_PAYLOAD), ScriptedResponse(json=USERINFO_PAYLOAD)]


class TestDocusignTransport:
    def test_refresh_token_grant_uses_basic_auth_with_the_integration_key(self) -> None:
        with scripted_network([ScriptedResponse(json=TOKEN_PAYLOAD)]) as network:
            mint_access_token(requests.Session(), refresh_credentials())

        request = network.requests_log[0]
        assert request.url == "https://account-d.docusign.com/oauth/token"
        assert request.body == b"grant_type=refresh_token&refresh_token=ref-tok"
        assert request.headers["authorization"] == "Basic aW50LWtleTpzZWstcmV0"

    @pytest.mark.parametrize(
        "credentials,expected",
        [
            (jwt_credentials(private_key=None), "RSA private key"),
            (jwt_credentials(user_id=None), "impersonated user ID"),
            (refresh_credentials(refresh_token=None), "refresh token"),
            (refresh_credentials(secret_key=None), "secret key"),
        ],
    )
    def test_incomplete_credentials_fail_before_any_request(
        self, credentials: DocusignCredentials, expected: str
    ) -> None:
        with scripted_network([]) as network:
            with pytest.raises(DocusignAuthError) as excinfo:
                mint_access_token(requests.Session(), credentials)

        assert expected in str(excinfo.value)
        assert network.requests_log == []

    @pytest.mark.parametrize(
        "payload,expected_fragment",
        [
            ({"error": "consent_required"}, "error=consent_required"),
            ({"error": "invalid_grant", "error_description": "no soup"}, "error=invalid_grant"),
        ],
    )
    def test_token_errors_surface_docusigns_error_code(self, payload: dict[str, Any], expected_fragment: str) -> None:
        with scripted_network([ScriptedResponse(status=400, json=payload)]):
            with pytest.raises(DocusignAuthError) as excinfo:
                mint_access_token(requests.Session(), jwt_credentials())

        assert expected_fragment in str(excinfo.value)

    def test_token_response_without_access_token_is_an_auth_error(self) -> None:
        with scripted_network([ScriptedResponse(json={"expires_in": 3600})]):
            with pytest.raises(DocusignAuthError):
                mint_access_token(requests.Session(), jwt_credentials())

    @pytest.mark.parametrize(
        "payload,account_id",
        [
            ({"accounts": []}, None),
            (USERINFO_PAYLOAD, "999"),
        ],
    )
    def test_resolve_account_rejects_unreachable_accounts(
        self, payload: dict[str, Any], account_id: Optional[str]
    ) -> None:
        with scripted_network([ScriptedResponse(json=payload)]):
            with pytest.raises(DocusignAuthError):
                resolve_account(requests.Session(), jwt_credentials(account_id=account_id), "tok-1")

    def test_resume_starts_from_the_saved_offset(self, logger: FilteringBoundLogger) -> None:
        result = driver().run(
            "envelopes",
            [*auth_responses(), ScriptedResponse(json=envelope_page(1, offset=400))],
            resume_state=DocusignResumeConfig(start_position=400),
            logger=logger,
        )

        assert result.raised is None
        assert result.requests[-1].param("start_position") == "400"
        assert result.final_state is None

    def test_expired_access_token_is_reminted_once(self, logger: FilteringBoundLogger) -> None:
        result = driver().run(
            "envelopes",
            [
                *auth_responses(),
                ScriptedResponse(status=401, json={"errorCode": "USER_AUTHENTICATION_FAILED"}),
                ScriptedResponse(json={"access_token": "tok-2"}),
                ScriptedResponse(json=envelope_page(1)),
            ],
            logger=logger,
        )

        assert result.raised is None
        assert len(result.items) == 1
        assert [request.method for request in result.requests].count("POST") == 2
        assert result.requests[-1].headers["authorization"] == "Bearer tok-2"

    def test_persistent_api_error_is_raised(self, logger: FilteringBoundLogger) -> None:
        result = driver().run(
            "envelopes",
            [*auth_responses(), ScriptedResponse(status=403, json={"errorCode": "USER_LACKS_PERMISSIONS"})],
            logger=logger,
        )

        assert isinstance(result.raised, requests.HTTPError)

    def test_recipients_are_flattened_out_of_every_role_bucket(self, logger: FilteringBoundLogger) -> None:
        page = envelope_page(1)
        page["envelopes"][0]["recipients"] = {
            "signers": [{"recipientId": "1", "email": "a@example.com"}],
            "carbonCopies": [{"recipientId": "2", "email": "b@example.com"}],
            "recipientCount": "2",
        }
        result = driver().run("envelope_recipients", [*auth_responses(), ScriptedResponse(json=page)], logger=logger)

        assert result.raised is None
        rows = result.rows
        assert [row["recipientType"] for row in rows] == ["signers", "carbonCopies"]
        assert {row["envelopeId"] for row in rows} == {"env-0"}
        assert rows[0]["envelopeStatusChangedDateTime"] == "2024-02-01T00:00:00.0000000Z"
        assert rows[0]["envelopeCreatedDateTime"] == "2024-01-01T00:00:00.0000000Z"
        assert result.requests[-1].param("include") == "recipients"

    @pytest.mark.parametrize("child_key", ["envelopeDocuments", "documents"])
    def test_documents_are_flattened_under_either_key_docusign_uses(
        self, child_key: str, logger: FilteringBoundLogger
    ) -> None:
        page = envelope_page(1)
        page["envelopes"][0][child_key] = [{"documentId": "1", "name": "contract.pdf"}]
        result = driver().run("envelope_documents", [*auth_responses(), ScriptedResponse(json=page)], logger=logger)

        assert result.raised is None
        assert result.rows == [
            {
                "documentId": "1",
                "name": "contract.pdf",
                "envelopeId": "env-0",
                "envelopeCreatedDateTime": "2024-01-01T00:00:00.0000000Z",
                "envelopeStatusChangedDateTime": "2024-02-01T00:00:00.0000000Z",
            }
        ]

    def test_custom_fields_are_flattened_from_both_field_types(self, logger: FilteringBoundLogger) -> None:
        page = envelope_page(1)
        page["envelopes"][0]["customFields"] = {
            "textCustomFields": [
                {"fieldId": "11", "name": "Deal ID", "value": "D-42"},
                {"name": "Ad hoc", "value": "x"},
                {"value": "no name or id"},
            ],
            "listCustomFields": [{"fieldId": "11", "name": "Region", "value": "EMEA", "listItems": ["EMEA", "APAC"]}],
        }
        result = driver().run("envelope_custom_fields", [*auth_responses(), ScriptedResponse(json=page)], logger=logger)

        assert result.raised is None
        assert [(row["customFieldType"], row["fieldId"], row["value"]) for row in result.rows] == [
            ("text", "11", "D-42"),
            ("text", "Ad hoc", "x"),
            ("list", "11", "EMEA"),
        ]
        assert {row["envelopeId"] for row in result.rows} == {"env-0"}
        assert result.rows[0]["envelopeCreatedDateTime"] == "2024-01-01T00:00:00.0000000Z"
        assert result.requests[-1].param("include") == "custom_fields"

    def test_envelopes_without_children_yield_no_rows_but_still_paginate(self, logger: FilteringBoundLogger) -> None:
        result = driver().run(
            "envelope_recipients",
            [
                *auth_responses(),
                ScriptedResponse(json=envelope_page(PAGE_SIZE, next_uri="/restapi/next")),
                ScriptedResponse(json=envelope_page(1, offset=PAGE_SIZE)),
            ],
            logger=logger,
        )

        assert result.raised is None
        assert result.items == []
        assert [state.start_position for state in result.saved_states] == [PAGE_SIZE]
        assert result.params("start_position")[-2:] == ["0", "100"]

    @pytest.mark.parametrize(
        "endpoint_name,sub_resource,sub_body,empty_body,expected_rows",
        [
            (
                "envelope_audit_events",
                "audit_events",
                {
                    "auditEvents": [
                        {"eventFields": [{"name": "logTime", "value": "t0"}, {"name": "Action", "value": "Sent"}]},
                        {"eventFields": [{"name": "logTime", "value": "t1"}, {"name": "Action", "value": "Signed"}]},
                    ]
                },
                {"auditEvents": []},
                [
                    {"envelopeId": "env-0", "logTime": "t0", "Action": "Sent", "eventIndex": 0},
                    {"envelopeId": "env-0", "logTime": "t1", "Action": "Signed", "eventIndex": 1},
                ],
            ),
            (
                "envelope_templates",
                "templates",
                {
                    "templates": [
                        {"templateId": "tpl-1", "name": "NDA", "documentId": "1"},
                        {"templateId": "tpl-1", "name": "NDA", "documentId": "2"},
                        {"templateId": "tpl-2", "name": "Order form", "documentId": "3"},
                    ]
                },
                {},
                [
                    {"envelopeId": "env-0", "templateId": "tpl-1", "name": "NDA", "documentId": "1"},
                    {"envelopeId": "env-0", "templateId": "tpl-2", "name": "Order form", "documentId": "3"},
                ],
            ),
            (
                "envelope_form_data",
                "form_data",
                {"envelopeId": "env-0", "status": "completed", "formData": [{"name": "Company", "value": "Acme"}]},
                {"envelopeId": "env-1", "status": "sent", "formData": []},
                [
                    {"envelopeId": "env-0", "status": "completed", "formData": [{"name": "Company", "value": "Acme"}]},
                    {"envelopeId": "env-1", "status": "sent", "formData": []},
                ],
            ),
        ],
    )
    def test_envelope_sub_resources_are_fetched_per_envelope(
        self,
        endpoint_name: str,
        sub_resource: str,
        sub_body: dict[str, Any],
        empty_body: dict[str, Any],
        expected_rows: list[dict[str, Any]],
        logger: FilteringBoundLogger,
    ) -> None:
        result = driver().run(
            endpoint_name,
            [
                *auth_responses(),
                ScriptedResponse(json=envelope_page(2)),
                ScriptedResponse(json=sub_body),
                ScriptedResponse(json=empty_body),
            ],
            logger=logger,
        )

        assert result.raised is None
        assert result.rows == [
            {
                **row,
                "envelopeCreatedDateTime": "2024-01-01T00:00:00.0000000Z",
                "envelopeStatusChangedDateTime": "2024-02-01T00:00:00.0000000Z",
            }
            for row in expected_rows
        ]
        assert [path.rsplit("/", 2)[-2:] for path in result.paths[-2:]] == [
            ["env-0", sub_resource],
            ["env-1", sub_resource],
        ]
        # Form data is only released to the sender, so received envelopes must not be listed.
        assert result.requests[-3].param("user_filter") == ("sender" if sub_resource == "form_data" else None)
        assert result.final_state is None

    @pytest.mark.parametrize("remaining,expect_pause", [("500", False), ("50", True)])
    def test_per_envelope_requests_pause_when_the_hourly_quota_runs_low(
        self, remaining: str, expect_pause: bool, logger: FilteringBoundLogger
    ) -> None:
        quota_headers = {
            "X-RateLimit-Limit": "1000",
            "X-RateLimit-Remaining": remaining,
            "X-RateLimit-Reset": str(int(time.time()) + 600),
        }
        with mock.patch(f"{_DOCUSIGN_MODULE}.interruptible_wait") as wait:
            result = driver().run(
                "envelope_audit_events",
                [
                    *auth_responses(),
                    ScriptedResponse(json=envelope_page(1), headers=quota_headers),
                    ScriptedResponse(json={"auditEvents": []}),
                ],
                logger=logger,
            )

        assert result.raised is None
        waits = [call.args[0] for call in wait.call_args_list]
        if expect_pause:
            assert len(waits) == 1 and 500 < waits[0] <= 600
        else:
            assert waits == []

    @pytest.mark.parametrize(
        "endpoint_name,body,expected_rows",
        [
            (
                "bulk_send_batches",
                {"bulkBatchSummaries": [{"batchId": "b-1", "submittedDate": "2024-01-01"}]},
                [{"batchId": "b-1", "submittedDate": "2024-01-01"}],
            ),
            (
                # The invoice listing is one response, so a `nextUri` must not start a second request.
                "billing_invoices",
                {"billingInvoices": [{"invoiceId": "inv-1", "balance": "0.00"}], "nextUri": "/restapi/next"},
                [{"invoiceId": "inv-1", "balance": "0.00"}],
            ),
        ],
    )
    def test_date_scoped_full_refresh_endpoints_always_send_from_date(
        self,
        endpoint_name: str,
        body: dict[str, Any],
        expected_rows: list[dict[str, Any]],
        logger: FilteringBoundLogger,
    ) -> None:
        result = driver().run(endpoint_name, [*auth_responses(), ScriptedResponse(json=body)], logger=logger)

        assert result.raised is None
        assert result.rows == expected_rows
        # Without from_date DocuSign narrows the result: an account-wide batch summary with no batch
        # list, or only the last 365 days of invoices.
        assert result.requests[-1].param("from_date") is not None

    def test_bulk_send_batch_envelopes_page_through_each_batch(self, logger: FilteringBoundLogger) -> None:
        batches = {"bulkBatchSummaries": [{"batchId": "b-1"}, {"batchId": ""}, {"batchId": "b-2"}]}
        result = driver().run(
            "bulk_send_batch_envelopes",
            [
                *auth_responses(),
                ScriptedResponse(json=batches),
                ScriptedResponse(json=envelope_page(PAGE_SIZE, next_uri="/restapi/next")),
                ScriptedResponse(json=envelope_page(1, offset=PAGE_SIZE)),
                ScriptedResponse(json={"envelopes": [], "resultSetSize": "0"}),
            ],
            logger=logger,
        )

        assert result.raised is None
        assert len(result.rows) == PAGE_SIZE + 1
        assert {row["bulkSendBatchId"] for row in result.rows} == {"b-1"}
        assert result.rows[-1]["envelopeId"] == f"env-{PAGE_SIZE}"
        assert result.paths[-4:] == [
            "/restapi/v2.1/accounts/222/bulk_send_batch",
            "/restapi/v2.1/accounts/222/bulk_send_batch/b-1/envelopes",
            "/restapi/v2.1/accounts/222/bulk_send_batch/b-1/envelopes",
            "/restapi/v2.1/accounts/222/bulk_send_batch/b-2/envelopes",
        ]
        assert result.params("start_position")[-3:] == ["0", str(PAGE_SIZE), "0"]
        assert result.requests[-4].param("from_date") is not None
        assert result.requests[-1].param("from_date") is None
        assert result.final_state is None

    def test_powerform_form_data_flattens_recipients_and_skips_unreadable_powerforms(
        self, logger: FilteringBoundLogger
    ) -> None:
        powerforms = {"powerForms": [{"powerFormId": "pf-1"}, {"powerFormId": "pf-2"}, {"powerFormId": "pf-3"}]}
        form_data = {
            "envelopes": [
                {
                    "envelopeId": "env-a",
                    "recipients": [
                        {"recipientId": "1", "email": "a@example.com", "formData": [{"name": "Plan", "value": "Pro"}]},
                        {"recipientId": "2", "email": "b@example.com", "formData": []},
                    ],
                },
                {"envelopeId": "env-b", "recipients": []},
                {"recipients": [{"recipientId": "9"}]},
            ]
        }
        result = driver().run(
            "powerform_form_data",
            [
                *auth_responses(),
                ScriptedResponse(json=powerforms),
                ScriptedResponse(status=403, json={"errorCode": "USER_LACKS_PERMISSIONS"}),
                ScriptedResponse(json=form_data),
                ScriptedResponse(status=404, json={"errorCode": "POWERFORM_DOES_NOT_EXIST"}),
            ],
            logger=logger,
        )

        assert result.raised is None
        assert result.rows == [
            {
                "recipientId": "1",
                "email": "a@example.com",
                "formData": [{"name": "Plan", "value": "Pro"}],
                "envelopeId": "env-a",
                "powerFormId": "pf-2",
            },
            {
                "recipientId": "2",
                "email": "b@example.com",
                "formData": [],
                "envelopeId": "env-a",
                "powerFormId": "pf-2",
            },
        ]
        assert [path.rsplit("/", 2)[-2:] for path in result.paths[-3:]] == [
            ["pf-1", "form_data"],
            ["pf-2", "form_data"],
            ["pf-3", "form_data"],
        ]
        assert result.requests[-1].param("data_layout") == "Native"

    @pytest.mark.parametrize(
        "endpoint_name,parent_body,status",
        [
            ("bulk_send_batch_envelopes", {"bulkBatchSummaries": [{"batchId": "b-1"}]}, 403),
            ("powerform_form_data", {"powerForms": [{"powerFormId": "pf-1"}]}, 400),
        ],
    )
    def test_fan_out_errors_outside_the_skip_list_fail_the_table(
        self, endpoint_name: str, parent_body: dict[str, Any], status: int, logger: FilteringBoundLogger
    ) -> None:
        result = driver().run(
            endpoint_name,
            [
                *auth_responses(),
                ScriptedResponse(json=parent_body),
                ScriptedResponse(status=status, json={"errorCode": "INVALID_REQUEST_PARAMETER"}),
            ],
            logger=logger,
        )

        assert isinstance(result.raised, requests.HTTPError)

    @pytest.mark.parametrize(
        "value,expected",
        [
            (None, None),
            (True, None),
            ("", None),
            ("2024-01-01T00:00:00Z", "2024-01-01T00:00:00Z"),
            (dt.datetime(2024, 3, 2, 4, 5, 6), "2024-03-02T04:05:06Z"),
            (
                dt.datetime(2024, 3, 2, 4, 5, 6, tzinfo=dt.timezone(dt.timedelta(hours=2))),
                "2024-03-02T02:05:06Z",
            ),
            (dt.date(2024, 3, 2), "2024-03-02T00:00:00Z"),
        ],
    )
    def test_watermark_coercion(self, value: Any, expected: Optional[str]) -> None:
        assert _to_iso8601(value) == expected

    def test_default_from_date_falls_back_to_a_bounded_lookback(self) -> None:
        fallback = _default_from_date(None)

        parsed = dt.datetime.strptime(fallback, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.UTC)
        assert dt.datetime.now(dt.UTC) - parsed > dt.timedelta(days=700)
        assert _default_from_date("  2020-06-01T00:00:00Z ") == "2020-06-01T00:00:00Z"

    def test_validate_credentials_reports_docusign_error_text(self) -> None:
        with scripted_network([ScriptedResponse(status=400, json={"error": "consent_required"})]):
            valid, message = validate_credentials(jwt_credentials())

        assert valid is False
        assert message is not None and "consent_required" in message

    def test_validate_credentials_succeeds_when_an_account_resolves(self) -> None:
        with scripted_network(auth_responses()) as network:
            assert validate_credentials(jwt_credentials()) == (True, None)
        assert network.requests_log[-1].path == "/oauth/userinfo"

    def test_validate_credentials_swallows_transport_failures(self) -> None:
        with scripted_network([ConnectionError("boom")]) as network:
            valid, message = validate_credentials(jwt_credentials())

        assert valid is False
        assert message == "Could not reach DocuSign with the provided credentials."
        assert {request.path for request in network.requests_log} == {"/oauth/token"}

    def test_unknown_environment_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            _ = jwt_credentials(environment="staging").auth_host

    def test_source_response_items_are_lazy(self, logger: FilteringBoundLogger) -> None:
        session = FakeSession(
            post_responses=[FakeResponse(200, TOKEN_PAYLOAD)],
            get_responses=[FakeResponse(200, USERINFO_PAYLOAD), FakeResponse(200, envelope_page(2))],
        )

        response = docusign_source(
            credentials=jwt_credentials(),
            endpoint_name="envelopes",
            start_date=None,
            resumable_source_manager=FakeResumeManager(),
            logger=logger,
        )
        # Nothing is requested until the pipeline iterates.
        assert session.post_calls == []

        with mock.patch(_SESSION_FACTORY, return_value=session):
            batches = list(cast("Iterable[list[dict[str, Any]]]", response.items()))

        assert [len(batch) for batch in batches] == [2]
        assert isinstance(batches[0], list)
