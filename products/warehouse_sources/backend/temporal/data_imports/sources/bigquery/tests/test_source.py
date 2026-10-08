import threading
import concurrent.futures
from types import SimpleNamespace
from typing import cast

import pytest
import time_machine
from unittest import mock

from dateutil import parser
from google.api_core.exceptions import (
    BadRequest,
    DeadlineExceeded,
    Forbidden,
    InternalServerError,
    InvalidArgument,
    NotFound,
    PermissionDenied,
    ServiceUnavailable,
)
from google.auth.credentials import Credentials as GoogleAuthCredentials
from google.auth.exceptions import RefreshError
from requests.adapters import HTTPAdapter

from posthog.models.integration import Integration
from posthog.models.team.team import Team

from products.batch_exports.backend.facade.destinations.bigquery import ServiceAccountOwnershipError
from products.warehouse_sources.backend.temporal.data_imports.external_data_job import Any_Source_Errors
from products.warehouse_sources.backend.temporal.data_imports.sources.bigquery import bigquery as bq_module
from products.warehouse_sources.backend.temporal.data_imports.sources.bigquery.bigquery import (
    BIGQUERY_COPY_JOB_TIMEOUT_SECONDS,
    BIGQUERY_CREATE_READ_SESSION_RETRY,
    BIGQUERY_CREDENTIALS_REJECTED_ERROR,
    BIGQUERY_DATASET_NOT_FOUND_ERROR,
    BIGQUERY_HTTP_TIMEOUT_SECONDS,
    BIGQUERY_IMPERSONATION_PERMISSION_ERROR,
    BIGQUERY_INTEGRATION_NOT_FOUND_ERROR,
    BIGQUERY_INVALID_IDENTIFIER_ERROR,
    BIGQUERY_INVALID_KEY_FILE_ERROR,
    BIGQUERY_INVALID_TOKEN_URI_ERROR,
    BIGQUERY_MISSING_KEY_FILE_FIELDS_ERROR,
    BIGQUERY_NO_CREDENTIALS_ERROR,
    BIGQUERY_QUERY_CREATE_RETRY,
    BIGQUERY_QUERY_JOB_RETRY,
    BIGQUERY_READ_ROWS_RETRY,
    BIGQUERY_ROW_COUNT_JOB_TIMEOUT_SECONDS,
    BIGQUERY_TOKEN_REFRESH_RETRY,
    BIGQUERY_TOKEN_RESPONSE_ERROR,
    BIGQUERY_VALIDATION_GENERIC_ERROR,
    BIGQUERY_VALIDATION_PERMISSION_DENIED_ERROR,
    BigQueryAuthResolutionError,
    BigQueryCredentialsRejectedError,
    BigQueryDatasetNotFoundError,
    BigQueryImplementation,
    BigQueryInvalidIdentifierError,
    BigQueryInvalidTokenUriError,
    BigQueryJobTimeoutError,
    BigQueryReadTimeoutError,
    BigQueryTokenRefreshError,
    _bq_select_clause,
    _get_primary_keys_for_table,
    _get_query,
    _get_rows_to_sync,
    _has_duplicate_primary_keys,
    _pages_with_idle_timeout,
    _resolve_region,
    _run_destination_query_with_job_retry,
    delete_all_temp_destination_tables,
    resolve_bigquery_auth,
    validate_bigquery_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.bigquery.source import BigQuerySource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import error_message_matches
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.identifiers import (
    InvalidIdentifierError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.predicates import (
    ColumnTypeCategory,
    ValidatedRowFilter,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.bigquery import (
    BigQueryAuthTypeConfig,
    BigQueryAuthTypeConfigKeyFileConfig,
    BigQueryDatasetProjectConfig,
    BigQuerySourceConfig,
    BigQueryTemporaryDatasetConfig,
    BigQueryUseCustomRegionConfig,
)
from products.warehouse_sources.backend.types import IncrementalFieldType


@pytest.fixture(autouse=True)
def _stub_google_credential_construction():
    """The test key files carry placeholder private keys, which google-auth rejects as malformed PEM.

    Turning a key file into credentials is google-auth's job, not the source's, so stub it and let
    each test exercise the source's own wiring. Tests that assert on credential construction patch
    over this themselves.
    """
    with mock.patch.object(
        bq_module.service_account.Credentials,
        "from_service_account_info",
        side_effect=lambda info, scopes=None: mock.MagicMock(spec=GoogleAuthCredentials),
    ):
        yield


def _make_inputs(**overrides) -> SourceInputs:
    defaults: dict = {
        "schema_name": "schema",
        "schema_id": "schema-id",
        "source_id": "source-id",
        "team_id": 1,
        "should_use_incremental_field": False,
        "db_incremental_field_last_value": None,
        "db_incremental_field_earliest_value": None,
        "incremental_field": None,
        "incremental_field_type": None,
        "job_id": "job-id",
        "logger": mock.MagicMock(),
        "reset_pipeline": False,
    }
    defaults.update(overrides)
    return SourceInputs(**defaults)


def _key_file(**overrides) -> BigQueryAuthTypeConfigKeyFileConfig:
    fields: dict[str, str] = {
        "project_id": "project-id",
        "private_key": "private-key",
        "private_key_id": "private-key-id",
        "client_email": "client-email",
        "token_uri": "https://oauth2.googleapis.com/token",
    }
    fields.update(overrides)
    return BigQueryAuthTypeConfigKeyFileConfig(**fields)


def _key_file_auth(**overrides) -> BigQueryAuthTypeConfig:
    return BigQueryAuthTypeConfig(selection="key_file", key_file=_key_file(**overrides))


def _integration_auth(integration_id: int) -> BigQueryAuthTypeConfig:
    return BigQueryAuthTypeConfig(
        selection="service_account", google_cloud_service_account_integration_id=integration_id
    )


def _make_config(
    *,
    project_id: str = "project-id",
    dataset_id: str = "dataset-id",
    dataset_project: BigQueryDatasetProjectConfig | None = None,
    temporary_dataset: BigQueryTemporaryDatasetConfig | None = None,
    use_custom_region: BigQueryUseCustomRegionConfig | None = None,
) -> BigQuerySourceConfig:
    return BigQuerySourceConfig(
        auth_type=_key_file_auth(project_id=project_id),
        dataset_id=dataset_id,
        dataset_project=dataset_project,
        temporary_dataset=temporary_dataset,
        use_custom_region=use_custom_region,
    )


def test_bigquery_get_columns_filters_existing_destination_tables():
    """`get_columns` strips `__posthog_import_*` tables before returning."""
    fake_client = mock.MagicMock()
    fake_row_keep = mock.MagicMock(table_name="table", column_name="c", data_type="STRING", is_nullable="NO")
    fake_row_skip = mock.MagicMock(
        table_name="__posthog_import_0000_0000", column_name="c", data_type="STRING", is_nullable="NO"
    )
    fake_client.query.return_value.result.return_value = [fake_row_keep, fake_row_skip]

    columns = BigQueryImplementation().get_columns(fake_client, _make_config(), names=None)
    assert list(columns.keys()) == ["table"]


def test_bigquery_get_columns_returns_empty_when_job_create_forbidden():
    """A service account without `bigquery.jobs.create` raises `Forbidden` from
    `client.query()` (which eagerly creates the job), not from `result()`. That must
    degrade to no schemas rather than crashing schema discovery."""
    fake_client = mock.MagicMock()
    fake_client.query.side_effect = Forbidden(
        "Access Denied: Project p: User does not have bigquery.jobs.create permission in project p."
    )

    columns = BigQueryImplementation().get_columns(fake_client, _make_config(), names=None)
    assert columns == {}


@pytest.mark.parametrize(
    "error_message,expected_type,is_token_refresh",
    [
        # A bad OAuth token endpoint makes google-auth raise this opaque `TypeError` during the
        # lazy token refresh — `get_columns` must surface a clear, non-retryable error instead.
        ("string indices must be integers, not 'str'", BigQueryTokenRefreshError, True),
        # Any other `TypeError` indicates a genuine bug and must propagate unchanged.
        ("unrelated bug", TypeError, False),
    ],
)
def test_bigquery_get_columns_typeerror_handling(error_message, expected_type, is_token_refresh):
    """Token-refresh `TypeError`s are wrapped as `BigQueryTokenRefreshError`; others propagate."""
    fake_client = mock.MagicMock()
    fake_client.query.side_effect = TypeError(error_message)

    with pytest.raises(expected_type) as exc_info:
        BigQueryImplementation().get_columns(fake_client, _make_config(), names=None)

    assert isinstance(exc_info.value, BigQueryTokenRefreshError) == is_token_refresh
    if is_token_refresh:
        # The raised message must carry the stable marker registered as non-retryable.
        assert BIGQUERY_TOKEN_RESPONSE_ERROR in str(exc_info.value)
        assert BIGQUERY_TOKEN_RESPONSE_ERROR in BigQuerySource().get_non_retryable_errors()
    else:
        assert error_message in str(exc_info.value)


def test_bigquery_get_columns_raises_friendly_error_when_dataset_not_found():
    """A missing dataset/table surfaces as a raw google `NotFound` from `client.query()`. Schema
    discovery must re-raise it with actionable wording instead of leaking BigQuery job internals,
    and that wording must stay registered as non-retryable."""
    fake_client = mock.MagicMock()
    fake_client.query.side_effect = NotFound(
        "404 Not found: Dataset prj:ds was not found in location US Job ID: b3abc342-16a7"
    )

    with pytest.raises(BigQueryDatasetNotFoundError) as exc_info:
        BigQueryImplementation().get_columns(fake_client, _make_config(), names=None)

    assert str(exc_info.value) == BIGQUERY_DATASET_NOT_FOUND_ERROR
    # The raw 404 (job id, location internals) must not survive into the message.
    assert "Job ID" not in str(exc_info.value)
    assert BIGQUERY_DATASET_NOT_FOUND_ERROR in BigQuerySource().get_non_retryable_errors()


@pytest.mark.parametrize(
    "phrase", ['Invalid dataset ID "(default)"', 'Invalid project ID "bad id"', "ProjectId must be non-empty"]
)
def test_bigquery_get_columns_raises_friendly_error_for_invalid_identifier(phrase):
    """A syntactically invalid project/dataset ID surfaces as a raw 400 `BadRequest` from
    `client.query()`. Schema discovery must re-raise it with actionable wording instead of leaking
    the offending value and BigQuery job internals, and that wording must stay non-retryable."""
    fake_client = mock.MagicMock()
    fake_client.query.side_effect = BadRequest(
        f"400 {phrase}. Dataset IDs must be alphanumeric. Location: US Job ID: f2bf3ba8-4c4b"
    )

    with pytest.raises(BigQueryInvalidIdentifierError) as exc_info:
        BigQueryImplementation().get_columns(fake_client, _make_config(), names=None)

    assert str(exc_info.value) == BIGQUERY_INVALID_IDENTIFIER_ERROR
    # The raw 400 (offending id, job id) must not survive into the message.
    assert "Job ID" not in str(exc_info.value)
    assert "(default)" not in str(exc_info.value)
    assert BIGQUERY_INVALID_IDENTIFIER_ERROR in BigQuerySource().get_non_retryable_errors()


def test_bigquery_get_columns_propagates_unrelated_bad_request():
    """A BadRequest that isn't an invalid-identifier error (e.g. a malformed query) must propagate
    unchanged rather than being mislabeled as an invalid project/dataset ID."""
    fake_client = mock.MagicMock()
    fake_client.query.side_effect = BadRequest("400 Syntax error: Unexpected keyword SELECT")

    with pytest.raises(BadRequest):
        BigQueryImplementation().get_columns(fake_client, _make_config(), names=None)


@pytest.mark.parametrize(
    "error_message,expected_type,is_rejected",
    [
        # An `invalid_grant` RefreshError means Google rejected the service-account grant (rotated
        # key, deleted account). `get_columns` must surface a clear message instead of the tuple repr.
        (
            "('invalid_grant: Invalid JWT Signature.', {'error': 'invalid_grant', 'error_description': 'Invalid JWT Signature.'})",
            BigQueryCredentialsRejectedError,
            True,
        ),
        # Transient/other RefreshErrors carry their own diagnoses and must propagate unchanged.
        ("('Failed to retrieve token', {'error': 'internal_failure'})", RefreshError, False),
    ],
)
def test_bigquery_get_columns_refresh_error_handling(error_message, expected_type, is_rejected):
    """`invalid_grant` RefreshErrors are wrapped as `BigQueryCredentialsRejectedError`; others propagate."""
    fake_client = mock.MagicMock()
    fake_client.query.side_effect = RefreshError(error_message)

    with pytest.raises(expected_type) as exc_info:
        BigQueryImplementation().get_columns(fake_client, _make_config(), names=None)

    assert isinstance(exc_info.value, BigQueryCredentialsRejectedError) == is_rejected
    if is_rejected:
        # The wizard shows this str() directly, and it must keep the `invalid_grant` marker so the
        # sync schema-discovery path still recognises it as non-retryable.
        assert "invalid_grant" in str(exc_info.value)
        assert "rejected by Google" in str(exc_info.value)
        assert any(key in str(exc_info.value) for key in BigQuerySource().get_non_retryable_errors())


@pytest.mark.parametrize(
    "dataset_project,temporary_dataset,expected_dataset_project_id,expected_destination_dataset_id",
    [
        # default — no dataset_project, no temporary_dataset
        (None, None, None, "dataset-id"),
        # dataset_project enabled — propagated through both delete_all and _build_source_response
        (
            BigQueryDatasetProjectConfig(dataset_project_id="other-project-id", enabled=True),
            None,
            "other-project-id",
            "dataset-id",
        ),
        # temporary_dataset enabled — overrides destination_table_dataset_id
        (
            None,
            BigQueryTemporaryDatasetConfig(temporary_dataset_id="some-other-dataset-id", enabled=True),
            None,
            "some-other-dataset-id",
        ),
        # both set — temporary_dataset wins for destination, dataset_project still resolved
        (
            BigQueryDatasetProjectConfig(dataset_project_id="other-project-id", enabled=True),
            BigQueryTemporaryDatasetConfig(temporary_dataset_id="some-other-dataset-id", enabled=True),
            "other-project-id",
            "some-other-dataset-id",
        ),
    ],
)
def test_bigquery_build_pipeline_resolves_dataset_routing(
    dataset_project, temporary_dataset, expected_dataset_project_id, expected_destination_dataset_id
):
    config = _make_config(dataset_project=dataset_project, temporary_dataset=temporary_dataset)
    expected_table_id = (
        f"project-id.{expected_destination_dataset_id}.__posthog_import_schema_id_job_id_"
        f"{str(parser.parse('2025-01-01T12:00:00.000Z').timestamp()).replace('.', '')}"
    )

    with (
        time_machine.travel("2025-01-01T12:00:00.000Z", tick=False),
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.bigquery.bigquery.delete_all_temp_destination_tables",
        ) as mock_delete_all,
        mock.patch.object(
            BigQueryImplementation, "_build_source_response", return_value=mock.MagicMock()
        ) as mock_build,
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.bigquery.bigquery.delete_table",
        ) as mock_delete,
    ):
        BigQuerySource().source_for_pipeline(config, _make_inputs())

    assert mock_delete_all.call_args.kwargs["dataset_id"] == expected_destination_dataset_id
    assert mock_delete_all.call_args.kwargs["dataset_project_id"] == expected_dataset_project_id
    assert mock_delete_all.call_args.kwargs["table_prefix"] == "__posthog_import_schema_id"

    assert mock_build.call_args.kwargs["dataset_project_id"] == expected_dataset_project_id
    assert mock_build.call_args.kwargs["bq_destination_table_id"] == expected_table_id

    assert mock_delete.call_args.kwargs["table_id"] == expected_table_id


@pytest.mark.parametrize(
    "exception",
    [
        # A transient token-refresh failure (e.g. a 502 from Google's OAuth endpoint).
        RefreshError("<!DOCTYPE html><html><head><title>Error 502 (Server Error)</title></head></html>"),
        # The customer's whole GCP project was deleted after the sync started — there's no
        # readable copy left to protect, unlike a live-project "Access Denied:" permission denial.
        Forbidden(
            "DELETE https://bigquery.googleapis.com/bigquery/v2/projects/proj/datasets/ds/tables/tbl"
            "?prettyPrint=false: Project #123456789 has been deleted."
        ),
    ],
)
def test_bigquery_build_pipeline_swallows_transient_cleanup_errors(exception):
    """A transient failure while deleting the run's own destination table must not turn an
    otherwise-successful sync into a failure — retrying the whole sync just to retry this delete
    is wasteful."""
    config = _make_config()
    logger = mock.MagicMock()
    inputs = _make_inputs(logger=logger)
    build_result = mock.MagicMock()

    with (
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.bigquery.bigquery.delete_all_temp_destination_tables",
        ),
        mock.patch.object(BigQueryImplementation, "_build_source_response", return_value=build_result),
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.bigquery.bigquery.delete_table",
            side_effect=exception,
        ),
    ):
        result = BigQuerySource().source_for_pipeline(config, inputs)

    assert result is build_result
    logger.warning.assert_called_once()


