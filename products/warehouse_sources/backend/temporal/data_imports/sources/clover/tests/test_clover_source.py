from typing import Literal
from urllib.parse import urlsplit

from unittest import mock

from django.test import SimpleTestCase

import structlog
from parameterized import parameterized
from requests.exceptions import ConnectionError

from products.warehouse_sources.backend.facade.source_config import ReleaseStatus, SourceFieldInputConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.clover.clover import CloverResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.clover.source import CloverSource
from products.warehouse_sources.backend.temporal.data_imports.sources.clover.tests.test_clover import (
    MERCHANT_ID,
    NOW_PATCH,
    http_responses,
    manager,
    response,
    rows,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.clover import CloverSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType

TABLES = {
    "orders",
    "line_items",
    "payments",
    "refunds",
    "credit_refunds",
    "items",
    "categories",
    "modifier_groups",
    "modifiers",
    "customers",
    "employees",
    "shifts",
    "tenders",
    "discounts",
    "tax_rates",
}


def token_config(region: Literal["na", "eu", "latam", "sandbox"] = "na") -> CloverSourceConfig:
    return CloverSourceConfig(region=region, merchant_id=MERCHANT_ID, api_token="test-token")


def inputs(schema: str = "items", incremental: bool = False, version: str | None = None) -> SourceInputs:
    return SourceInputs(
        schema_name=schema,
        schema_id="schema1",
        source_id="source1",
        team_id=1,
        should_use_incremental_field=incremental,
        db_incremental_field_last_value=None,
        db_incremental_field_earliest_value=None,
        incremental_field=None,
        incremental_field_type=None,
        job_id="job1",
        logger=structlog.get_logger(),
        reset_pipeline=False,
        api_version=version,
    )


class TestCloverSource(SimpleTestCase):
    def setUp(self) -> None:
        self.source = CloverSource()
        self.config = token_config()

    def test_connection_form_is_visible_and_keeps_api_tokens_secret(self) -> None:
        config = self.source.get_source_config
        self.assertEqual(self.source.source_type, ExternalDataSourceType.CLOVER)
        self.assertEqual(config.label, "Clover (Fiserv)")
        self.assertEqual(config.releaseStatus, ReleaseStatus.BETA)
        self.assertFalse(config.unreleasedSource)
        self.assertEqual(config.iconPath, "/static/services/clover.png")
        self.assertEqual(config.docsUrl, "https://posthog.com/docs/cdp/sources/clover")
        secrets = {field.name for field in config.fields if isinstance(field, SourceFieldInputConfig) and field.secret}
        self.assertEqual(secrets, {"api_token"})

    def test_catalog_lists_full_refresh_tables_without_credentials(self) -> None:
        schemas = self.source.get_schemas(self.config, 1)
        self.assertEqual({schema.name for schema in schemas}, TABLES)
        self.assertTrue(all(not schema.supports_incremental and not schema.supports_append for schema in schemas))
        self.assertTrue(all(not schema.incremental_fields for schema in schemas))
        tables = self.source.get_documented_tables()
        self.assertEqual({table["name"] for table in tables}, TABLES)
        self.assertTrue(all(table["description"] and table["primary_keys"] for table in tables))
        self.assertTrue(all(table["sync_methods"] == ["Full refresh"] for table in tables))
        self.assertEqual(
            [schema.name for schema in self.source.get_schemas(self.config, 1, names=["modifiers"])], ["modifiers"]
        )
        self.assertEqual(self.source.get_schemas(self.config, 1, names=[]), [])

    @parameterized.expand([(200, None, True), (401, None, False), (403, None, True), (403, "payments", False)])
    def test_credentials_probe_the_requested_scope(self, status: int, schema: str | None, valid: bool) -> None:
        with http_responses([response([], status)]) as requests:
            result = self.source.validate_credentials(self.config, 1, schema_name=schema)
        self.assertEqual(result[0], valid)
        path = f"/v3/merchants/{MERCHANT_ID}" + ("/payments" if schema else "")
        self.assertEqual(urlsplit(requests[0].url or "").path, path)
        self.assertEqual(requests[0].headers["Authorization"], "Bearer test-token")

    @parameterized.expand(
        [
            ("na", "api.clover.com"),
            ("eu", "api.eu.clover.com"),
            ("latam", "api.la.clover.com"),
            ("sandbox", "apisandbox.dev.clover.com"),
        ]
    )
    def test_pipeline_uses_the_selected_regional_host(
        self, region: Literal["na", "eu", "latam", "sandbox"], host: str
    ) -> None:
        with http_responses([response([{"id": "item1"}])]) as requests:
            imported = rows(self.source.source_for_pipeline(token_config(region), manager(), inputs()))
        self.assertEqual(imported, [{"id": "item1"}])
        self.assertEqual(urlsplit(requests[0].url or "").hostname, host)

    @parameterized.expand(
        [
            ("", MERCHANT_ID, "Missing Clover API token"),
            ("test-token", "", "Missing Clover merchant ID"),
        ]
    )
    def test_missing_credentials_fail_before_http(self, api_token: str, merchant_id: str, pattern: str) -> None:
        config = CloverSourceConfig(region="na", merchant_id=merchant_id, api_token=api_token)
        with http_responses([]) as requests:
            result = self.source.validate_credentials(config, 1)
        self.assertFalse(result[0])
        self.assertTrue(result[1])
        self.assertEqual(requests, [])
        self.assertIn(pattern, self.source.get_non_retryable_errors())

    def test_network_failure_is_reported_without_exposing_request_details(self) -> None:
        with mock.patch("requests.sessions.Session.send", side_effect=ConnectionError("private request detail")):
            valid, message = self.source.validate_credentials(self.config, 1)
        self.assertFalse(valid)
        self.assertEqual(message, "Could not connect to Clover. Try again.")

    @parameterized.expand([(401, True), (403, True), (429, False), (500, False)])
    def test_only_permanent_http_errors_are_non_retryable(self, status: int, permanent: bool) -> None:
        message = (
            f"{status} Client Error: "
            + ({401: "Unauthorized", 403: "Forbidden"}.get(status, "Transient"))
            + " for url: https://api.clover.com"
        )
        self.assertEqual(any(key in message for key in self.source.get_non_retryable_errors()), permanent)

    def test_manager_serializes_the_resume_data_class(self) -> None:
        resume_manager = self.source.get_resumable_source_manager(inputs())
        self.assertIsInstance(resume_manager, ResumableSourceManager)
        state = CloverResumeConfig(paginator_state={"resource_state": {"offset": 1000}, "end_ms": 2000})
        self.assertEqual(resume_manager._load_json(resume_manager._dump_json(state)), state)

    @mock.patch(NOW_PATCH, return_value=1000)
    def test_pipeline_uses_saved_state_and_stable_creation_partitions(self, now: mock.MagicMock) -> None:
        resume_manager = manager({"window_start_ms": 10, "end_ms": 1000, "resource_state": {"offset": 1000}})
        with http_responses([response([{"id": "order", "createdTime": 20, "modifiedTime": 999}])]) as requests:
            result = self.source.source_for_pipeline(self.config, resume_manager, inputs("orders"))
            imported = rows(result)
        self.assertEqual(imported[0]["created_at"].timestamp(), 0.02)
        self.assertEqual(result.partition_keys, ["created_at"])
        self.assertIn("offset=1000", requests[0].url or "")

    @parameterized.expand([(True, "v3", "full refresh only"), (False, "v4", "Unsupported Clover API version")])
    def test_pipeline_rejects_unverified_modes_and_versions(
        self, incremental: bool, version: str, message: str
    ) -> None:
        with http_responses([]) as requests:
            with self.assertRaisesRegex(ValueError, message):
                self.source.source_for_pipeline(
                    self.config, manager(), inputs(incremental=incremental, version=version)
                )
        self.assertEqual(requests, [])
