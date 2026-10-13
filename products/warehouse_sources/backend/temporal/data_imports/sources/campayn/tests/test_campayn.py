import pytest

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.campayn.campayn import (
    base_url,
    campayn_source,
    is_subdomain_valid,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.campayn.settings import (
    CAMPAYN_ENDPOINTS,
    ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.campayn.source import CampaynSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.campayn import (
    CampaynSourceConfig,
)


def _driver() -> SourceDriver:
    return SourceDriver(CampaynSource(), CampaynSourceConfig(subdomain="acme", api_key="k"))


class TestIsSubdomainValid:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("acme", True),
            ("acme-corp", True),
            ("acme.campayn.com", True),
            ("https://acme.campayn.com", True),
            # Pasted paths/URLs collapse to the bare label, so these end up safe.
            ("acme/../evil", True),
            ("acme@evil.com", False),
            ("acme.evil.com", False),
            ("acme corp", False),
            ("", False),
        ],
    )
    def test_validity(self, raw: str, expected: bool) -> None:
        assert is_subdomain_valid(raw) is expected


class TestFanOut:
    def test_contacts_fan_out_injects_list_id(self) -> None:
        result = _driver().run(
            "contacts",
            [
                ScriptedResponse(json=[{"id": "10"}, {"id": "20"}]),
                ScriptedResponse(json=[{"id": "1", "email": "a@x.com"}]),
                ScriptedResponse(json=[{"id": "2", "email": "b@x.com"}]),
            ],
        )

        assert result.raised is None
        assert result.items == [
            [{"id": "1", "email": "a@x.com", "list_id": "10"}],
            [{"id": "2", "email": "b@x.com", "list_id": "20"}],
        ]
        assert result.urls == [
            f"{base_url('acme')}/lists.json",
            f"{base_url('acme')}/lists/10/contacts.json",
            f"{base_url('acme')}/lists/20/contacts.json",
        ]

    def test_fan_out_skips_list_deleted_mid_sync(self) -> None:
        # A list deleted between enumeration and the child fetch 404s — skip it, keep syncing.
        result = _driver().run(
            "contacts",
            [
                ScriptedResponse(json=[{"id": "10"}, {"id": "20"}]),
                ScriptedResponse(status=404, json={"error": "not found"}),
                ScriptedResponse(json=[{"id": "2"}]),
            ],
        )

        assert result.raised is None
        assert result.items == [[{"id": "2", "list_id": "20"}]]

    def test_fan_out_reraises_non_404_http_error(self) -> None:
        result = _driver().run(
            "forms",
            [
                ScriptedResponse(json=[{"id": "10"}]),
                ScriptedResponse(status=403, json={"error": "forbidden"}),
            ],
        )

        assert isinstance(result.raised, requests.HTTPError)
        assert "403 Client Error" in str(result.raised)

    def test_fan_out_fails_loudly_on_parent_row_missing_id(self) -> None:
        # `id` drives all fan-out, so a malformed list record must fail rather than silently
        # dropping its contacts/forms.
        result = _driver().run("contacts", [ScriptedResponse(json=[{"name": "no id here"}])])

        assert isinstance(result.raised, ValueError)
        assert "field 'id'" in str(result.raised)


class TestErrorHandling:
    @pytest.mark.parametrize("status", [429, 500, 503])
    def test_retryable_statuses_raise_retryable_error(self, status: int) -> None:
        result = _driver().run("lists", always(ScriptedResponse(status=status, json={})))

        assert isinstance(result.raised, RESTClientRetryableError)
        assert len(result.requests) == 5

    @pytest.mark.parametrize(
        "status, reason",
        [(401, "Unauthorized"), (403, "Forbidden"), (404, "Not Found")],
    )
    def test_client_errors_raise_http_error(self, status: int, reason: str) -> None:
        result = _driver().run("lists", [ScriptedResponse(status=status, json={})])

        # The "<status> Client Error" prefix is what get_non_retryable_errors matches on.
        assert isinstance(result.raised, requests.HTTPError)
        assert f"{status} Client Error" in str(result.raised)
        assert reason in str(result.raised)


class TestCampaynSource:
    def test_all_endpoints_buildable_with_correct_primary_keys(self) -> None:
        for endpoint in ENDPOINTS:
            response = campayn_source("acme", "k", endpoint, team_id=1, job_id="j")
            assert response.name == endpoint
            assert response.primary_keys == CAMPAYN_ENDPOINTS[endpoint].primary_keys
            # No stable creation-time field exists, so nothing is partitioned.
            assert response.partition_mode is None


class TestValidateCredentials:
    def test_connection_error_returns_false(self) -> None:
        with scripted_network(always(ConnectionResetError("boom"))) as network:
            assert validate_credentials("acme", "k") is False

        assert network.requests_log[0].path == "/api/v1/lists.json"