@pytest.mark.parametrize(
    "exception",
    [
        # A genuine permission denial must keep propagating: this table holds a real materialized
        # copy of the customer's data, so swallowing it here would let readable copies accumulate
        # on every run instead of the sync failing via the "Access Denied:" non-retryable key.
        Forbidden("Access Denied: Permission bigquery.tables.delete denied on table"),
        # `invalid_grant` (rejected credentials) is not transient and must reach the sync-path
        # classifier rather than being silently swallowed as a routine refresh hiccup.
        RefreshError(("invalid_grant: Invalid JWT Signature.", {"error": "invalid_grant"})),
        RuntimeError("boom"),
    ],
)
def test_bigquery_build_pipeline_propagates_unexpected_cleanup_errors(exception):
    """Only a transient (non-`invalid_grant`) `RefreshError` is treated as best-effort during
    destination-table cleanup — anything else, including permission denials and rejected
    credentials, must still surface."""
    config = _make_config()
    inputs = _make_inputs()

    with (
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.bigquery.bigquery.delete_all_temp_destination_tables",
        ),
        mock.patch.object(BigQueryImplementation, "_build_source_response", return_value=mock.MagicMock()),
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.bigquery.bigquery.delete_table",
            side_effect=exception,
        ),
        pytest.raises(type(exception)),
    ):
        BigQuerySource().source_for_pipeline(config, inputs)


