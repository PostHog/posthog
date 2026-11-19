import uuid
import contextlib

import pytest
from posthog.test.base import BaseTest
from unittest import mock

from django.db import OperationalError

from parameterized import parameterized

from posthog.credentials_service.errors import CredentialsServiceUnreachableError, SecretMissingError
from posthog.models.integration import UndecryptedIntegrationSecretError
from posthog.temporal.common.errors import NonReportableError

from products.warehouse_sources.backend.models.external_data_schema import (
    ExternalDataSchema,
    SchemaSyncResult,
    persist_schema_metadata,
    update_sync_type_config_keys,
)
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.metadata import sql_schema_metadata
from products.warehouse_sources.backend.temporal.data_imports.workflow_activities import sync_new_schemas as module
from products.warehouse_sources.backend.temporal.data_imports.workflow_activities.sync_new_schemas import (
    SyncNewSchemasActivityInputs,
    sync_new_schemas_activity,
)


def _patch_common(
    source_mock, schemas_created=None, source_api_version=None, merge_error=None, self_managed_migration=False
):
    """Patch DB + registry so the activity runs without a database or real source."""
    existing_source = mock.MagicMock(
        source_type="GoogleAds",
        job_inputs={"k": "v"},
        credentials_integration_id=None,
        deleted=False,
        api_version=source_api_version,
        is_self_managed_migration=self_managed_migration,
    )
    # The store asks the source class where its OAuth pointer is. A MagicMock answer is not an integration id.
    source_mock.in_use_oauth_slot.return_value = None
    existing_source.merge_connection_metadata.side_effect = merge_error
    objects = mock.MagicMock()
    objects.filter.return_value.exclude.return_value.exists.return_value = True
    objects.get.return_value = existing_source

    return {
        "close_old_connections": mock.patch.object(module, "close_old_connections"),
        "objects": mock.patch.object(module.ExternalDataSource, "objects", objects),
        "source_type": mock.patch.object(module, "ExternalDataSourceType", return_value="GoogleAds"),
        "is_registered": mock.patch.object(module.SourceRegistry, "is_registered", return_value=True),
        "get_source": mock.patch.object(module.SourceRegistry, "get_source", return_value=source_mock),
        "sync_old_schemas_with_new_schemas": mock.patch.object(
            module,
            "sync_old_schemas_with_new_schemas",
            return_value=SchemaSyncResult(created=schemas_created or [], deleted=[]),
        ),
        "auto_enable_new_schemas": mock.patch.object(module, "auto_enable_new_schemas", return_value=[]),
    }


def _patch_db(source_type, *, source_exists=True):
    """Patch the DB reads only, so the activity resolves `source_type` through the real enum."""
    objects = mock.MagicMock()
    objects.filter.return_value.exclude.return_value.exists.return_value = source_exists
    objects.get.return_value = mock.MagicMock(
        source_type=source_type,
        job_inputs={"k": "v"},
        credentials_integration_id=None,
        deleted=False,
        api_version=None,
        is_self_managed_migration=False,
    )
    return objects


def test_deleted_source_drops_the_schedule_and_completes():
    # A source deleted since the schedule was created is a race with a schedule that already
    # fired, not a defect. The activity must drop the schedule and complete, because failing
    # here opens an error tracking issue on every remaining discovery run.
    objects = _patch_db("GoogleAds", source_exists=False)

    with (
        mock.patch.object(module, "close_old_connections"),
        mock.patch.object(module.ExternalDataSource, "objects", objects),
        mock.patch.object(module, "delete_discover_schemas_schedule") as delete_schedule,
        mock.patch.object(module, "sync_old_schemas_with_new_schemas") as sync_schemas,
    ):
        sync_new_schemas_activity(SyncNewSchemasActivityInputs(source_id="src", team_id=1))

    delete_schedule.assert_called_once_with("src")
    sync_schemas.assert_not_called()


