from typing import Any

import pytest
from unittest import mock

from requests.exceptions import RequestException

from products.warehouse_sources.sources.sdk import ResumableSourceManager
from products.warehouse_sources.sources.sdk.testing import RecordedRequest, ScriptedResponse, scripted_network
from products.warehouse_sources.sources.zoho_crm._config import ZohoCRMSourceConfig
from products.warehouse_sources.sources.zoho_crm.settings import ENDPOINTS, ZOHO_CRM_ENDPOINTS
from products.warehouse_sources.sources.zoho_crm.source import ZohoCRMSource
from products.warehouse_sources.sources.zoho_crm.zoho_crm import (
    CLIENT_REJECTED_MESSAGE,
    CLIENT_SECRET_REJECTED_MESSAGE,
    REFRESH_TOKEN_REJECTED_MESSAGE,
    ZohoCRMAuthError,
    ZohoCRMResumeConfig,
)

_SOURCE_MODULE = "products.warehouse_sources.sources.zoho_crm.source"

INCREMENTAL_ENDPOINTS = sorted(name for name, config in ZOHO_CRM_ENDPOINTS.items() if config.incremental)
FULL_REFRESH_ENDPOINTS = sorted(name for name, config in ZOHO_CRM_ENDPOINTS.items() if not config.incremental)


def _inputs(schema_name: str = "Leads", **overrides: Any) -> mock.MagicMock:
    defaults: dict[str, Any] = {
        "schema_name": schema_name,
        "schema_id": "schema-1",
        "source_id": "source-1",
        "team_id": 1,
        "should_use_incremental_field": False,
        "db_incremental_field_last_value": None,
        "db_incremental_field_earliest_value": None,
        "incremental_field": None,
        "incremental_field_type": None,
        "job_id": "job-1",
        "logger": mock.MagicMock(),
        "reset_pipeline": False,
        "api_version": None,
    }
    defaults.update(overrides)
    return mock.MagicMock(**defaults)


class TestZohoCRMSource:
    def setup_method(self) -> None:
        self.source = ZohoCRMSource()
        self.team_id = 123
        self.config = ZohoCRMSourceConfig(region="eu", client_id="cid", client_secret="secret", refresh_token="refresh")

    def test_api_version_is_pinned_to_what_the_transport_calls(self) -> None:
        assert self.source.supported_versions == ("v8",)
        assert self.source.default_version == "v8"
        assert self.source.api_docs_url.startswith("https://")

    @mock.patch(f"{_SOURCE_MODULE}.validate_zoho_crm_credentials")
    def test_validate_credentials_passes_the_resolved_version(self, mock_validate: mock.MagicMock) -> None:
        mock_validate.return_value = (True, None)

        assert self.source.validate_credentials(self.config, self.team_id) == (True, None)
        assert mock_validate.call_args.kwargs == {
            "region": "eu",
            "client_id": "cid",
            "client_secret": "secret",
            "refresh_token": "refresh",
            "api_version": "v8",
        }

    @pytest.mark.parametrize(
        "probe_result, expected",
        [
            ((False, REFRESH_TOKEN_REJECTED_MESSAGE), REFRESH_TOKEN_REJECTED_MESSAGE),
            ((False, None), "Invalid Zoho CRM credentials"),
        ],
    )
    @mock.patch(f"{_SOURCE_MODULE}.validate_zoho_crm_credentials")
    def test_validate_credentials_surfaces_a_reason(
        self, mock_validate: mock.MagicMock, probe_result: tuple[bool, str | None], expected: str
    ) -> None:
        mock_validate.return_value = probe_result

        assert self.source.validate_credentials(self.config, self.team_id) == (False, expected)

    def test_resumable_manager_is_namespaced_per_schema(self) -> None:
        manager = self.source.get_resumable_source_manager(_inputs("Contacts"))

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is ZohoCRMResumeConfig
        assert manager._namespace == "Contacts"

    @mock.patch(f"{_SOURCE_MODULE}.zoho_crm_source")
    def test_source_for_pipeline_plumbs_the_incremental_cursor(self, mock_source: mock.MagicMock) -> None:
        manager = mock.MagicMock()
        inputs = _inputs(
            "Deals",
            should_use_incremental_field=True,
            db_incremental_field_last_value="2024-06-01T00:00:00+00:00",
            incremental_field="Modified_Time",
        )

        self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = mock_source.call_args.kwargs
        assert kwargs["region"] == "eu"
        assert kwargs["endpoint"] == "Deals"
        assert kwargs["api_version"] == "v8"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2024-06-01T00:00:00+00:00"
        assert kwargs["incremental_field"] == "Modified_Time"

    @mock.patch(f"{_SOURCE_MODULE}.zoho_crm_source")
    def test_full_refresh_never_forwards_a_stale_watermark(self, mock_source: mock.MagicMock) -> None:
        inputs = _inputs(
            "Leads", should_use_incremental_field=False, db_incremental_field_last_value="2024-06-01T00:00:00+00:00"
        )

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_source.call_args.kwargs["db_incremental_field_last_value"] is None