def test_bigquery_get_query_projects_enabled_columns():
    bq_table = mock.MagicMock(dataset_id="ds", table_id="t")
    query, params = _get_query(
        should_use_incremental_field=False,
        db_incremental_field_last_value=None,
        bq_table=bq_table,
        enabled_columns=["email"],
        primary_keys=["id"],
    )
    assert "SELECT `email`, `id` FROM" in query
    assert params == []


def test_bigquery_get_query_binds_row_filters_as_parameters():
    bq_table = mock.MagicMock(dataset_id="ds", table_id="t")
    bq_table.schema = [
        SimpleNamespace(name="age", field_type="INTEGER"),
        SimpleNamespace(name="name", field_type="STRING"),
    ]
    query, params = _get_query(
        should_use_incremental_field=False,
        db_incremental_field_last_value=None,
        bq_table=bq_table,
        row_filters=[
            ValidatedRowFilter(column="age", operator=">", value=21, category=ColumnTypeCategory.INTEGER),
            ValidatedRowFilter(
                column="name", operator="=", value="x'; DROP TABLE y; --", category=ColumnTypeCategory.STRING
            ),
        ],
    )
    # Values are bound as @params, never inlined.
    assert "WHERE `age` > @row_filter_0 AND `name` = @row_filter_1" in query
    assert "DROP TABLE" not in query
    assert [(p.name, p.type_, p.value) for p in params] == [
        ("row_filter_0", "INT64", 21),
        ("row_filter_1", "STRING", "x'; DROP TABLE y; --"),
    ]


@mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.bigquery.bigquery.time.sleep")
def test_bigquery_get_rows_to_sync_retries_transient_job_not_found(mock_sleep):
    # The COUNT query hits BigQuery's job-metadata race; it must be retried and yield the real
    # count, not swallowed into the catch-all that returns 0 and captures error-tracking noise.
    table = mock.MagicMock(project="proj", dataset_id="ds", table_id="t")
    table.schema = [SimpleNamespace(name="age", field_type="INTEGER")]
    client = mock.MagicMock()
    job = mock.MagicMock()
    job.result.side_effect = [NotFound("404 Not found: Job proj:US.job_abc123"), iter([[123]])]
    client.query.return_value = job

    with mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.bigquery.bigquery.capture_exception"
    ) as mock_capture:
        result = _get_rows_to_sync(
            table=table,
            client=client,
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
            logger=mock.MagicMock(),
            row_filters=[
                ValidatedRowFilter(column="age", operator="IN", value=[21, 30], category=ColumnTypeCategory.INTEGER)
            ],
        )

    assert result == 123
    assert client.query.call_count == 2
    mock_sleep.assert_called_once()
    mock_capture.assert_not_called()


def test_bigquery_get_rows_to_sync_skips_capture_when_table_missing():
    # A table deleted/renamed after schema discovery (or absent from the queried region) makes the
    # COUNT query raise a terminal NotFound. The main read path already surfaces this non-retryably,
    # so the best-effort probe must fall back to 0 without capturing error-tracking noise.
    table = mock.MagicMock(project="proj", dataset_id="ds", table_id="t")
    table.schema = [SimpleNamespace(name="age", field_type="INTEGER")]
    client = mock.MagicMock()
    job = mock.MagicMock()
    job.result.side_effect = NotFound("404 Not found: Table proj:ds.t was not found in location EU")
    client.query.return_value = job

    with mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.bigquery.bigquery.capture_exception"
    ) as mock_capture:
        result = _get_rows_to_sync(
            table=table,
            client=client,
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
            logger=mock.MagicMock(),
            row_filters=[
                ValidatedRowFilter(column="age", operator="IN", value=[21, 30], category=ColumnTypeCategory.INTEGER)
            ],
        )

    assert result == 0
    mock_capture.assert_not_called()


def test_bigquery_get_rows_to_sync_captures_unexpected_error():
    # A NotFound is only skipped for the missing-table/region wording; an unrelated failure must
    # still be captured so genuine bugs stay visible.
    table = mock.MagicMock(project="proj", dataset_id="ds", table_id="t")
    table.schema = [SimpleNamespace(name="age", field_type="INTEGER")]
    client = mock.MagicMock()
    job = mock.MagicMock()
    job.result.side_effect = ValueError("something unexpected")
    client.query.return_value = job

    with mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.bigquery.bigquery.capture_exception"
    ) as mock_capture:
        result = _get_rows_to_sync(
            table=table,
            client=client,
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
            logger=mock.MagicMock(),
            row_filters=[
                ValidatedRowFilter(column="age", operator="IN", value=[21, 30], category=ColumnTypeCategory.INTEGER)
            ],
        )

    assert result == 0
    mock_capture.assert_called_once()


@pytest.mark.parametrize(
    "field_type,column_bq_type,last_value,expected_clause,offset_present",
    [
        # DATETIME columns are timezone-naive — a tz-aware literal can't be cast and BigQuery rejects it
        # with "Could not cast literal ... to type DATETIME". On the first incremental sync the cursor
        # defaults to the 1970-01-01 UTC initial value, whose isoformat carries a '+00:00' offset; for a
        # DATETIME field the literal must be naive.
        (IncrementalFieldType.DateTime, "DATETIME", None, "WHERE `cursor` > '1970-01-01T00:00:00'", False),
        # A tz-aware value carried over from a previous sync is also rendered naive for DATETIME fields.
        (
            IncrementalFieldType.DateTime,
            "DATETIME",
            parser.parse("2024-03-11T09:26:04+00:00"),
            "WHERE `cursor` > '2024-03-11T09:26:04'",
            False,
        ),
        # TIMESTAMP columns are timezone-aware, so the offset must be preserved in the literal.
        (IncrementalFieldType.Timestamp, "TIMESTAMP", None, "WHERE `cursor` > '1970-01-01T00:00:00+00:00'", True),
    ],
)
def test_bigquery_get_query_datetime_cursor_timezone_offset(
    field_type, column_bq_type, last_value, expected_clause, offset_present
):
    bq_table = mock.MagicMock(dataset_id="ds", table_id="t")
    bq_table.schema = [SimpleNamespace(name="cursor", field_type=column_bq_type)]
    sql, _ = _get_query(
        should_use_incremental_field=True,
        db_incremental_field_last_value=last_value,
        bq_table=bq_table,
        incremental_field="cursor",
        incremental_field_type=field_type,
    )
    assert expected_clause in sql
    assert ("+00:00" in sql) is offset_present


@pytest.mark.parametrize(
    "field_type,last_value,expected_clause",
    [
        (IncrementalFieldType.DateTime, None, "WHERE `cursor` > '1970-01-01'"),
        (IncrementalFieldType.Timestamp, None, "WHERE `cursor` > '1970-01-01'"),
        (
            IncrementalFieldType.DateTime,
            parser.parse("2024-03-11T09:26:04+00:00"),
            "WHERE `cursor` > '2024-03-11'",
        ),
    ],
)
def test_bigquery_get_query_date_column_with_datetime_cursor(field_type, last_value, expected_clause):
    # A column retyped to DATE in BigQuery after discovery still carries a DateTime/Timestamp cursor
    # here, whose datetime-shaped literal ("1970-01-01T00:00:00") BigQuery refuses to cast to DATE
    # ("Could not cast literal ... to type DATE"). The literal must follow the column's live type.
    bq_table = mock.MagicMock(dataset_id="ds", table_id="t")
    bq_table.schema = [SimpleNamespace(name="cursor", field_type="DATE")]
    sql, _ = _get_query(
        should_use_incremental_field=True,
        db_incremental_field_last_value=last_value,
        bq_table=bq_table,
        incremental_field="cursor",
        incremental_field_type=field_type,
    )
    assert expected_clause in sql
    assert "T00:00:00" not in sql
    assert "+00:00" not in sql


@pytest.mark.parametrize(
    "malicious_column",
    [
        "x` FROM `other.private` --",
        "id; DROP TABLE customers",
        "email`, `secret",
        "name with space",
        "col\x00null",
    ],
)
def test_bigquery_select_clause_rejects_injection_attempts(malicious_column):
    """`enabled_columns` flows from user config — must be allowlisted before backtick quoting."""
    with pytest.raises(InvalidIdentifierError):
        _bq_select_clause([malicious_column], primary_keys=None, incremental_field=None)