def test_source_type_the_registry_does_not_know_is_skipped():
    # A stored source type this build does not register (one removed while rows still referenced
    # it, one created by web code before every worker carries it, or a vendor module that failed to
    # import) cannot be synced by any code path here. Resolving it must not fail the activity, or the
    # one row keeps failing every discovery run for good.
    objects = _patch_db("NotARealSourceType")

    with (
        mock.patch.object(module, "close_old_connections"),
        mock.patch.object(module.ExternalDataSource, "objects", objects),
        mock.patch.object(module, "delete_discover_schemas_schedule") as delete_schedule,
        mock.patch.object(module, "sync_old_schemas_with_new_schemas") as sync_schemas,
        mock.patch.object(module.SourceRegistry, "get_source", side_effect=ValueError("Unknown source type")),
    ):
        sync_new_schemas_activity(SyncNewSchemasActivityInputs(source_id="src", team_id=1))

    sync_schemas.assert_not_called()
    # The value can become known again on a newer worker, so the schedule has to survive.
    delete_schedule.assert_not_called()


def _run_activity(
    source_mock, schemas_created=None, source_api_version=None, merge_error=None, self_managed_migration=False
):
    patches = _patch_common(
        source_mock,
        schemas_created,
        source_api_version=source_api_version,
        merge_error=merge_error,
        self_managed_migration=self_managed_migration,
    )
    with contextlib.ExitStack() as stack:
        entered = {name: stack.enter_context(patcher) for name, patcher in patches.items()}
        sync_new_schemas_activity(SyncNewSchemasActivityInputs(source_id="src", team_id=1))
    return entered


@pytest.mark.parametrize(
    "error_msg,non_retryable,retryable,expected_exc",
    [
        (
            "('invalid_grant: Bad Request', {'error': 'invalid_grant', 'error_description': 'Bad Request'})",
            {"invalid_grant": None},
            set(),
            None,
        ),
        (
            "UNAVAILABLE: transient network blip",
            {"invalid_grant": None},
            set(),
            "transient network blip",
        ),
    ],
    ids=["non_retryable_error_is_skipped", "unknown_error_propagates"],
)
def test_get_schemas_error_handling(error_msg, non_retryable, retryable, expected_exc):
    source_mock = mock.MagicMock()
    source_mock.parse_config.return_value = {}
    source_mock.get_schemas.side_effect = Exception(error_msg)
    source_mock.get_non_retryable_errors.return_value = non_retryable
    source_mock.get_retryable_errors.return_value = retryable

    if expected_exc is None:
        _run_activity(source_mock)
    else:
        with pytest.raises(Exception, match=expected_exc):
            _run_activity(source_mock)


def test_retryable_error_is_reraised_for_temporal_retry():
    # A retryable source error (a transient connect blip) must fail the activity as NonReportableError,
    # not complete it. NonReportableError keeps the workflow's Temporal retry (the activity interceptor
    # re-raises it without capturing), so discovery retries within the run instead of skipping the whole
    # ~6h pass. Mirrors import_data_sync's handling of the same get_retryable_errors set.
    source_mock = mock.MagicMock()
    source_mock.parse_config.return_value = {}
    source_mock.get_schemas.side_effect = Exception("250001: Could not connect to Snowflake backend after 3 attempt(s)")
    source_mock.get_non_retryable_errors.return_value = {}
    source_mock.get_retryable_errors.return_value = {"Could not connect to Snowflake backend after"}

    with pytest.raises(NonReportableError):
        _run_activity(source_mock)


@pytest.mark.parametrize(
    "error_msg",
    [
        "HTTPSConnectionPool(host='api.example.com', port=443): Max retries exceeded with url: /v1/things "
        "(Caused by ProxyError('Cannot connect to proxy.', OSError('Tunnel connection failed: 429 Too Many Requests')))",
        "Could not connect to ClickHouse at https://example.invalid:8443: ('Cannot connect to proxy.', TimeoutError('timed out'))",
    ],
    ids=["tunnel_429", "proxy_connect_timeout"],
)
def test_transient_egress_proxy_error_is_reraised_without_source_opt_in(error_msg):
    source_mock = mock.MagicMock()
    source_mock.parse_config.return_value = {}
    source_mock.get_schemas.side_effect = Exception(error_msg)
    source_mock.get_non_retryable_errors.return_value = {}
    source_mock.get_retryable_errors.return_value = set()

    with pytest.raises(NonReportableError) as exc_info:
        _run_activity(source_mock)

    assert str(exc_info.value) == error_msg


