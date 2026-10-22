from typing import Any, cast

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.kommo import KommoSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.kommo.kommo import (
    KommoResumeConfig,
    get_resource,
    normalize_subdomain,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.kommo.settings import ENDPOINT_CONFIG, ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.kommo.source import KommoSource


def _leads_page(ids: list[int], page: int, page_count: int) -> dict[str, Any]:
    return {
        "_page": page,
        "_page_count": page_count,
        "_embedded": {"leads": [{"id": lead_id, "updated_at": 1700000000 + lead_id} for lead_id in ids]},
    }


class TestNormalizeSubdomain:
    @pytest.mark.parametrize(
        "raw",
        [
            "",
            "   ",
            "acme.amocrm.ru",
            "evil.example.com",
            "acme.kommo.com.evil.example.com",
            "acme..kommo.com",
            "-acme",
            "acme-",
            "acme_corp",
            "acme:8080",
            "10.0.0.1",
            "acme kommo",
        ],
    )
    def test_rejects_anything_that_is_not_a_single_kommo_label(self, raw: str) -> None:
        # The subdomain picks the host the access token is sent to, so a value that
        # smuggles another host through must be rejected rather than normalized.
        assert normalize_subdomain(raw) is None


class TestGetResource:
    def test_every_declared_endpoint_builds_a_resource(self) -> None:
        for name in ENDPOINTS:
            resource = get_resource(name, should_use_incremental_field=False)
            endpoint = cast(dict[str, Any], resource["endpoint"])

            assert resource["name"] == name
            assert resource["primary_key"] == ENDPOINT_CONFIG[name].primary_key
            assert endpoint["path"].startswith("/api/v4/")
            assert endpoint["data_selector"].startswith("_embedded.")

    @pytest.mark.parametrize("name", ["Leads", "Contacts", "Companies", "LeadNotes", "ContactNotes", "CompanyNotes"])
    def test_incremental_endpoints_bind_the_updated_at_filter_and_merge(self, name: str) -> None:
        resource = get_resource(name, should_use_incremental_field=True)
        params = cast(dict[str, Any], resource["endpoint"])["params"]

        assert params["filter[updated_at][from]"] == {
            "type": "incremental",
            "cursor_path": "updated_at",
            "initial_value": 0,
        }
        assert params["order[updated_at]"] == "asc"
        assert resource["write_disposition"] == {"disposition": "merge", "strategy": "upsert"}

    @pytest.mark.parametrize("name", ["Tasks", "Events", "Pipelines", "Users", "Catalogs", "LeadTags"])
    def test_full_refresh_endpoints_never_bind_a_filter_even_when_asked(self, name: str) -> None:
        # Tasks and Events do expose a server-side timestamp filter but no ordering parameter for
        # it, so they must stay full refresh: an unordered incremental sync corrupts the watermark.
        resource = get_resource(name, should_use_incremental_field=True)
        params = cast(dict[str, Any], resource["endpoint"])["params"]

        assert not any(key.startswith("filter[") for key in params)
        assert resource["write_disposition"] == "replace"


class TestKommoSourceTransport:
    @staticmethod
    def _driver() -> SourceDriver:
        return SourceDriver(KommoSource(), KommoSourceConfig(subdomain="acme", api_key="test-token"))

    def test_full_refresh_run_checkpoints_the_next_page_after_each_batch(self) -> None:
        result = self._driver().run(
            "Leads",
            [
                ScriptedResponse(json=_leads_page([1], page=1, page_count=3)),
                ScriptedResponse(json=_leads_page([2], page=2, page_count=3)),
                ScriptedResponse(json=_leads_page([3], page=3, page_count=3)),
            ],
        )

        assert result.raised is None
        assert result.params("page") == ["1", "2", "3"]
        assert result.params("limit") == ["250", "250", "250"]
        assert [row["id"] for row in result.rows] == [1, 2, 3]
        assert result.saved_states == [KommoResumeConfig(page=2), KommoResumeConfig(page=3)]
        assert result.committed_states == result.saved_states
        assert result.response is not None
        assert result.response.name == "Leads"
        assert result.response.primary_keys == ["id"]
        assert result.response.sort_mode == "asc"

    def test_full_refresh_run_resumes_from_the_saved_page(self) -> None:
        result = self._driver().run(
            "Leads",
            [ScriptedResponse(json=_leads_page([9], page=7, page_count=7))],
            resume_state=KommoResumeConfig(page=7),
        )

        assert result.raised is None
        assert result.params("page") == ["7"]
        assert [row["id"] for row in result.rows] == [9]


class TestValidateCredentials:
    @pytest.mark.parametrize(
        ("status_code", "expected_ok", "expected_message_fragment"),
        [
            (402, False, "not paid up"),
            (404, False, "acme.kommo.com"),
        ],
    )
    def test_maps_status_codes_to_actionable_results(
        self, status_code: int, expected_ok: bool, expected_message_fragment: str | None
    ) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code, json={}))) as network:
            is_valid, message = validate_credentials("test-token", "acme")

        assert is_valid is expected_ok
        assert network.requests_log[0].path == "/api/v4/account"
        assert network.requests_log[0].headers["authorization"] == "Bearer test-token"
        if expected_message_fragment is None:
            assert message is None
        else:
            assert message is not None and expected_message_fragment in message