@pytest.mark.parametrize(
    "observed_error",
    [
        # Rotated/revoked service account private key.
        "('invalid_grant: Invalid JWT Signature.', {'error': 'invalid_grant', 'error_description': 'Invalid JWT Signature.'})",
        # Deleted service account.
        "('invalid_grant: Invalid grant: account not found', {'error': 'invalid_grant', 'error_description': 'Invalid grant: account not found'})",
    ],
)
def test_non_retryable_errors_match_rejected_credentials(observed_error):
    """A `RefreshError` carrying the OAuth2 `invalid_grant` code means Google rejected the
    service account grant — retrying can't recover, so the sync must be disabled."""
    non_retryable_errors = BigQuerySource().get_non_retryable_errors()
    assert any(key in observed_error for key in non_retryable_errors)


@pytest.mark.parametrize(
    "observed_error",
    [
        # token_uri pointed at the cloud metadata endpoint — PostHog's egress proxy denies it.
        "RefreshError: Egress proxying is denied to host '169.254.169.254': no valid IP found "
        "among resolved addresses - 169.254.169.254 denied by rule 'Deny: Not Global Unicast'. .",
        # Different denied host — the match must not rely on the volatile host/IP.
        "RefreshError: Egress proxying is denied to host '10.0.0.5': no valid IP found "
        "among resolved addresses - 10.0.0.5 denied by rule 'Deny: Not Global Unicast'. .",
    ],
)
def test_non_retryable_errors_match_egress_denied_token_uri_endpoint(observed_error):
    """A service account whose `token_uri` points at a non-globally-routable address (e.g. a
    cloud metadata endpoint) makes our egress proxy deny the request, and google-auth surfaces
    that denial as a `RefreshError` — a misconfigured key the user must fix, so the sync must be
    disabled rather than retried forever."""
    non_retryable_errors = BigQuerySource().get_non_retryable_errors()
    matching = [key for key in non_retryable_errors if key in observed_error]
    assert matching, "Egress-denied token_uri endpoint error should be recognised as non-retryable"
    assert all(non_retryable_errors[key] is not None for key in matching)


@pytest.mark.parametrize(
    "observed_error",
    [
        # Corrupted/truncated private key body in the uploaded service account JSON.
        "Unable to load PEM file. See https://cryptography.io/en/latest/faq/#why-can-t-i-import-my-pem-file for more details. InvalidData(InvalidPadding)",
        "ValueError: Unable to load PEM file. InvalidData(InvalidByte(1, 45))",
    ],
)
def test_bigquery_unparseable_private_key_is_non_retryable(observed_error):
    non_retryable_errors = BigQuerySource().get_non_retryable_errors()
    matching = [key for key in non_retryable_errors if key in observed_error]
    assert matching, "Unparseable private key error should be recognised as non-retryable"
    assert all(non_retryable_errors[key] is not None for key in matching)


def _run_delete_all_temp_destination_tables(side_effect, logger):
    bq = mock.MagicMock()
    bq.list_tables.side_effect = side_effect
    client_cm = mock.MagicMock()
    client_cm.__enter__.return_value = bq

    with (
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.bigquery.bigquery.bigquery_client",
            return_value=client_cm,
        ),
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.bigquery.bigquery.capture_exception"
        ) as mock_capture,
    ):
        delete_all_temp_destination_tables(
            dataset_id="dataset-id",
            table_prefix="prefix_",
            project_id="project-id",
            location=None,
            dataset_project_id=None,
            credentials=mock.MagicMock(spec=GoogleAuthCredentials),
            logger=logger,
        )
    return mock_capture


@pytest.mark.parametrize(
    "exception",
    [
        Forbidden("Access Denied: Permission bigquery.tables.list denied on dataset"),
        NotFound("Dataset not found (or it may not exist)"),
        RefreshError(("invalid_grant: Invalid JWT Signature.", {"error": "invalid_grant"})),
        BadRequest(
            "GET https://bigquery.googleapis.com/bigquery/v2/projects/my-project.my_dataset/datasets/"
            "my-project.my_dataset/tables?prettyPrint=false: Invalid resource name "
            "projects/my-project.my_dataset; Project id: my-project.my_dataset"
        ),
    ],
)
def test_delete_all_temp_destination_tables_swallows_expected_errors_quietly(exception):
    """Lost permissions, a deleted dataset, rejected credentials, or a malformed project/dataset ID
    during best-effort cleanup must NOT be captured to error tracking — it's expected and fires on
    every sync otherwise."""
    logger = mock.MagicMock()

    mock_capture = _run_delete_all_temp_destination_tables(exception, logger)

    mock_capture.assert_not_called()
    logger.warning.assert_called_once()


def test_delete_all_temp_destination_tables_captures_unexpected_errors():
    """Genuinely unexpected errors are still captured so we don't lose visibility."""
    logger = mock.MagicMock()

    mock_capture = _run_delete_all_temp_destination_tables(RuntimeError("boom"), logger)

    mock_capture.assert_called_once()


# Regression: a stray leading/trailing space in a hand-entered project or dataset ID made
# every BigQuery request fail with an opaque `BadRequest: Invalid project ID ' ...'` /
# `Invalid dataset ID ' ...'`. The identifiers must be trimmed before reaching BigQuery.


def test_bigquery_resolve_region_trims_and_treats_whitespace_as_unset():
    assert (
        _resolve_region(_make_config(dataset_project=None)) is None  # no custom region configured
    )

    config = _make_config()
    config.use_custom_region = BigQueryUseCustomRegionConfig(region="  us-east1 ", enabled=True)
    assert _resolve_region(config) == "us-east1"

    config.use_custom_region = BigQueryUseCustomRegionConfig(region="   ", enabled=True)
    assert _resolve_region(config) is None


# Regression: credentials validate with a region-agnostic `list_tables`, but a discovery query
# job created without a location defaults to the US multi-region — so a dataset in another region
# passed validation yet failed schema discovery with "... was not found in location US". `connect`
# auto-resolves the dataset's real location so discovery runs where the data lives.


def _patch_bigquery_client(fake_bq):
    client_cm = mock.MagicMock()
    client_cm.__enter__.return_value = fake_bq
    return mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.bigquery.bigquery.bigquery_client",
        return_value=client_cm,
    )


def test_connect_falls_back_to_unset_location_when_detection_fails():
    """If the dataset-location probe fails (e.g. the dataset really doesn't exist), connect leaves
    the location unset so `get_columns` still surfaces the actionable not-found error."""
    fake_bq = mock.MagicMock()
    fake_bq.get_dataset.side_effect = NotFound("Not found: Dataset prj:ds")

    with _patch_bigquery_client(fake_bq) as mock_client:
        with BigQueryImplementation().connect(_make_config()):
            pass

    assert mock_client.call_args_list[-1][0][1] is None


@pytest.mark.parametrize("method_name", ["get_primary_keys", "get_leading_index_columns"])
def test_bigquery_discovery_qualifies_information_schema_with_dataset_project(method_name):
    """`get_primary_keys` and `get_leading_index_columns` share the same unqualified-reference
    defect as `get_columns`, but swallow the error and silently lose PK/index detection. Their
    INFORMATION_SCHEMA references must carry the dataset project too."""
    config = _make_config(
        project_id="service-account-project",
        dataset_id="posthog_export",
        dataset_project=BigQueryDatasetProjectConfig(dataset_project_id="dataset-project", enabled=True),
    )

    fake_client = mock.MagicMock()
    fake_client.query.return_value.result.return_value = []

    getattr(BigQueryImplementation(), method_name)(fake_client, config, tables=["t"])

    sql = fake_client.query.call_args.args[0]
    assert "`dataset-project.posthog_export`.INFORMATION_SCHEMA" in sql
    assert fake_client.query.call_args.kwargs["project"] == "dataset-project"


def _config_with_key_file(**overrides) -> BigQuerySourceConfig:
    return BigQuerySourceConfig(auth_type=_key_file_auth(**overrides), dataset_id="my_dataset")


def test_bigquery_validate_credentials_missing_key_file_fields_reports_actionable_message():
    config = _config_with_key_file(private_key="")

    with mock.patch.object(bq_module, "bigquery_client") as mock_client:
        ok, message = BigQuerySource().validate_credentials(config, team_id=1)

    assert ok is False
    assert message == BIGQUERY_MISSING_KEY_FILE_FIELDS_ERROR
    # A malformed key file must be caught before we try to reach BigQuery.
    mock_client.assert_not_called()


@pytest.mark.parametrize(
    "auth_type",
    [
        BigQueryAuthTypeConfig(selection="service_account"),
        BigQueryAuthTypeConfig(selection="key_file"),
    ],
)
def test_bigquery_validate_credentials_without_the_selected_credential_reports_actionable_message(auth_type):
    """The credential under each option is optional on the form, so a source can reach validation
    having picked an authentication type without supplying its credential."""
    config = BigQuerySourceConfig(dataset_id="my_dataset", auth_type=auth_type)

    with mock.patch.object(bq_module, "bigquery_client") as mock_client:
        ok, message = BigQuerySource().validate_credentials(config, team_id=1)

    assert (ok, message) == (False, BIGQUERY_NO_CREDENTIALS_ERROR)
    mock_client.assert_not_called()