def test_proxy_auth_failure_is_still_reported():
    error_msg = (
        "Could not connect to ClickHouse at https://example.invalid:8443: "
        "('Cannot connect to proxy.', OSError('Tunnel connection failed: 407 Proxy Authentication Required'))"
    )
    source_mock = mock.MagicMock()
    source_mock.parse_config.return_value = {}
    source_mock.get_schemas.side_effect = Exception(error_msg)
    source_mock.get_non_retryable_errors.return_value = {}
    source_mock.get_retryable_errors.return_value = set()

    with pytest.raises(Exception, match="407") as exc_info:
        _run_activity(source_mock)

    assert not isinstance(exc_info.value, NonReportableError)


def test_all_source_non_retryable_error_is_skipped():
    # "Database host not allowed" (and the rest of Any_Source_Errors) is raised from shared
    # connection code, not any one source, so it's never in a source's own
    # get_non_retryable_errors. Without merging it in here, discovery retries forever and spams
    # error tracking on a host that will never resolve.
    source_mock = mock.MagicMock()
    source_mock.parse_config.return_value = {}
    source_mock.get_schemas.side_effect = Exception("Database host not allowed: could not resolve host")
    source_mock.get_non_retryable_errors.return_value = {}

    _run_activity(source_mock)


def test_undecrypted_integration_secret_error_is_skipped():
    # Checked by type, not message, so it must be skipped even when get_non_retryable_errors
    # has no matching entry — otherwise discovery retries forever on an unrecoverable decryption
    # failure and spams error tracking every cycle.
    source_mock = mock.MagicMock()
    source_mock.parse_config.return_value = {}
    source_mock.get_schemas.side_effect = UndecryptedIntegrationSecretError()
    source_mock.get_non_retryable_errors.return_value = {}

    _run_activity(source_mock)


@pytest.mark.parametrize(
    "error,expect_capture",
    [
        (CredentialsServiceUnreachableError("connect timeout"), False),
        (SecretMissingError("some_key"), True),
    ],
    ids=["non_reportable_service_unreachable", "reportable_secret_missing"],
)
def test_credentials_service_failure_is_retried_and_reported_by_reportable(error, expect_capture):
    # A credentials-service failure is never the customer's fault, so discovery must not disable
    # the source (would need `handle_non_retryable_error`) — it must re-raise as NonReportableError
    # so the workflow's retry policy picks it back up. `reportable` alone decides whether a person
    # hears about it: capturing an unreachable service opens an issue per credential read for what
    # its own availability alerting already covers. Assert the capture, because asserting the raise
    # alone passes even when everything is captured.
    source_mock = mock.MagicMock()
    source_mock.parse_config.return_value = {}
    source_mock.get_schemas.side_effect = error
    source_mock.get_non_retryable_errors.return_value = {}

    with mock.patch.object(module, "capture_exception") as capture, pytest.raises(NonReportableError):
        _run_activity(source_mock)

    assert capture.called is expect_capture


def test_discovery_passes_schema_metadata_for_non_github_sources():
    source_mock = mock.MagicMock()
    source_mock.parse_config.return_value = {}
    source_mock.get_schemas.return_value = [
        SourceSchema(
            name="budget",
            supports_incremental=False,
            supports_append=False,
            schema_metadata={"source_resource_id": "7"},
        )
    ]

    mocks = _run_activity(source_mock)

    assert mocks["sync_old_schemas_with_new_schemas"].call_args.kwargs["schema_metadata_by_name"] == {
        "budget": {"source_resource_id": "7"}
    }


def test_discovery_uses_source_pinned_api_version():
    # A pinned source must discover schemas under its pin, not the default — dropping the pin
    # here makes discovery reconcile under the wrong vendor version (tables vanish/duplicate).
    source_mock = mock.MagicMock()
    source_mock.parse_config.return_value = {}
    source_mock.get_schemas.return_value = []
    source_mock.resolve_api_version.side_effect = lambda pinned: pinned or "v-default"

    _run_activity(source_mock, source_api_version="v-old")

    assert source_mock.get_schemas.call_args.kwargs["api_version"] == "v-old"


