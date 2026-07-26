import json
from typing import Any, Optional
from urllib.parse import urlparse

import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.gcp_cloud_billing.gcp_cloud_billing import (
    ServiceAccountKey,
    _BillingApiClient,
    _raise_for_status,
    billing_account_resource_name,
    gcp_cloud_billing_source,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.gcp_cloud_billing.settings import (
    BILLING_BUDGETS_HOST,
    CLOUD_BILLING_HOST,
    ENDPOINTS,
    GCP_CLOUD_BILLING_ENDPOINTS,
)

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.gcp_cloud_billing.gcp_cloud_billing"


def _key() -> ServiceAccountKey:
    return ServiceAccountKey(
        project_id="posthog-billing",
        private_key="-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----\n",
        private_key_id="key-id",
        client_email="sa@posthog-billing.iam.gserviceaccount.com",
        token_uri="https://oauth2.googleapis.com/token",
    )


def _response(
    status_code: int = 200,
    body: Optional[dict[str, Any]] = None,
    url: str = f"{CLOUD_BILLING_HOST}/v1/billingAccounts",
) -> requests.Response:
    """A real `requests.Response` so `raise_for_status` and `json` behave like production."""
    response = requests.Response()
    response.status_code = status_code
    response.url = url
    response.reason = {200: "OK", 401: "Unauthorized", 403: "Forbidden", 500: "Internal Server Error"}.get(
        status_code, "Unknown"
    )
    response._content = json.dumps(body or {}).encode()
    return response


def _called_paths(session: mock.MagicMock) -> list[str]:
    return [urlparse(call.args[0]).path for call in session.get.call_args_list]


class TestGcpCloudBillingTransport:
    @pytest.mark.parametrize(
        "entered, expected",
        [
            ("012345-567890-ABCDEF", "billingAccounts/012345-567890-ABCDEF"),
            ("billingAccounts/012345-567890-ABCDEF", "billingAccounts/012345-567890-ABCDEF"),
            ("  billingAccounts/012345-567890-ABCDEF  ", "billingAccounts/012345-567890-ABCDEF"),
            ("  012345-567890-ABCDEF ", "billingAccounts/012345-567890-ABCDEF"),
        ],
    )
    def test_billing_account_resource_name_normalizes_user_input(self, entered: str, expected: str) -> None:
        assert billing_account_resource_name(entered) == expected

    def test_raise_for_status_carries_the_google_error_body(self) -> None:
        response = _response(
            403,
            {
                "error": {
                    "message": "Cloud Billing API has not been used in project 12345 before or it is disabled.",
                }
            },
        )

        with pytest.raises(requests.HTTPError) as raised:
            _raise_for_status(response)

        message = str(raised.value)
        # Both the status line and the body detail have to survive, because non-retryable error
        # matching reads `str(error)` and keys on each of them separately.
        assert "403 Client Error: Forbidden for url: https://cloudbilling.googleapis.com" in message
        assert "has not been used in project" in message

    @mock.patch(f"{_MODULE}._mint_token", return_value="token-1")
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_paginate_follows_page_tokens_until_exhausted(
        self, mock_session: mock.MagicMock, mock_mint: mock.MagicMock
    ) -> None:
        session = mock_session.return_value
        session.get.side_effect = [
            _response(200, {"services": [{"name": "services/A"}], "nextPageToken": "page-2"}),
            _response(200, {"services": [{"name": "services/B"}]}),
        ]

        client = _BillingApiClient(_key())
        batches = list(client.paginate(CLOUD_BILLING_HOST, "/v1/services", "services", 5000, mock.MagicMock()))

        assert batches == [[{"name": "services/A"}], [{"name": "services/B"}]]
        assert session.get.call_args_list[0].kwargs["params"] == {"pageSize": 5000}
        assert session.get.call_args_list[1].kwargs["params"] == {"pageSize": 5000, "pageToken": "page-2"}

    @mock.patch(f"{_MODULE}._mint_token", return_value="token-1")
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_paginate_stops_when_the_api_repeats_a_page_token(
        self, mock_session: mock.MagicMock, mock_mint: mock.MagicMock
    ) -> None:
        session = mock_session.return_value
        session.get.return_value = _response(200, {"services": [{"name": "services/A"}], "nextPageToken": "stuck"})

        client = _BillingApiClient(_key())
        batches = list(client.paginate(CLOUD_BILLING_HOST, "/v1/services", "services", 5000, mock.MagicMock()))

        assert len(batches) == 2
        assert session.get.call_count == 2

    @mock.patch(f"{_MODULE}._mint_token", return_value="token-1")
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_paginate_skips_empty_pages(self, mock_session: mock.MagicMock, mock_mint: mock.MagicMock) -> None:
        session = mock_session.return_value
        session.get.return_value = _response(200, {"nextPageToken": None})

        client = _BillingApiClient(_key())
        batches = list(client.paginate(CLOUD_BILLING_HOST, "/v1/services", "services", 5000, mock.MagicMock()))

        assert batches == []

    @mock.patch(f"{_MODULE}._mint_token", side_effect=["expired-token", "fresh-token"])
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_expired_token_is_reminted_once_and_the_call_replayed(
        self, mock_session: mock.MagicMock, mock_mint: mock.MagicMock
    ) -> None:
        session = mock_session.return_value
        session.get.side_effect = [
            _response(401, {"error": {"message": "Invalid Credentials"}}),
            _response(200, {"services": [{"name": "services/A"}]}),
        ]

        batches = list(get_rows(_key(), None, "services", mock.MagicMock()))

        assert batches == [[{"name": "services/A"}]]
        assert mock_mint.call_count == 2
        assert session.get.call_args_list[0].kwargs["headers"]["Authorization"] == "Bearer expired-token"
        assert session.get.call_args_list[1].kwargs["headers"]["Authorization"] == "Bearer fresh-token"

    @mock.patch(f"{_MODULE}._mint_token", return_value="token-1")
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_permanent_error_is_raised_rather_than_swallowed(
        self, mock_session: mock.MagicMock, mock_mint: mock.MagicMock
    ) -> None:
        mock_session.return_value.get.return_value = _response(403, {"error": {"message": "Permission denied"}})

        with pytest.raises(requests.HTTPError):
            list(get_rows(_key(), None, "services", mock.MagicMock()))

    @mock.patch(f"{_MODULE}._mint_token", return_value="token-1")
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_billing_accounts_are_listed_when_no_account_is_pinned(
        self, mock_session: mock.MagicMock, mock_mint: mock.MagicMock
    ) -> None:
        session = mock_session.return_value
        session.get.return_value = _response(200, {"billingAccounts": [{"name": "billingAccounts/A", "open": True}]})

        batches = list(get_rows(_key(), None, "billing_accounts", mock.MagicMock()))

        assert batches == [[{"name": "billingAccounts/A", "open": True}]]
        assert _called_paths(session) == ["/v1/billingAccounts"]

    @mock.patch(f"{_MODULE}._mint_token", return_value="token-1")
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_pinned_billing_account_is_fetched_directly_instead_of_listed(
        self, mock_session: mock.MagicMock, mock_mint: mock.MagicMock
    ) -> None:
        session = mock_session.return_value
        session.get.return_value = _response(200, {"name": "billingAccounts/A", "open": True})

        batches = list(get_rows(_key(), "A", "billing_accounts", mock.MagicMock()))

        assert batches == [[{"name": "billingAccounts/A", "open": True}]]
        assert _called_paths(session) == ["/v1/billingAccounts/A"]

    @pytest.mark.parametrize(
        "endpoint, data_key, expected_path",
        [
            ("projects", "projectBillingInfo", "/v1/billingAccounts/A/projects"),
            ("sub_accounts", "billingAccounts", "/v1/billingAccounts/A/subAccounts"),
            ("budgets", "budgets", "/v1/billingAccounts/A/budgets"),
        ],
    )
    @mock.patch(f"{_MODULE}._mint_token", return_value="token-1")
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_billing_account_fan_out_tags_rows_with_their_parent(
        self,
        mock_session: mock.MagicMock,
        mock_mint: mock.MagicMock,
        endpoint: str,
        data_key: str,
        expected_path: str,
    ) -> None:
        session = mock_session.return_value
        session.get.side_effect = [
            _response(200, {"billingAccounts": [{"name": "billingAccounts/A"}, {"name": "billingAccounts/B"}]}),
            _response(200, {data_key: [{"name": "child-a"}]}),
            _response(200, {data_key: [{"name": "child-b"}]}),
        ]

        batches = list(get_rows(_key(), None, endpoint, mock.MagicMock()))

        assert batches == [
            [{"name": "child-a", "_billing_account_name": "billingAccounts/A"}],
            [{"name": "child-b", "_billing_account_name": "billingAccounts/B"}],
        ]
        assert _called_paths(session)[1] == expected_path

    @mock.patch(f"{_MODULE}._mint_token", return_value="token-1")
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_budgets_are_read_from_the_budgets_host(
        self, mock_session: mock.MagicMock, mock_mint: mock.MagicMock
    ) -> None:
        session = mock_session.return_value
        session.get.side_effect = [
            _response(200, {"billingAccounts": [{"name": "billingAccounts/A"}]}),
            _response(200, {"budgets": [{"name": "billingAccounts/A/budgets/1"}]}),
        ]

        list(get_rows(_key(), None, "budgets", mock.MagicMock()))

        called_urls = [call.args[0] for call in session.get.call_args_list]
        assert called_urls[0].startswith(CLOUD_BILLING_HOST)
        assert called_urls[1].startswith(BILLING_BUDGETS_HOST)

    @mock.patch(f"{_MODULE}._mint_token", return_value="token-1")
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_pinned_billing_account_skips_the_account_listing_on_fan_out(
        self, mock_session: mock.MagicMock, mock_mint: mock.MagicMock
    ) -> None:
        session = mock_session.return_value
        session.get.return_value = _response(200, {"projectBillingInfo": [{"name": "projects/p/billingInfo"}]})

        batches = list(get_rows(_key(), "billingAccounts/A", "projects", mock.MagicMock()))

        assert batches == [[{"name": "projects/p/billingInfo", "_billing_account_name": "billingAccounts/A"}]]
        assert _called_paths(session) == ["/v1/billingAccounts/A/projects"]

    @mock.patch(f"{_MODULE}._mint_token", return_value="token-1")
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_skus_fan_out_over_services_and_tag_their_service(
        self, mock_session: mock.MagicMock, mock_mint: mock.MagicMock
    ) -> None:
        session = mock_session.return_value
        session.get.side_effect = [
            _response(200, {"services": [{"name": "services/DA34-426B-A397"}]}),
            _response(200, {"skus": [{"name": "services/DA34-426B-A397/skus/AA95-CD31-42FE"}]}),
        ]

        batches = list(get_rows(_key(), None, "skus", mock.MagicMock()))

        assert batches == [
            [
                {
                    "name": "services/DA34-426B-A397/skus/AA95-CD31-42FE",
                    "_service_name": "services/DA34-426B-A397",
                }
            ]
        ]
        assert _called_paths(session) == ["/v1/services", "/v1/services/DA34-426B-A397/skus"]

    @mock.patch(f"{_MODULE}._mint_token", return_value="token-1")
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_fan_out_over_no_parents_yields_nothing(
        self, mock_session: mock.MagicMock, mock_mint: mock.MagicMock
    ) -> None:
        mock_session.return_value.get.return_value = _response(200, {"billingAccounts": []})

        assert list(get_rows(_key(), None, "projects", mock.MagicMock())) == []


class TestGcpCloudBillingValidateCredentials:
    @mock.patch(f"{_MODULE}._mint_token", side_effect=ValueError("Unable to load PEM file"))
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_rejects_a_key_file_that_cannot_mint_a_token(
        self, mock_session: mock.MagicMock, mock_mint: mock.MagicMock
    ) -> None:
        is_valid, message = validate_credentials(_key(), None)

        assert is_valid is False
        assert message is not None
        assert "service account key file" in message

    @mock.patch(f"{_MODULE}._mint_token", return_value="token-1")
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_accepts_a_key_that_can_list_billing_accounts(
        self, mock_session: mock.MagicMock, mock_mint: mock.MagicMock
    ) -> None:
        session = mock_session.return_value
        session.get.return_value = _response(200, {"billingAccounts": [{"name": "billingAccounts/A"}]})

        assert validate_credentials(_key(), None) == (True, None)
        assert session.get.call_args.kwargs["params"] == {"pageSize": 1}

    @mock.patch(f"{_MODULE}._mint_token", return_value="token-1")
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_pinned_account_is_probed_directly(self, mock_session: mock.MagicMock, mock_mint: mock.MagicMock) -> None:
        session = mock_session.return_value
        session.get.return_value = _response(200, {"name": "billingAccounts/A"})

        assert validate_credentials(_key(), "A") == (True, None)
        assert _called_paths(session) == ["/v1/billingAccounts/A"]

    @pytest.mark.parametrize(
        "status_code, expected_fragment",
        [
            (401, "Billing Account Viewer"),
            (403, "Billing Account Viewer"),
            (500, "Could not reach"),
        ],
    )
    @mock.patch(f"{_MODULE}._mint_token", return_value="token-1")
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_maps_api_failures_to_actionable_messages(
        self,
        mock_session: mock.MagicMock,
        mock_mint: mock.MagicMock,
        status_code: int,
        expected_fragment: str,
    ) -> None:
        mock_session.return_value.get.return_value = _response(status_code, {"error": {"message": "nope"}})

        is_valid, message = validate_credentials(_key(), None)

        assert is_valid is False
        assert message is not None
        assert expected_fragment in message

    @mock.patch(f"{_MODULE}._mint_token", return_value="token-1")
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_network_failure_is_not_reported_as_a_permission_problem(
        self, mock_session: mock.MagicMock, mock_mint: mock.MagicMock
    ) -> None:
        mock_session.return_value.get.side_effect = requests.ConnectionError("boom")

        is_valid, message = validate_credentials(_key(), None)

        assert is_valid is False
        assert message == "Could not reach the Google Cloud Billing API. Please try again."


class TestGcpCloudBillingSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint: str) -> None:
        config = GCP_CLOUD_BILLING_ENDPOINTS[endpoint]
        response = gcp_cloud_billing_source(_key(), None, endpoint, mock.MagicMock())

        assert response.name == endpoint
        assert response.primary_keys == config.primary_key
        assert response.sort_mode == "asc"
        assert response.partition_keys is None

    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_every_endpoint_is_keyed_on_a_globally_unique_resource_name(self, endpoint: str) -> None:
        # Google resource names are globally unique, so fan-out children cannot collide across
        # parents even though they are aggregated into one table.
        assert GCP_CLOUD_BILLING_ENDPOINTS[endpoint].primary_key == ["name"]