_NON_GOOGLE_TOKEN_URIS = [
    "https://attacker.example.com/relay",
    "http://oauth2.googleapis.com/token",
    "https://oauth2.googleapis.com.example.com/token",
    "http://169.254.169.254/latest/meta-data/",
]


@pytest.mark.parametrize(
    "token_uri",
    ["https://oauth2.googleapis.com/token", "https://accounts.google.com/o/oauth2/token"],
)
def test_bigquery_validate_credentials_accepts_both_google_token_endpoints(token_uri):
    config = _config_with_key_file(token_uri=token_uri)

    with (
        mock.patch.object(bq_module, "bigquery_client"),
        mock.patch.object(bq_module.service_account.Credentials, "from_service_account_info") as mock_creds,
    ):
        ok, message = BigQuerySource().validate_credentials(config, team_id=1)

    assert (ok, message) == (True, None)
    assert mock_creds.call_args.args[0]["token_uri"] == token_uri


@pytest.mark.parametrize("token_uri", _NON_GOOGLE_TOKEN_URIS)
def test_bigquery_rejects_non_google_token_uri_before_building_credentials(token_uri):
    """`token_uri` decides where a worker posts the service-account grant, so a hand-edited one must
    be refused before google-auth is handed the key at all."""
    config = _config_with_key_file(token_uri=token_uri)

    with mock.patch.object(bq_module.service_account.Credentials, "from_service_account_info") as mock_creds:
        with pytest.raises(BigQueryInvalidTokenUriError) as exc_info:
            resolve_bigquery_auth(config, team_id=1)

        mock_creds.assert_not_called()
        ok, message = BigQuerySource().validate_credentials(config, team_id=1)

    assert (ok, message) == (False, BIGQUERY_INVALID_TOKEN_URI_ERROR)
    assert str(exc_info.value) in BigQuerySource().get_non_retryable_errors()


@pytest.mark.parametrize(
    "exception,expected_message,should_capture",
    [
        (
            ValueError("Unable to load PEM file. ... InvalidData(InvalidPadding)"),
            BIGQUERY_INVALID_KEY_FILE_ERROR,
            False,
        ),
        (RefreshError("('invalid_grant: Invalid JWT Signature.', {})"), BIGQUERY_CREDENTIALS_REJECTED_ERROR, False),
        (
            RefreshError(
                "('Unable to acquire impersonated credentials', "
                '\'{"error": {"code": 403, "message": "Permission \\\'iam.serviceAccounts.getAccessToken\\\' '
                'denied on resource (or it may not exist).", "status": "PERMISSION_DENIED"}}\')'
            ),
            BIGQUERY_IMPERSONATION_PERMISSION_ERROR,
            False,
        ),
        (
            # Names the permission without denying it, so it must not match the check above and
            # should fall through to the generic (captured) branch.
            RefreshError("('Unable to acquire impersonated credentials', 'iam.serviceAccounts.getAccessToken')"),
            BIGQUERY_VALIDATION_GENERIC_ERROR,
            True,
        ),
        (BadRequest('Invalid dataset ID "(default)"'), BIGQUERY_INVALID_IDENTIFIER_ERROR, False),
        (BadRequest("400 ProjectId must be non-empty"), BIGQUERY_INVALID_IDENTIFIER_ERROR, False),
        (
            BadRequest(
                "GET https://bigquery.googleapis.com/bigquery/v2/projects/my-project.my_dataset/datasets/"
                "my-project.my_dataset/tables?prettyPrint=false: Invalid resource name "
                "projects/my-project.my_dataset; Project id: my-project.my_dataset"
            ),
            BIGQUERY_INVALID_IDENTIFIER_ERROR,
            False,
        ),
        (
            NotFound("404 Not found: Dataset my-project:my_dataset was not found in location US"),
            BIGQUERY_DATASET_NOT_FOUND_ERROR,
            False,
        ),
        (
            Forbidden("403 Access Denied: Table my-project:my_dataset.t"),
            BIGQUERY_VALIDATION_PERMISSION_DENIED_ERROR,
            False,
        ),
        (RuntimeError("something unexpected"), BIGQUERY_VALIDATION_GENERIC_ERROR, True),
    ],
)
def test_bigquery_validate_credentials_maps_failures_to_actionable_messages(
    exception, expected_message, should_capture
):
    # Validation consumes the first page of `list_tables`, and that page fetch is where the request
    # actually runs, so surface each failure from page consumption — the real request site. This
    # also guards the regression: an inert validation that never consumes a page would return
    # `(True, None)` and fail these assertions.
    bq = mock.MagicMock()
    bq.list_tables.return_value.pages.__next__.side_effect = exception
    client_cm = mock.MagicMock()
    client_cm.__enter__.return_value = bq

    with (
        mock.patch.object(bq_module, "bigquery_client", return_value=client_cm),
        mock.patch.object(bq_module, "capture_exception") as mock_capture,
    ):
        ok, message = validate_bigquery_credentials(
            dataset_id="my_dataset",
            project_id="my-project",
            credentials=mock.MagicMock(spec=GoogleAuthCredentials),
            dataset_project_id=None,
            location=None,
        )

    assert ok is False
    assert message == expected_message
    # Expected user/config errors must not be reported to error tracking as noise; only genuinely
    # unexpected failures are captured.
    assert mock_capture.called is should_capture


@pytest.mark.parametrize(
    "use_custom_region,expected_region",
    [
        (None, None),
        (BigQueryUseCustomRegionConfig(enabled=False, region="europe-west2"), None),
        (BigQueryUseCustomRegionConfig(enabled=True, region=""), None),
        (BigQueryUseCustomRegionConfig(enabled=True, region="europe-west2"), "europe-west2"),
    ],
)
def test_bigquery_source_validate_credentials_wires_config_and_region(use_custom_region, expected_region):
    config = _make_config(use_custom_region=use_custom_region)

    with mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.bigquery.source.validate_bigquery_credentials",
        return_value=(True, None),
    ) as mock_validate:
        result = BigQuerySource().validate_credentials(config, team_id=1)

    assert result == (True, None)
    dataset_id, project_id, _credentials, dataset_project_id, region = mock_validate.call_args.args
    assert dataset_id == "dataset-id"
    assert project_id == "project-id"
    assert dataset_project_id is None
    # A custom region only flows through when the toggle is enabled and non-empty.
    assert region == expected_region


@pytest.mark.parametrize(
    "observed_error",
    [
        # Storage Read API permission failure — `str(PermissionDenied)` is "403 Access Denied: ..."
        str(
            PermissionDenied(
                "Access Denied: Table prj:ds.fct__conversions: Permission bigquery.tables.getData "
                "denied on table prj:ds.fct__conversions (or it may not exist)."
            )
        ),
        # Permission to list tables in a dataset is also denied with the same prefix
        str(Forbidden("Access Denied: Permission bigquery.tables.list denied on dataset prj:ds.")),
        # Storage Read API `create_read_session` denial — `str(PermissionDenied)` is "403 request
        # failed: the user does not have 'bigquery.readsessions.create' permission for 'projects/...'",
        # which the "Access Denied:" / "PermissionDenied: 403 request failed" keys don't cover.
        str(
            PermissionDenied(
                "request failed: the user does not have 'bigquery.readsessions.create' "
                "permission for 'projects/some-project'"
            )
        ),
        # Storage Read API stream-read denial — the session can be created but the account lacks
        # `bigquery.readsessions.getData`. `str(PermissionDenied)` is "there was an error operating
        # on '.../streams/...': the user does not have 'bigquery.readsessions.getData' permission for
        # '...'", which neither the "Access Denied:" / "403 request failed" nor the readsessions.create
        # keys cover.
        str(
            PermissionDenied(
                "there was an error operating on 'projects/some-project/locations/us/sessions/sess/"
                "streams/strm': the user does not have 'bigquery.readsessions.getData' permission for "
                "'projects/some-project/locations/us/sessions/sess/streams/strm'"
            )
        ),
    ],
)
def test_non_retryable_errors_match_permission_denied(observed_error):
    non_retryable_errors = BigQuerySource().get_non_retryable_errors()
    assert any(key in observed_error for key in non_retryable_errors)