@pytest.mark.parametrize("self_managed_migration, discovers", [(False, True), (True, False)])
def test_discovery_skips_a_source_rooted_at_a_whole_bucket(self_managed_migration, discovers):
    source_mock = mock.MagicMock()
    source_mock.parse_config.return_value = {}
    source_mock.get_schemas.return_value = []

    mocks = _run_activity(source_mock, self_managed_migration=self_managed_migration)

    assert source_mock.get_schemas.called is discovers
    assert mocks["sync_old_schemas_with_new_schemas"].called is discovers


def test_unparseable_config_is_skipped():
    source_mock = mock.MagicMock()
    source_mock.parse_config.side_effect = TypeError("Cannot build 'MySQLSourceConfig' from str; expected a mapping")

    _run_activity(source_mock)

    source_mock.get_schemas.assert_not_called()


def test_created_schemas_are_passed_to_auto_enable():
    source_mock = mock.MagicMock()
    source_mock.parse_config.return_value = {}
    discovered = mock.MagicMock()
    discovered.name = "raw_events"
    source_mock.get_schemas.return_value = [discovered]

    mocks = _run_activity(source_mock, schemas_created=["raw_events"])

    auto_enable = mocks["auto_enable_new_schemas"]
    auto_enable.assert_called_once()
    source_arg, created_arg, source_schemas_arg = auto_enable.call_args.args
    assert source_arg is mocks["objects"].get.return_value
    assert created_arg == ["raw_events"]
    assert source_schemas_arg == {"raw_events": discovered}


def test_auto_enable_not_called_when_nothing_created():
    source_mock = mock.MagicMock()
    source_mock.parse_config.return_value = {}
    source_mock.get_schemas.return_value = []

    mocks = _run_activity(source_mock)

    mocks["auto_enable_new_schemas"].assert_not_called()


def test_probed_metadata_goes_through_the_locked_merge():
    # `source` is read before schema discovery, which is itself a network call, so the write has to
    # re-read the row. Assigning the field here would drop a write that landed in between.
    source_mock = mock.MagicMock()
    source_mock.parse_config.return_value = {}
    source_mock.get_schemas.return_value = []
    source_mock.get_server_metadata.return_value = {"engine": "mongodb", "wire_version": 7}

    mocks = _run_activity(source_mock)

    source = mocks["objects"].get.return_value
    source.merge_connection_metadata.assert_called_once_with({"engine": "mongodb", "wire_version": 7})
    source.save.assert_not_called()


@pytest.mark.parametrize(
    "probe_error,merge_error,expected_merge_calls",
    [
        (Exception("connection refused"), None, 0),
        (None, OperationalError("canceling statement due to lock timeout"), 1),
    ],
    ids=["the_probe_fails", "the_locked_merge_fails"],
)
def test_a_failed_metadata_write_leaves_discovery_successful(probe_error, merge_error, expected_merge_calls):
    # Recording the version is incidental to discovery, and each step fails on its own terms: the
    # probe reaches an unreachable server, and the merge waits on a row lock the backfill command can
    # hold. Either one escaping would fail every discovery pass for that source, and the schemas
    # found just above would never reconcile.
    source_mock = mock.MagicMock()
    source_mock.parse_config.return_value = {}
    source_mock.get_schemas.return_value = []
    source_mock.get_server_metadata.return_value = {"engine": "mongodb", "wire_version": 7}
    source_mock.get_server_metadata.side_effect = probe_error

    mocks = _run_activity(source_mock, merge_error=merge_error)

    mocks["sync_old_schemas_with_new_schemas"].assert_called_once()
    assert mocks["objects"].get.return_value.merge_connection_metadata.call_count == expected_merge_calls


_ORDERS_COLUMNS = [("id", "integer", False), ("total", "numeric", True)]


