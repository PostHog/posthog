from collections.abc import Iterable
from typing import cast

import pytest
from unittest import mock

from parameterized import parameterized
from structlog.testing import capture_logs

from products.warehouse_sources.backend.models.external_data_schema import SCHEMA_RESOURCE_ID_METADATA_KEY
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.sharepoint import (
    SharePointSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sharepoint.settings import (
    FILE_NOT_FOUND_ERROR,
    PATTERN_ERROR,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sharepoint.source import SharePointSource
from products.warehouse_sources.backend.temporal.data_imports.sources.sharepoint.tests.test_sharepoint import (
    CLIENT_ID,
    CLIENT_SECRET,
    FILES_MODULE,
    MODULE,
    SITE_A,
    SITE_URL,
    TENANT_ID,
    _g,
    _manager,
    _session,
    excel_bytes,
    file_routes,
)


def make_config(
    enabled: bool | None = True, site_urls: str | None = SITE_URL, pattern: str | None = None
) -> SharePointSourceConfig:
    values: dict[str, object] = {
        "tenant_id": TENANT_ID,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "site_urls": site_urls,
    }
    if enabled is not None:
        values["import_files"] = {"enabled": enabled, "file_pattern": pattern}
    return SharePointSourceConfig.from_dict(values)


def make_inputs(schema_name: str, resource_id: str | None) -> SourceInputs:
    return SourceInputs(
        schema_name=schema_name,
        schema_id="schema-id",
        source_id="source-id",
        team_id=1,
        should_use_incremental_field=False,
        db_incremental_field_last_value=None,
        db_incremental_field_earliest_value=None,
        incremental_field=None,
        incremental_field_type=None,
        job_id="job-id",
        logger=mock.MagicMock(),
        reset_pipeline=False,
        schema_metadata={SCHEMA_RESOURCE_ID_METADATA_KEY: resource_id} if resource_id is not None else None,
    )


class TestSharePointSchemas:
    def test_discovers_one_table_per_visible_worksheet(self) -> None:
        routes = file_routes([{"id": "item-a", "name": "report.xlsx", "file": {}}])
        routes[_g("/drives/drive-a/items/item-a/content")] = excel_bytes()
        with mock.patch(f"{MODULE}.make_tracked_session", return_value=_session(routes)):
            schemas = SharePointSource().get_schemas(make_config(), team_id=1)

        assert [
            (schema.name, schema.label, schema.description, schema.schema_metadata)
            for schema in schemas
            if schema.schema_metadata
        ] == [
            (
                "shared_documents_report_sales_north",
                "Shared Documents/report.xlsx [Sales - North]",
                "Rows of the worksheet Sales - North in the Excel file Shared Documents/report.xlsx",
                {SCHEMA_RESOURCE_ID_METADATA_KEY: "drive-a:item-a:Sales - North"},
            ),
            (
                "shared_documents_report_sales_south",
                "Shared Documents/report.xlsx [Sales South]",
                "Rows of the worksheet Sales South in the Excel file Shared Documents/report.xlsx",
                {SCHEMA_RESOURCE_ID_METADATA_KEY: "drive-a:item-a:Sales South"},
            ),
        ]

    @parameterized.expand([("reported_size",), ("download_size",), ("corrupt",), ("missing",)])
    def test_skips_unreadable_workbooks_and_keeps_sibling_csv(self, case: str) -> None:
        routes = file_routes(
            [
                {"id": "item-a", "name": "report.xlsx", "file": {}, "size": 51 if case == "reported_size" else 1},
                {"id": "csv", "name": "orders.csv", "file": {}},
            ]
        )
        routes[_g("/drives/drive-a/items/item-a/content")] = (
            404 if case == "missing" else b"not a zip" if case == "corrupt" else excel_bytes()
        )
        session = _session(routes)
        with (
            mock.patch(f"{MODULE}.make_tracked_session", return_value=session),
            mock.patch(f"{FILES_MODULE}.MAX_EXCEL_FILE_BYTES", 50),
            capture_logs() as logs,
        ):
            schemas = SharePointSource().get_schemas(make_config(), team_id=1)

        assert [schema.name for schema in schemas if schema.schema_metadata] == ["shared_documents_orders"]
        assert any(
            log.get("log_level") == "warning" and log.get("path") == "Shared Documents/report.xlsx" for log in logs
        )
        if case == "reported_size":
            assert not any(call.args[0].endswith("/content") for call in session.get.call_args_list)

    def test_caps_excel_downloads_in_discovery_order(self) -> None:
        routes = file_routes(
            [
                {"id": "first", "name": "first.xlsx", "file": {}},
                {"id": "second", "name": "second.xlsx", "file": {}},
                {"id": "csv", "name": "orders.csv", "file": {}},
            ]
        )
        routes[_g("/drives/drive-a/items/first/content")] = excel_bytes()
        session = _session(routes)
        with (
            mock.patch(f"{MODULE}.make_tracked_session", return_value=session),
            mock.patch(f"{FILES_MODULE}.MAX_EXCEL_FILES", 1),
            capture_logs() as logs,
        ):
            schemas = SharePointSource().get_schemas(make_config(), team_id=1)

        assert [schema.name for schema in schemas if schema.schema_metadata] == [
            "shared_documents_first_sales_north",
            "shared_documents_first_sales_south",
            "shared_documents_orders",
        ]
        assert any(log.get("log_level") == "warning" and log.get("skipped_files") == 1 for log in logs)
        assert not any("second/content" in call.args[0] for call in session.get.call_args_list)

    @parameterized.expand(
        [
            ("absent", None, None),
            ("off", False, None),
            ("static_names", True, ["drives"]),
            ("empty_names", True, []),
        ]
    )
    def test_static_catalog_needs_no_requests(self, _name: str, enabled: bool | None, names: list[str] | None) -> None:
        session = _session({})
        source = SharePointSource()
        with mock.patch(f"{MODULE}.make_tracked_session", return_value=session):
            expected = source.get_schemas(make_config(enabled=None, site_urls=None), team_id=1, names=names)
            schemas = source.get_schemas(make_config(enabled=enabled, site_urls=None), team_id=1, names=names)

        assert schemas == expected
        session.get.assert_not_called()
        session.post.assert_not_called()

    @parameterized.expand(
        [
            ("all", None),
            ("combined_names", ["sites", "shared_documents_orders"]),
        ]
    )
    def test_discovers_file_schemas_with_resource_ids(self, _name: str, names: list[str] | None) -> None:
        session = _session(file_routes([{"id": "item-a", "name": "orders.csv", "file": {}}]))
        source = SharePointSource()
        static = source.get_schemas(make_config(enabled=False), team_id=1, names=names)
        with mock.patch(f"{MODULE}.make_tracked_session", return_value=session):
            schemas = source.get_schemas(make_config(), team_id=1, names=names)

        assert schemas[:-1] == static
        file = schemas[-1]
        assert file.name == "shared_documents_orders"
        assert file.label == "Shared Documents/orders.csv"
        assert file.description == "Rows of the CSV file Shared Documents/orders.csv"
        assert file.schema_metadata == {SCHEMA_RESOURCE_ID_METADATA_KEY: "drive-a:item-a"}
        assert not file.supports_append and not file.supports_incremental


class TestSharePointCredentialValidation:
    @parameterized.expand(
        [
            ("missing_sites", None, None, "Enter at least one site URL to import file contents."),
            ("blank_sites", " ,\n ", None, "Enter at least one site URL to import file contents."),
            ("invalid_pattern", SITE_URL, "([", PATTERN_ERROR),
        ]
    )
    def test_rejects_invalid_file_settings_without_http(
        self, _name: str, site_urls: str | None, pattern: str | None, expected: str
    ) -> None:
        session = _session({})
        with mock.patch(f"{MODULE}.make_tracked_session", return_value=session):
            valid, error = SharePointSource().validate_credentials(make_config(site_urls=site_urls, pattern=pattern), 1)

        assert valid is False
        assert error is not None and error.startswith(expected)
        session.get.assert_not_called()
        session.post.assert_not_called()

    def test_validates_the_site_without_discovering_files(self) -> None:
        session = _session({_g("/sites/contoso.sharepoint.com:/sites/a:"): {"id": SITE_A}})
        with mock.patch(f"{MODULE}.make_tracked_session", return_value=session):
            assert SharePointSource().validate_credentials(make_config(pattern=r"\.csv$"), 1) == (True, None)

        assert session.get.call_count == 1


class TestSharePointPipeline:
    @parameterized.expand([("static", "sites", None), ("file", "old_table_name", "drive-a:item-a")])
    def test_routes_static_tables_and_stored_file_ids(
        self, _name: str, schema_name: str, resource_id: str | None
    ) -> None:
        session = _session(
            {
                _g("/sites/contoso.sharepoint.com:/sites/a:"): {"id": SITE_A},
                _g("/drives/drive-a/items/item-a"): {"name": "new-name.csv"},
                _g("/drives/drive-a/items/item-a/content"): b"id\n1\n",
            }
        )
        manager = _manager()
        with mock.patch(f"{MODULE}.make_tracked_session", return_value=session):
            response = SharePointSource().source_for_pipeline(
                make_config(), manager, make_inputs(schema_name, resource_id)
            )
            rows = [row for chunk in cast(Iterable[list[dict[str, object]]], response.items()) for row in chunk]

        if resource_id is None:
            assert rows == [{"id": SITE_A}]
        else:
            assert rows == [{"id": "1", "_file_name": "new-name.csv", "_file_modified_at": None}]
            assert response.supports_resume is False
            manager.save_state.assert_not_called()

    def test_missing_metadata_fails_before_http(self) -> None:
        session = _session({})
        with mock.patch(f"{MODULE}.make_tracked_session", return_value=session):
            with pytest.raises(ValueError, match=f"^{FILE_NOT_FOUND_ERROR}"):
                SharePointSource().source_for_pipeline(make_config(), _manager(), make_inputs("orders", None))

        session.get.assert_not_called()
        session.post.assert_not_called()