@pytest.mark.parametrize(
    "observed_error,expected_key,expected_word",
    [
        # Overwriting a PostHog temp table — denied with bigquery.tables.update on the table.
        (
            str(
                Forbidden(
                    "Access Denied: Table prj:ds.__posthog_import_abc_123: Permission bigquery.tables.update "
                    "denied on table prj:ds.__posthog_import_abc_123 (or it may not exist)."
                )
            ),
            "bigquery.tables.update",
            "write access",
        ),
        # Creating a PostHog temp table — denied with bigquery.tables.create on the dataset.
        (
            str(
                Forbidden(
                    "Access Denied: Dataset prj:ds: Permission bigquery.tables.create denied on dataset "
                    "prj:ds (or it may not exist)."
                )
            ),
            "bigquery.tables.create",
            "create",
        ),
        # Querying a table/view that reads through a BigQuery connection (federated query or
        # BigLake) the service account isn't authorized to use — denied with
        # bigquery.connections.use on the connection resource, not the table/dataset.
        (
            str(
                Forbidden(
                    "Access Denied: Connection projects/proj/locations/us/connections/conn: User does not "
                    "have bigquery.connections.use permission for connection "
                    "projects/proj/locations/us/connections/conn."
                )
            ),
            "bigquery.connections.use",
            "connection",
        ),
    ],
)
def test_specific_permission_denial_outranks_generic_access_denied(observed_error, expected_key, expected_word):
    # Each of these denials also contains "Access Denied:", so both the generic key and the
    # more specific key match. external_data_job surfaces the first matching key's message, so the
    # specific key must sit above "Access Denied:" — otherwise the customer is told to grant table
    # read access to fix a failure that read access can't resolve.
    non_retryable_errors = BigQuerySource().get_non_retryable_errors()
    first_key, friendly = next((key, msg) for key, msg in non_retryable_errors.items() if key in observed_error)
    assert first_key == expected_key
    assert friendly is not None
    assert expected_word in friendly


@pytest.mark.parametrize(
    "observed_error",
    [
        # Federated table backed by a Cloud SQL PostgreSQL server — BigQuery wraps the upstream
        # ACL failure in a 400 BadRequest while reading query results.
        str(
            BadRequest(
                "GET https://bigquery.googleapis.com/bigquery/v2/projects/p/queries/j?maxResults=0"
                "&location=us-central1: Error while reading data, error message: Failed to fetch row "
                "from PostgreSQL server. Error: ERROR:  permission denied for table GroupParticipant"
            )
        ),
    ],
)
def test_non_retryable_errors_match_federated_upstream_permission_denied(observed_error):
    non_retryable_errors = BigQuerySource().get_non_retryable_errors()
    assert any(key in observed_error for key in non_retryable_errors)


@pytest.mark.parametrize(
    "observed_error",
    [
        # Administrator-set custom cost control on the customer's BigQuery project — surfaced as a
        # `Forbidden` whose str() is "403 Custom quota exceeded: ...".
        str(
            Forbidden(
                "Custom quota exceeded: Your usage exceeded the custom quota for QueryUsagePerDay, "
                "which is set by your administrator. For more information, see "
                "https://docs.cloud.google.com/bigquery/cost-controls.; reason: quotaExceeded"
            )
        ),
        # Per-user variant of the same custom cost control.
        str(
            Forbidden(
                "Custom quota exceeded: Your usage exceeded the custom quota for "
                "QueryUsagePerUserPerDay, which is set by your administrator.; reason: quotaExceeded"
            )
        ),
    ],
)
def test_non_retryable_errors_match_custom_quota_exceeded(observed_error):
    """An administrator-set custom cost control (e.g. QueryUsagePerDay) can't be recovered by
    retrying within the sync's window — the user must raise the quota or sync less data."""
    non_retryable_errors = BigQuerySource().get_non_retryable_errors()
    assert any(key in observed_error for key in non_retryable_errors)


def _run_has_duplicate_primary_keys(side_effect):
    table = mock.MagicMock()
    table.dataset_id = "dataset"
    table.table_id = "table"
    table.project = "project"

    client = mock.MagicMock()
    job = mock.MagicMock()
    job.result.side_effect = side_effect
    client.query.return_value = job

    with mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.bigquery.bigquery.capture_exception"
    ) as mock_capture:
        result = _has_duplicate_primary_keys(table, client, ["id"])
    return result, mock_capture


@pytest.mark.parametrize(
    "exception",
    [
        BadRequest(
            "Resources exceeded during query execution: The query could not be executed in the allotted memory."
        ),
        BadRequest("query failed", errors=[{"reason": "resourcesExceeded", "message": "out of memory"}]),
    ],
)
def test_has_duplicate_primary_keys_skips_resource_exceeded_quietly(exception):
    """A `resourcesExceeded` BigQuery error during the best-effort duplicate-key probe must NOT
    be captured to error tracking — it's a non-actionable data-volume limit that otherwise fires
    on every sync of a large table."""
    result, mock_capture = _run_has_duplicate_primary_keys(exception)

    assert result is False
    mock_capture.assert_not_called()


@pytest.mark.parametrize(
    "exception",
    [
        BadRequest(
            "Name is_qualified not found inside visit; failed to parse view 'my_dataset.my_view' at [5:19]; "
            "reason: invalidQuery, location: query, message: Name is_qualified not found inside visit; "
            "failed to parse view 'my_dataset.my_view' at [5:19]"
        ),
        BadRequest("Invalid table-valued function EXTERNAL_QUERY; failed to parse view 'my_dataset.my_view' at [1:1]"),
    ],
)
def test_has_duplicate_primary_keys_skips_view_parse_failure_quietly(exception):
    """A `failed to parse view` BigQuery error during the best-effort duplicate-key probe must NOT
    be captured to error tracking — the probed table is itself a broken view, a customer-side
    problem that otherwise fires on every sync of that table."""
    result, mock_capture = _run_has_duplicate_primary_keys(exception)

    assert result is False
    mock_capture.assert_not_called()


def test_has_duplicate_primary_keys_captures_unexpected_bad_request():
    """A non-resource BadRequest (e.g. a genuinely malformed probe query) is still captured so we
    don't lose visibility into real bugs."""
    result, mock_capture = _run_has_duplicate_primary_keys(BadRequest("Syntax error in query"))

    assert result is False
    mock_capture.assert_called_once()


def test_has_duplicate_primary_keys_captures_unexpected_errors():
    """Genuinely unexpected errors are still captured so we don't lose visibility."""
    result, mock_capture = _run_has_duplicate_primary_keys(RuntimeError("boom"))

    assert result is False
    mock_capture.assert_called_once()


def test_bigquery_query_create_retry_retries_queued_jobs_quota():
    """The queued-jobs quota is rejected at `jobs.insert`, which `job_retry` never wraps — only the
    `retry` on `client.query()` can wait it out — so the create retry must cover it while still
    leaving the administrator-set daily cost cap to surface non-retryably."""
    queued_jobs = Forbidden(
        "Quota exceeded: Your project_and_region exceeded quota for max number of jobs that can be "
        "queued per project. For more information, see https://cloud.google.com/bigquery/docs/troubleshoot-quotas"
    )
    custom_quota = Forbidden(
        "Custom quota exceeded: Your usage exceeded the custom quota for QueryUsagePerDay, "
        "which is set by your administrator.; reason: quotaExceeded"
    )
    assert BIGQUERY_QUERY_CREATE_RETRY._predicate(queued_jobs) is True
    assert BIGQUERY_QUERY_CREATE_RETRY._predicate(custom_quota) is False


@pytest.mark.parametrize(
    "exc",
    [
        # The observed transient: a dropped Storage Read stream surfaced as a gRPC INTERNAL. The
        # library default only reconnects on ServiceUnavailable, so this escaped and crashed the read.
        InternalServerError("Received RST_STREAM with error code 2"),
        ServiceUnavailable("503 The service is currently unavailable."),
    ],
)
def test_bigquery_read_rows_retry_reconnects_on_transient_stream_errors(exc):
    assert BIGQUERY_READ_ROWS_RETRY._predicate(exc) is True


@pytest.mark.parametrize(
    "exc",
    [
        # Deterministic failures must surface rather than reconnect forever.
        NotFound("404 Requested stream was not found."),
        BadRequest("400 request failed"),
    ],
)
def test_bigquery_read_rows_retry_does_not_reconnect_on_deterministic_errors(exc):
    assert BIGQUERY_READ_ROWS_RETRY._predicate(exc) is False


@pytest.mark.parametrize(
    "exc",
    [
        # The observed production failure: `create_read_session` itself returning a transient
        # gRPC INTERNAL before any stream exists. The library default only retries
        # DeadlineExceeded/ServiceUnavailable, so this escaped and crashed the import activity.
        InternalServerError("request failed: internal error"),
        ServiceUnavailable("503 The service is currently unavailable."),
        DeadlineExceeded("504 Deadline Exceeded"),
    ],
)
def test_bigquery_create_read_session_retry_retries_transient_errors(exc):
    assert BIGQUERY_CREATE_READ_SESSION_RETRY._predicate(exc) is True


@pytest.mark.parametrize(
    "exc",
    [
        # Deterministic failures must surface rather than retry forever.
        NotFound("404 Requested table was not found."),
        BadRequest("400 request failed"),
    ],
)
def test_bigquery_create_read_session_retry_does_not_retry_deterministic_errors(exc):
    assert BIGQUERY_CREATE_READ_SESSION_RETRY._predicate(exc) is False