class TestDiscoveryStoresColumnMetadata(BaseTest):
    def _make_source(self, **kwargs) -> ExternalDataSource:
        return ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            source_type="Postgres",
            created_by=self.user,
            job_inputs={"host": "localhost", "port": 5432, "schema": "public"},
            **kwargs,
        )

    def _discover(self, source: ExternalDataSource, columns: list[tuple[str, str, bool]]) -> ExternalDataSchema:
        source_impl = mock.MagicMock()
        source_impl.in_use_oauth_slot.return_value = None
        source_impl.get_server_metadata.return_value = {}
        source_impl.get_schemas.return_value = [
            SourceSchema(
                name="orders",
                supports_incremental=False,
                supports_append=False,
                columns=columns,
                source_schema="public",
                source_table_name="orders",
                detected_primary_keys=["id"],
            )
        ]
        with (
            mock.patch.object(module, "close_old_connections"),
            mock.patch.object(module.SourceRegistry, "get_source", return_value=source_impl),
        ):
            sync_new_schemas_activity(SyncNewSchemasActivityInputs(source_id=str(source.id), team_id=self.team.pk))
        return ExternalDataSchema.objects.get(source=source, name="orders")

    @parameterized.expand(
        [
            ("synced", {}, True),
            ("synced_and_live_queryable", {"direct_query_enabled": True}, True),
            ("direct", {"access_method": ExternalDataSource.AccessMethod.DIRECT}, False),
        ]
    )
    def test_columns_are_stored_for_a_table_found_after_creation(
        self, _name: str, source_kwargs: dict, expect_metadata: bool
    ) -> None:
        schema = self._discover(self._make_source(**source_kwargs), _ORDERS_COLUMNS)

        config = schema.sync_type_config or {}
        if not expect_metadata:
            assert "schema_metadata" not in config
            return
        assert config["schema_metadata"]["columns"] == [
            {"name": "id", "data_type": "integer", "is_nullable": False},
            {"name": "total", "data_type": "numeric", "is_nullable": True},
        ]
        assert (config["schema_metadata"]["source_schema"], config["schema_metadata"]["source_table_name"]) == (
            "public",
            "orders",
        )
        assert config["primary_key_columns"] == ["id"]

    @parameterized.expand(
        [
            ("unchanged_upstream", _ORDERS_COLUMNS, False),
            ("column_added_upstream", [*_ORDERS_COLUMNS, ("note", "text", True)], True),
        ]
    )
    def test_a_later_run_writes_only_when_columns_changed(
        self, _name: str, later_columns: list[tuple[str, str, bool]], expect_write: bool
    ) -> None:
        source = self._make_source()
        first = self._discover(source, _ORDERS_COLUMNS)

        later = self._discover(source, later_columns)

        assert (later.updated_at != first.updated_at) is expect_write
        assert [c["name"] for c in later.sync_type_config["schema_metadata"]["columns"]] == [
            c[0] for c in later_columns
        ]

    @parameterized.expand(
        [
            ("one_selected_column_dropped", {}, ["id", "total"], ["id"]),
            ("last_selected_column_dropped", {}, ["total"], ["total"]),
            (
                "last_selected_column_dropped_incremental_field_survives",
                {"sync_type": ExternalDataSchema.SyncType.INCREMENTAL},
                ["total"],
                [],
            ),
        ]
    )
    def test_a_dropped_column_leaves_the_selection(
        self,
        _name: str,
        schema_fields: dict,
        enabled_columns: list[str],
        expected_enabled_columns: list[str],
    ) -> None:
        source = self._make_source()
        schema_id = self._discover(source, _ORDERS_COLUMNS).id
        ExternalDataSchema.objects.filter(id=schema_id).update(enabled_columns=enabled_columns, **schema_fields)
        update_sync_type_config_keys(schema_id, self.team.pk, updates={"incremental_field": "id"})

        schema = self._discover(source, [("id", "integer", False)])

        assert schema.enabled_columns == expected_enabled_columns

    def test_a_key_written_after_the_row_was_read_survives(self) -> None:
        source = self._make_source()
        schema = ExternalDataSchema.objects.create(team_id=self.team.pk, source=source, name="orders")
        stale = ExternalDataSchema.objects.get(id=schema.id)
        update_sync_type_config_keys(schema.id, self.team.pk, updates={"cdc_position": "0/16B3748"})

        persist_schema_metadata(stale, schema_metadata=sql_schema_metadata(_ORDERS_COLUMNS))

        schema.refresh_from_db()
        assert schema.sync_type_config["cdc_position"] == "0/16B3748"
        assert schema.sync_type_config["schema_metadata"]["columns"][0]["name"] == "id"