@pytest.mark.parametrize(
    ("error_code", "expected"),
    [
        ("invalid_code", REFRESH_TOKEN_REJECTED_MESSAGE),
        ("invalid_client", CLIENT_REJECTED_MESSAGE),
        ("invalid_client_secret", CLIENT_SECRET_REJECTED_MESSAGE),
        (None, REFRESH_TOKEN_REJECTED_MESSAGE),
    ],
)
def test_sync_token_failure_shows_the_message_for_its_error_code(error_code: str | None, expected: str) -> None:
    error = str(ZohoCRMAuthError(error_code)).lower()
    friendly = [
        message for pattern, message in ZohoCRMSource().get_non_retryable_errors().items() if pattern.lower() in error
    ]

    assert friendly[0] == expected


def test_edition_dependent_modules_do_not_sync_by_default() -> None:
    # Each of these only exists on some Zoho CRM editions (Inventory), so Zoho answers
    # INVALID_MODULE for an org that never enabled it. A default-synced module fails every first
    # sync for such an org instead of just sitting unticked.
    for name in (
        "Vendors",
        "Price_Books",
        "Quotes",
        "Sales_Orders",
        "Purchase_Orders",
        "Invoices",
        "Cases",
        "Solutions",
    ):
        assert ZOHO_CRM_ENDPOINTS[name].should_sync_default is False


_MODULES = [
    {"api_name": "Leads", "generated_type": "default", "api_supported": True},
    {"api_name": "Projects", "generated_type": "custom", "api_supported": True},
    {"api_name": "Deals_X_Contacts", "generated_type": "linking", "api_supported": True},
    {"api_name": "Hidden_Custom", "generated_type": "custom", "api_supported": False},
    {"api_name": "Web_Tab", "generated_type": "web", "api_supported": True},
    {"api_name": "Territories", "generated_type": "custom", "api_supported": True},
]


def _zoho(modules_status: int = 200) -> Any:
    def respond(request: RecordedRequest) -> ScriptedResponse:
        if request.path == "/oauth/v2/token":
            return ScriptedResponse(json={"access_token": "token", "api_domain": "https://www.zohoapis.com"})
        return ScriptedResponse(status=modules_status, json={"modules": _MODULES})

    return respond


class TestCustomModuleDiscovery:
    def setup_method(self) -> None:
        self.source = ZohoCRMSource()
        self.config = ZohoCRMSourceConfig(region="us", client_id="cid", client_secret="secret", refresh_token="refresh")

    def test_adds_custom_and_linking_modules_unticked(self) -> None:
        with scripted_network(_zoho()):
            schemas = self.source.get_schemas(self.config, team_id=1)

        by_name = {schema.name: schema for schema in schemas}
        custom = ["Custom_Projects", "Custom_Deals_X_Contacts", "Custom_Territories"]
        assert [schema.name for schema in schemas] == [*ENDPOINTS, *custom]
        for name in custom:
            assert by_name[name].should_sync_default is False
            assert [field["field"] for field in by_name[name].incremental_fields] == ["Modified_Time"]

    @pytest.mark.parametrize(
        ("config", "names"),
        [
            (ZohoCRMSourceConfig(region="us", client_id="", client_secret="", refresh_token=""), None),
            (ZohoCRMSourceConfig(region="us", client_id="cid", client_secret="secret", refresh_token="r"), ["Leads"]),
        ],
        ids=["no_credentials", "only_static_names"],
    )
    def test_skips_discovery_when_it_cannot_add_anything(
        self, config: ZohoCRMSourceConfig, names: list[str] | None
    ) -> None:
        with scripted_network(_zoho()) as network:
            schemas = self.source.get_schemas(config, team_id=1, names=names)

        assert network.requests_log == []
        assert [schema.name for schema in schemas] == (names or list(ENDPOINTS))

    def test_failed_discovery_raises_instead_of_dropping_custom_modules(self) -> None:
        with scripted_network(_zoho(modules_status=500)):
            with pytest.raises(RequestException):
                self.source.get_schemas(self.config, team_id=1)

    def test_names_filter_finds_a_discovered_module(self) -> None:
        with scripted_network(_zoho()):
            schemas = self.source.get_schemas(self.config, team_id=1, names=["Custom_Projects"])

        assert [schema.name for schema in schemas] == ["Custom_Projects"]