def test_bigquery_get_primary_keys_for_table_passes_job_retry():
    """The primary-key probe must run under the extended job retry so a transient BigQuery job
    error is re-tried in place instead of crashing the import."""
    table = mock.MagicMock()
    table.schema = []
    table.dataset_id = "dataset"
    table.table_id = "table"
    table.project = "project"

    client = mock.MagicMock()
    client.query.return_value.result.return_value = []

    _get_primary_keys_for_table(table, client)

    assert client.query.return_value.result.call_args.kwargs["job_retry"] is BIGQUERY_QUERY_JOB_RETRY
    assert client.query.call_args.kwargs["retry"] is BIGQUERY_QUERY_CREATE_RETRY


@mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.bigquery.bigquery.time.sleep")
def test_bigquery_get_primary_keys_for_table_retries_transient_job_not_found(mock_sleep):
    """The primary-key probe hits BigQuery's job-metadata race the same as the other queries in this
    file; it must retry with a fresh job instead of crashing the whole sync."""
    table = mock.MagicMock()
    table.schema = [SimpleNamespace(name="id")]
    table.dataset_id = "dataset"
    table.table_id = "table"
    table.project = "project"

    client = mock.MagicMock()
    ok_job = mock.MagicMock()
    ok_job.result.return_value = iter([{"column_name": "id"}])
    client.query.side_effect = [NotFound("404 Not found: Job prj:US.abc"), ok_job]

    primary_keys = _get_primary_keys_for_table(table, client)

    assert primary_keys == ["id"]
    assert client.query.call_count == 2
    mock_sleep.assert_called_once()


def test_run_destination_query_passes_job_retry():
    """The copy-into-temp-table query — where the production sync crashed on a transient per-second
    rate quota — must run under the extended job retry so it waits the rate limit out in place
    instead of aborting the import."""
    client = mock.MagicMock()

    _run_destination_query_with_job_retry(
        client, "SELECT 1", destination_table=mock.MagicMock(), query_parameters=[], project="prj"
    )

    assert client.query.return_value.result.call_args.kwargs["job_retry"] is BIGQUERY_QUERY_JOB_RETRY
    assert client.query.call_args.kwargs["retry"] is BIGQUERY_QUERY_CREATE_RETRY


@mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.bigquery.bigquery.time.sleep")
def test_run_destination_query_does_not_retry_genuine_not_found(mock_sleep):
    """A genuine `NotFound` (missing dataset/table) is not the job race, so it surfaces immediately
    rather than looping until the attempt cap."""
    client = mock.MagicMock()
    client.query.side_effect = NotFound("404 Not found: Table prj:ds.tbl")

    with pytest.raises(NotFound):
        _run_destination_query_with_job_retry(
            client, "SELECT 1", destination_table=mock.MagicMock(), query_parameters=[], project="prj"
        )

    assert client.query.call_count == 1
    mock_sleep.assert_not_called()


@mock.patch(
    "products.warehouse_sources.backend.temporal.data_imports.sources.bigquery.bigquery._JOB_NOT_FOUND_MAX_ATTEMPTS",
    4,
)
@mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.bigquery.bigquery.time.sleep")
def test_run_destination_query_gives_up_after_max_attempts(mock_sleep):
    """The race almost always clears within moments, but a persistent job-not-found must still stop
    at the attempt cap and surface the error instead of retrying forever."""
    client = mock.MagicMock()
    client.query.side_effect = [NotFound("404 Not found: Job prj:US.abc") for _ in range(4)]

    with pytest.raises(NotFound):
        _run_destination_query_with_job_retry(
            client, "SELECT 1", destination_table=mock.MagicMock(), query_parameters=[], project="prj"
        )

    assert client.query.call_count == 4
    # No back-off after the final, failed attempt.
    assert mock_sleep.call_count == 3


def test_bigquery_storage_read_client_disables_grpc_message_size_limit():
    """Regression: the Storage Read API streams Arrow ReadRowsResponse messages that can
    exceed gRPC's default 4 MiB client receive limit (wide rows / large string columns like
    GeoJSON), which surfaced as `_MultiThreadedRendezvous` RESOURCE_EXHAUSTED "Received
    message larger than max". Because we build the channel ourselves, we must pass the same
    unlimited message-length options the transport sets on its own default channel."""
    with (
        mock.patch.object(bq_module.service_account.Credentials, "from_service_account_info", return_value=mock.Mock()),
        mock.patch.object(bq_module, "make_tracked_channel", return_value=mock.Mock()),
        mock.patch.object(bq_module, "BigQueryReadGrpcTransport") as mock_transport_cls,
        mock.patch.object(bq_module.bigquery_storage, "BigQueryReadClient"),
    ):
        with bq_module.bigquery_storage_read_client(credentials=mock.Mock(spec=GoogleAuthCredentials)):
            pass

    mock_transport_cls.create_channel.assert_called_once()
    options = dict(mock_transport_cls.create_channel.call_args.kwargs["options"])
    assert options["grpc.max_receive_message_length"] == -1
    assert options["grpc.max_send_message_length"] == -1


def test_bigquery_client_retries_transient_token_refresh_failures():
    """Regression: `AuthorizedSession`'s default token-refresh session only retries connection
    errors, not HTTP error responses, so a transient 502/503/504 from Google's OAuth token
    endpoint escaped every `bigquery_client` call site as an opaque `RefreshError` instead of
    being retried. `bigquery_client` must hand `AuthorizedSession` an `auth_request` built from
    a session carrying `BIGQUERY_TOKEN_REFRESH_RETRY`."""
    with bq_module.bigquery_client(
        project_id="project-id",
        location=None,
        credentials=mock.Mock(spec=GoogleAuthCredentials),
    ) as client:
        auth_request_session = client._http._auth_request.session
        adapter = cast(HTTPAdapter, auth_request_session.get_adapter("https://oauth2.googleapis.com"))
        retry = adapter.max_retries

    assert retry is BIGQUERY_TOKEN_REFRESH_RETRY
    assert retry.allowed_methods and "POST" in retry.allowed_methods
    assert retry.status_forcelist and {502, 503, 504} <= set(retry.status_forcelist)


def test_bigquery_source_declares_v2_as_default():
    # The core of this PR: v2 is a supported version and the default for new sources, while the
    # legacy label stays supported so existing pins keep resolving. Guards a revert of the default
    # bump or an accidental drop of a supported label (base-class pin resolution itself is already
    # covered by the registry-invariant suite).
    source = BigQuerySource()
    assert source.supported_versions == ("v1", "v2")
    assert source.default_version == "v2"


# A BigQuery source authenticates either with a Google Cloud service account integration (shared
# across the team, and keyless when PostHog impersonates the account) or with a JSON key file
# uploaded onto the source itself. `resolve_bigquery_auth` picks between them once per run, and
# every client the run opens signs with what it returns.


_BATCH_EXPORT_MODULE = "products.batch_exports.backend.facade.destinations.bigquery"


def _google_cloud_integration(team, *, with_key: bool, email: str = "sa@my-project.iam.gserviceaccount.com"):
    return Integration.objects.create(
        team=team,
        kind=Integration.IntegrationKind.GOOGLE_CLOUD_SERVICE_ACCOUNT,
        integration_id=f"{email}-{team.id}-{'key-file' if with_key else 'impersonated'}",
        config={"project_id": "integration-project", "service_account_email": email},
        sensitive_config=(
            {
                "private_key": "private-key",
                "private_key_id": "private-key-id",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
            if with_key
            else {}
        ),
    )


@pytest.mark.django_db
def test_bigquery_auth_from_keyless_integration_impersonates_only_after_ownership_is_verified(team, settings):
    """A keyless integration means PostHog signs as the customer's service account using its own
    identity. Without the ownership check, a team that merely knows another org's service account
    email could have PostHog read that org's data on its behalf."""
    settings.BATCH_EXPORT_BIGQUERY_STS_AUDIENCE_FIELD = "//iam.googleapis.com/projects/1/locations/global"
    settings.BATCH_EXPORT_BIGQUERY_SERVICE_ACCOUNT = "posthog@posthog.iam.gserviceaccount.com"
    integration = _google_cloud_integration(team, with_key=False)
    config = BigQuerySourceConfig(dataset_id="my_dataset", auth_type=_integration_auth(integration.id))

    with (
        mock.patch(f"{_BATCH_EXPORT_MODULE}.verify_impersonated_service_account_ownership") as mock_verify,
        mock.patch(f"{_BATCH_EXPORT_MODULE}.get_our_google_cloud_credentials"),
        mock.patch.object(bq_module.google_auth_impersonated_credentials, "Credentials") as mock_impersonated,
    ):
        auth = resolve_bigquery_auth(config, team_id=team.id)

    mock_verify.assert_awaited_once_with("sa@my-project.iam.gserviceaccount.com", team.id)
    assert auth.project_id == "integration-project"
    assert auth.credentials is mock_impersonated.return_value
    assert mock_impersonated.call_args.kwargs["target_principal"] == "sa@my-project.iam.gserviceaccount.com"


@pytest.mark.django_db
def test_bigquery_unverified_service_account_ownership_is_reported_and_not_retried(team, settings):
    settings.BATCH_EXPORT_BIGQUERY_STS_AUDIENCE_FIELD = "//iam.googleapis.com/projects/1/locations/global"
    settings.BATCH_EXPORT_BIGQUERY_SERVICE_ACCOUNT = "posthog@posthog.iam.gserviceaccount.com"
    integration = _google_cloud_integration(team, with_key=False)
    config = BigQuerySourceConfig(dataset_id="my_dataset", auth_type=_integration_auth(integration.id))
    # Verbatim wording from batch exports, which raises the same error for the same check.
    ownership_error = ServiceAccountOwnershipError("sa@my-project.iam.gserviceaccount.com", "org-uuid")

    with (
        mock.patch(
            f"{_BATCH_EXPORT_MODULE}.verify_impersonated_service_account_ownership", side_effect=ownership_error
        ),
        mock.patch(f"{_BATCH_EXPORT_MODULE}.get_our_google_cloud_credentials"),
        mock.patch.object(bq_module, "bigquery_client") as mock_client,
    ):
        ok, message = BigQuerySource().validate_credentials(config, team_id=team.id)

    assert ok is False
    assert message == str(ownership_error)
    mock_client.assert_not_called()
    # The customer has to change their service account description, so the sync must stop rather
    # than retry the same rejection every run.
    assert any(key in str(ownership_error) for key in BigQuerySource().get_non_retryable_errors())


@pytest.mark.django_db
def test_bigquery_auth_rejects_an_integration_belonging_to_another_team(team):
    other_team = Team.objects.create(organization=team.organization, name="other")
    integration = _google_cloud_integration(other_team, with_key=True)
    config = BigQuerySourceConfig(dataset_id="my_dataset", auth_type=_integration_auth(integration.id))

    with pytest.raises(BigQueryAuthResolutionError) as exc_info:
        resolve_bigquery_auth(config, team_id=team.id)

    assert str(exc_info.value) == BIGQUERY_INTEGRATION_NOT_FOUND_ERROR


@pytest.mark.django_db
def test_bigquery_connect_works_for_a_source_with_no_key_file(team):
    """Schema discovery resolves the project it queries from the open connection, because a source
    authenticating through an integration has no key file to read a project out of."""
    integration = _google_cloud_integration(team, with_key=True)
    config = BigQuerySourceConfig(dataset_id="my_dataset", auth_type=_integration_auth(integration.id))
    fake_bq = mock.MagicMock()
    fake_bq.get_dataset.return_value.location = "europe-west1"

    with _patch_bigquery_client(fake_bq) as mock_client:
        with BigQueryImplementation().connect(config, team_id=team.id) as conn:
            assert conn is fake_bq

    assert mock_client.call_args_list[-1][0][0] == "integration-project"
    assert mock_client.call_args_list[-1][0][1] == "europe-west1"


_COMPLETE_KEY_FILE = {
    "project_id": "my-project",
    "private_key": "private-key",
    "private_key_id": "private-key-id",
    "client_email": "client-email",
    "token_uri": "https://oauth2.googleapis.com/token",
}


@pytest.mark.parametrize(
    "job_inputs,expected_valid",
    [
        ({"auth_type": "service_account", "google_cloud_service_account_integration_id": 7}, True),
        ({"auth_type": "key_file", "key_file": _COMPLETE_KEY_FILE}, True),
        ({"auth_type": "service_account"}, False),
        ({"auth_type": "key_file"}, False),
        ({"auth_type": "key_file", "key_file": {"project_id": "my-project"}}, False),
        ({"auth_type": "key_file", "key_file": {**_COMPLETE_KEY_FILE, "private_key": ""}}, False),
    ],
)
def test_bigquery_validate_config_reads_a_bare_selection_from_the_flat_payload(job_inputs, expected_valid):
    is_valid, errors = BigQuerySource().validate_config({"dataset_id": "d", **job_inputs})

    assert is_valid is expected_valid
    assert not any("Required field" in error for error in errors)
    if not expected_valid:
        assert any("Google Cloud service account" in error for error in errors)


@pytest.mark.parametrize(
    "caller_timeout, sent_timeout",
    [(None, BIGQUERY_HTTP_TIMEOUT_SECONDS), (5.0, 5.0)],
    ids=["client_default_of_none", "explicit_timeout_is_kept"],
)
def test_bigquery_rest_requests_always_have_a_timeout(caller_timeout, sent_timeout):
    # The BigQuery client passes `timeout=None` for each call without one, and `requests` then
    # waits on a silent server without limit.
    with (
        bq_module.bigquery_client(
            project_id="project-id", location=None, credentials=mock.Mock(spec=GoogleAuthCredentials)
        ) as client,
        mock.patch.object(bq_module.AuthorizedSession, "request") as request,
    ):
        client._http.request("GET", "https://bigquery.googleapis.com/x", timeout=caller_timeout)

    assert request.call_args.kwargs["timeout"] == sent_timeout


@pytest.mark.parametrize("cancel_error", [None, RuntimeError("cancel refused")], ids=["cancelled", "cancel_fails"])
def test_copy_job_past_its_limit_is_cancelled_and_raises_a_retryable_error(cancel_error):
    client = mock.MagicMock()
    job = client.query.return_value
    job.result.side_effect = concurrent.futures.TimeoutError()
    job.cancel.side_effect = cancel_error

    with pytest.raises(BigQueryJobTimeoutError) as error:
        _run_destination_query_with_job_retry(
            client, "SELECT 1", destination_table=mock.MagicMock(), query_parameters=[], project="prj"
        )

    assert job.result.call_args.kwargs["timeout"] == BIGQUERY_COPY_JOB_TIMEOUT_SECONDS
    job.cancel.assert_called_once()
    _assert_retryable(str(error.value))


def test_bigquery_get_rows_to_sync_gives_zero_when_the_count_is_past_its_limit():
    table = mock.MagicMock(project="proj", dataset_id="ds", table_id="t")
    table.schema = [SimpleNamespace(name="age", field_type="INTEGER")]
    client = mock.MagicMock()
    job = client.query.return_value
    job.result.side_effect = concurrent.futures.TimeoutError()

    with mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.bigquery.bigquery.capture_exception"
    ) as mock_capture:
        result = _get_rows_to_sync(
            table=table,
            client=client,
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
            logger=mock.MagicMock(),
            row_filters=[
                ValidatedRowFilter(column="age", operator="IN", value=[21, 30], category=ColumnTypeCategory.INTEGER)
            ],
        )

    assert result == 0
    assert job.result.call_args.kwargs["timeout"] == BIGQUERY_ROW_COUNT_JOB_TIMEOUT_SECONDS
    # A slow count is expected on a large filtered table, so it is not an error to track.
    mock_capture.assert_not_called()


def _assert_retryable(message: str) -> None:
    source = BigQuerySource()
    assert error_message_matches(message, source.get_retryable_errors())
    assert not error_message_matches(message, {**Any_Source_Errors, **source.get_non_retryable_errors()})


def test_row_pages_that_keep_coming_never_end_the_read():
    end_read = mock.Mock()

    pages = list(_pages_with_idle_timeout(iter([1, 2, 3]), timeout_seconds=30, end_read=end_read))

    assert pages == [1, 2, 3]
    end_read.assert_not_called()


def test_each_row_page_gets_its_own_wait_limit(monkeypatch):
    # A limit on the stream as a whole would end a long read that is in good health.
    timers: list[mock.Mock] = []

    def fake_timer(interval, function):
        timers.append(mock.Mock(interval=interval))
        return timers[-1]

    monkeypatch.setattr(bq_module.threading, "Timer", fake_timer)

    list(_pages_with_idle_timeout(iter([1, 2]), timeout_seconds=600, end_read=mock.Mock()))

    # One wait for each page, and one for the end of the stream.
    assert [timer.interval for timer in timers] == [600, 600, 600]
    assert all(timer.start.called and timer.cancel.called for timer in timers)


def test_row_page_that_does_not_come_ends_the_read_with_a_retryable_error():
    ended = threading.Event()

    def silent_stream():
        yield "first page"
        assert ended.wait(5)
        raise ValueError("Cannot invoke RPC on closed channel!")

    taken = []
    with pytest.raises(BigQueryReadTimeoutError) as error:
        for page in _pages_with_idle_timeout(silent_stream(), timeout_seconds=0.05, end_read=ended.set):
            taken.append(page)

    assert taken == ["first page"]
    _assert_retryable(str(error.value))


def test_row_page_error_before_the_limit_keeps_its_own_class():
    def broken_stream():
        raise InvalidArgument("the read session is not valid")
        yield

    with pytest.raises(InvalidArgument):
        list(_pages_with_idle_timeout(broken_stream(), timeout_seconds=30, end_read=mock.Mock()))
