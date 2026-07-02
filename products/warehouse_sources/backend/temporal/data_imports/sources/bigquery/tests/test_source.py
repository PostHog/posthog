from types import SimpleNamespace

import pytest
from freezegun import freeze_time
from unittest import mock

from dateutil import parser
from google.api_core.exceptions import BadRequest, Forbidden, InvalidArgument, NotFound, PermissionDenied
from google.auth.exceptions import RefreshError

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.bigquery import bigquery as bq_module
from products.warehouse_sources.backend.temporal.data_imports.sources.bigquery.bigquery import (
    BIGQUERY_DATASET_NOT_FOUND_ERROR,
    BIGQUERY_INVALID_IDENTIFIER_ERROR,
    BIGQUERY_QUERY_JOB_RETRY,
    BIGQUERY_TOKEN_RESPONSE_ERROR,
    BigQueryCredentialsRejectedError,
    BigQueryDatasetNotFoundError,
    BigQueryImplementation,
    BigQueryInvalidIdentifierError,
    BigQueryTokenRefreshError,
    _bq_select_clause,
    _get_primary_keys_for_table,
    _get_query,
    _get_rows_to_sync,
    _has_duplicate_primary_keys,
    _is_transient_job_not_found,
    _resolve_dataset_id,
    _resolve_dataset_project_id,
    _resolve_project_id,
    _resolve_query_project,
    _resolve_region,
    _run_destination_query_with_job_retry,
    delete_all_temp_destination_tables,
    validate_bigquery_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.bigquery.source import BigQuerySource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.identifiers import (
    InvalidIdentifierError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.predicates import (
    ColumnTypeCategory,
    ValidatedRowFilter,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import (
    BigQueryDatasetProjectConfig,
    BigQueryKeyFileConfig,
    BigQuerySourceConfig,
    BigQueryTemporaryDatasetConfig,
    BigQueryUseCustomRegionConfig,
)
from products.warehouse_sources.backend.types import IncrementalFieldType


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


def _make_config(
    *,
    project_id: str = "project-id",
    dataset_id: str = "dataset-id",
    dataset_project: BigQueryDatasetProjectConfig | None = None,
    temporary_dataset: BigQueryTemporaryDatasetConfig | None = None,
) -> BigQuerySourceConfig:
    return BigQuerySourceConfig(
        key_file=BigQueryKeyFileConfig(
            project_id=project_id,
            private_key="private-key",
            private_key_id="private-key-id",
            client_email="client-email",
            token_uri="token-uri",
        ),
        dataset_id=dataset_id,
        dataset_project=dataset_project,
        temporary_dataset=temporary_dataset,
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


@pytest.mark.parametrize("phrase", ['Invalid dataset ID "(default)"', 'Invalid project ID "bad id"'])
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
        freeze_time("2025-01-01T12:00:00.000Z"),
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
    "enabled_columns,primary_keys,incremental_field,expected",
    [
        (None, ["id"], None, "*"),
        (["email"], ["id"], None, "`email`, `id`"),
        (["email"], ["id"], "created_at", "`email`, `id`, `created_at`"),
        ([], None, None, "*"),
        ([], ["id"], None, "`id`"),
    ],
)
def test_bigquery_select_clause(enabled_columns, primary_keys, incremental_field, expected):
    assert _bq_select_clause(enabled_columns, primary_keys, incremental_field) == expected


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


def test_bigquery_get_query_keeps_incremental_field_in_projection():
    bq_table = mock.MagicMock(dataset_id="ds", table_id="t")
    query, params = _get_query(
        should_use_incremental_field=True,
        db_incremental_field_last_value=42,
        bq_table=bq_table,
        incremental_field="updated_at",
        incremental_field_type=IncrementalFieldType.Integer,
        enabled_columns=["email"],
        primary_keys=["id"],
    )
    assert "SELECT `email`, `id`, `updated_at` FROM" in query
    assert "WHERE `updated_at` > 42" in query
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


def test_bigquery_get_rows_to_sync_runs_count_query_when_filtered():
    # With row filters present the whole-table `num_rows` shortcut is invalid, so a COUNT(*)
    # query with bound parameters runs instead.
    table = mock.MagicMock(project="proj", dataset_id="ds", table_id="t")
    table.schema = [SimpleNamespace(name="age", field_type="INTEGER")]
    client = mock.MagicMock()
    job = mock.MagicMock()
    job.result.return_value = iter([[123]])
    client.query.return_value = job

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
    client.get_table.assert_not_called()  # num_rows shortcut skipped when filtered
    count_query = client.query.call_args.args[0]
    assert "COUNT(*)" in count_query
    job_config = client.query.call_args.kwargs["job_config"]
    assert [p.name for p in job_config.query_parameters] == ["row_filter_0_0", "row_filter_0_1"]


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


def test_bigquery_get_query_in_filter_expands_to_one_param_per_value():
    bq_table = mock.MagicMock(dataset_id="ds", table_id="t")
    bq_table.schema = [SimpleNamespace(name="age", field_type="INTEGER")]
    query, params = _get_query(
        should_use_incremental_field=False,
        db_incremental_field_last_value=None,
        bq_table=bq_table,
        row_filters=[
            ValidatedRowFilter(column="age", operator="IN", value=[21, 30], category=ColumnTypeCategory.INTEGER)
        ],
    )
    assert "WHERE `age` IN (@row_filter_0_0, @row_filter_0_1)" in query
    assert [(p.name, p.type_, p.value) for p in params] == [
        ("row_filter_0_0", "INT64", 21),
        ("row_filter_0_1", "INT64", 30),
    ]


def test_bigquery_get_query_row_filters_compose_with_incremental():
    bq_table = mock.MagicMock(dataset_id="ds", table_id="t")
    bq_table.schema = [SimpleNamespace(name="age", field_type="INTEGER")]
    query, params = _get_query(
        should_use_incremental_field=True,
        db_incremental_field_last_value=42,
        bq_table=bq_table,
        incremental_field="updated_at",
        incremental_field_type=IncrementalFieldType.Integer,
        row_filters=[ValidatedRowFilter(column="age", operator=">", value=21, category=ColumnTypeCategory.INTEGER)],
    )
    assert "WHERE `updated_at` > 42 AND `age` > @row_filter_0 ORDER BY `updated_at` ASC" in query
    assert [(p.name, p.value) for p in params] == [("row_filter_0", 21)]


@pytest.mark.parametrize(
    "field_type,last_value,expected_clause,offset_present",
    [
        # DATETIME columns are timezone-naive — a tz-aware literal can't be cast and BigQuery rejects it
        # with "Could not cast literal ... to type DATETIME". On the first incremental sync the cursor
        # defaults to the 1970-01-01 UTC initial value, whose isoformat carries a '+00:00' offset; for a
        # DATETIME field the literal must be naive.
        (IncrementalFieldType.DateTime, None, "WHERE `cursor` > '1970-01-01T00:00:00'", False),
        # A tz-aware value carried over from a previous sync is also rendered naive for DATETIME fields.
        (
            IncrementalFieldType.DateTime,
            parser.parse("2024-03-11T09:26:04+00:00"),
            "WHERE `cursor` > '2024-03-11T09:26:04'",
            False,
        ),
        # TIMESTAMP columns are timezone-aware, so the offset must be preserved in the literal.
        (IncrementalFieldType.Timestamp, None, "WHERE `cursor` > '1970-01-01T00:00:00+00:00'", True),
    ],
)
def test_bigquery_get_query_datetime_cursor_timezone_offset(field_type, last_value, expected_clause, offset_present):
    bq_table = mock.MagicMock(dataset_id="ds", table_id="t")
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
        # Raised when the Dataset ID is `project.dataset`, so we build a 4-component table id.
        'table_id must be a fully-qualified ID in standard SQL format, e.g., "project.dataset.table_id", '
        "got immortal-407108.immortal-407108.analytics_529249625.events_20260325",
        'table_id must be a fully-qualified ID in standard SQL format, e.g., "project.dataset.table_id", '
        "got immortal-407108.immortal-407108.analytics_529249625.__posthog_import_abc_def_123",
    ],
)
def test_bigquery_malformed_table_id_is_non_retryable(observed_error):
    non_retryable_errors = BigQuerySource().get_non_retryable_errors()
    matching = [key for key in non_retryable_errors if key in observed_error]
    assert matching, "Malformed table id error should be recognised as non-retryable"
    assert all(non_retryable_errors[key] is not None for key in matching)


@pytest.mark.parametrize(
    "observed_error",
    [
        # Offline ngrok tunnel — the subdomain varies but the stable error code does not.
        "RefreshError: <!DOCTYPE html> <html> ... "
        "<noscript>The endpoint tetrarchical-coercibly-norine.ngrok-free.dev is offline. (ERR_NGROK_3200)</noscript>",
        # Different tunnel subdomain — the match must not rely on the volatile host part.
        "RefreshError: <!DOCTYPE html> <html> ... "
        "<noscript>The endpoint other-tunnel-name.ngrok-free.dev is offline. (ERR_NGROK_3200)</noscript>",
    ],
)
def test_non_retryable_errors_match_offline_token_uri_endpoint(observed_error):
    """A service account whose `token_uri` points at an offline ngrok tunnel makes google-auth
    raise a `RefreshError` carrying ngrok's HTML error page — a misconfigured key the user must
    fix, so the sync must be disabled rather than retried forever."""
    non_retryable_errors = BigQuerySource().get_non_retryable_errors()
    matching = [key for key in non_retryable_errors if key in observed_error]
    assert matching, "Offline token_uri endpoint error should be recognised as non-retryable"
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


@pytest.mark.parametrize(
    "transient_error",
    [
        # A token refresh that failed for a transient reason must stay retryable.
        "RefreshError: ('Failed to retrieve token', {'error': 'internal_failure'})",
        "RefreshError: HTTPError 503 Service Unavailable",
        "Connection reset by peer",
        "ReadTimeout: The read operation timed out",
        "503 Service Unavailable",
    ],
)
def test_non_retryable_errors_does_not_match_transient_refresh_failures(transient_error):
    """Transient errors must not match any non-retryable key, so they stay retryable. Mirrors the
    real matching mechanism (substring against every key) to guard against an overly broad key."""
    non_retryable_errors = BigQuerySource().get_non_retryable_errors()
    matching = [key for key in non_retryable_errors if key in transient_error]
    assert not matching, f"Transient error should remain retryable, but matched keys: {matching}"


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
            private_key="private-key",
            private_key_id="private-key-id",
            client_email="client-email",
            token_uri="token-uri",
            logger=logger,
        )
    return mock_capture


@pytest.mark.parametrize(
    "exception",
    [
        Forbidden("Access Denied: Permission bigquery.tables.list denied on dataset"),
        NotFound("Dataset not found (or it may not exist)"),
        RefreshError(("invalid_grant: Invalid JWT Signature.", {"error": "invalid_grant"})),
    ],
)
def test_delete_all_temp_destination_tables_swallows_expected_errors_quietly(exception):
    """Lost permissions, a deleted dataset, or rejected credentials during best-effort cleanup
    must NOT be captured to error tracking — it's expected and fires on every sync otherwise."""
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


@pytest.mark.parametrize(
    "resolver,field,raw,expected",
    [
        (_resolve_project_id, "project_id", " 524098457564", "524098457564"),
        (_resolve_project_id, "project_id", "project-id\n", "project-id"),
        (_resolve_dataset_id, "dataset_id", " bigquery_aloalo ", "bigquery_aloalo"),
        (_resolve_dataset_id, "dataset_id", "\tdataset-id", "dataset-id"),
    ],
)
def test_bigquery_resolvers_trim_whitespace(resolver, field, raw, expected):
    config = _make_config(**{field: raw})
    assert resolver(config) == expected


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


def test_connect_auto_detects_dataset_region_when_unset():
    """No custom region configured: connect must pin the discovery client to the dataset's real
    location (read via the region-agnostic `get_dataset`) instead of defaulting to US."""
    fake_bq = mock.MagicMock()
    fake_bq.get_dataset.return_value.location = "europe-west1"

    with _patch_bigquery_client(fake_bq) as mock_client:
        with BigQueryImplementation().connect(_make_config()) as conn:
            assert conn is fake_bq

    # The region must come from an actual dataset-location lookup, not a hardcoded default.
    fake_bq.get_dataset.assert_called_once()
    # The last client built is the one discovery queries run on; its location is positional arg 1.
    assert mock_client.call_args_list[-1][0][1] == "europe-west1"


def test_connect_uses_configured_region_without_probing():
    """A configured custom region is used as-is — no dataset-location probe is performed."""
    config = _make_config()
    config.use_custom_region = BigQueryUseCustomRegionConfig(region="us-east1", enabled=True)
    fake_bq = mock.MagicMock()

    with _patch_bigquery_client(fake_bq) as mock_client:
        with BigQueryImplementation().connect(config):
            pass

    fake_bq.get_dataset.assert_not_called()
    assert mock_client.call_count == 1
    assert mock_client.call_args_list[-1][0][1] == "us-east1"


def test_connect_falls_back_to_unset_location_when_detection_fails():
    """If the dataset-location probe fails (e.g. the dataset really doesn't exist), connect leaves
    the location unset so `get_columns` still surfaces the actionable not-found error."""
    fake_bq = mock.MagicMock()
    fake_bq.get_dataset.side_effect = NotFound("Not found: Dataset prj:ds")

    with _patch_bigquery_client(fake_bq) as mock_client:
        with BigQueryImplementation().connect(_make_config()):
            pass

    assert mock_client.call_args_list[-1][0][1] is None


def test_bigquery_resolve_dataset_project_id_trims_and_treats_whitespace_as_unset():
    config = _make_config(
        dataset_project=BigQueryDatasetProjectConfig(dataset_project_id="  other-project ", enabled=True)
    )
    assert _resolve_dataset_project_id(config) == "other-project"

    config = _make_config(dataset_project=BigQueryDatasetProjectConfig(dataset_project_id="   ", enabled=True))
    assert _resolve_dataset_project_id(config) is None


def test_bigquery_resolve_query_project_prefers_dataset_project():
    config = _make_config(
        project_id=" service-account-project ",
        dataset_project=BigQueryDatasetProjectConfig(dataset_project_id=" dataset-project ", enabled=True),
    )
    assert _resolve_query_project(config) == "dataset-project"

    config = _make_config(project_id=" service-account-project ")
    assert _resolve_query_project(config) == "service-account-project"


def test_bigquery_get_columns_trims_whitespace_in_identifiers():
    """`get_columns` must not embed a leading space into the INFORMATION_SCHEMA query
    or the `project` it runs against."""
    fake_client = mock.MagicMock()
    fake_client.query.return_value.result.return_value = []

    config = _make_config(project_id=" 524098457564", dataset_id=" bigquery_aloalo ")
    BigQueryImplementation().get_columns(fake_client, config, names=None)

    sql = fake_client.query.call_args.args[0]
    assert "`bigquery_aloalo.INFORMATION_SCHEMA.COLUMNS`" in sql
    assert " bigquery_aloalo" not in sql
    assert fake_client.query.call_args.kwargs["project"] == "524098457564"


def test_bigquery_get_primary_keys_trims_whitespace_in_identifiers():
    fake_client = mock.MagicMock()
    fake_client.query.return_value.result.return_value = []

    config = _make_config(project_id=" my-project ", dataset_id=" my_dataset ")
    BigQueryImplementation().get_primary_keys(fake_client, config, tables=["t"])

    sql = fake_client.query.call_args.args[0]
    assert "`my_dataset`.INFORMATION_SCHEMA.TABLE_CONSTRAINTS" in sql
    assert " my_dataset`" not in sql
    assert fake_client.query.call_args.kwargs["project"] == "my-project"


def test_bigquery_validate_credentials_trims_whitespace_before_calling_bigquery():
    bq = mock.MagicMock()
    client_cm = mock.MagicMock()
    client_cm.__enter__.return_value = bq

    with mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.bigquery.bigquery.bigquery_client",
        return_value=client_cm,
    ) as mock_client:
        validate_bigquery_credentials(
            dataset_id=" my_dataset ",
            key_file={
                "project_id": " 524098457564",
                "private_key": "private-key",
                "private_key_id": "private-key-id",
                "client_email": "client-email",
                "token_uri": "token-uri",
            },
            dataset_project_id=None,
            location=None,
        )

    assert mock_client.call_args.args[0] == "524098457564"
    bq.dataset.assert_called_once_with("my_dataset", project="524098457564")


def test_bigquery_build_pipeline_trims_whitespace_in_destination_table():
    """Whitespace in project/dataset IDs must not leak into the fully-qualified
    destination table name passed to BigQuery during a sync."""
    config = _make_config(project_id=" 524098457564", dataset_id=" bigquery_aloalo ")
    expected_table_id = (
        f"524098457564.bigquery_aloalo.__posthog_import_schema_id_job_id_"
        f"{str(parser.parse('2025-01-01T12:00:00.000Z').timestamp()).replace('.', '')}"
    )

    with (
        freeze_time("2025-01-01T12:00:00.000Z"),
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.bigquery.bigquery.delete_all_temp_destination_tables",
        ) as mock_delete_all,
        mock.patch.object(BigQueryImplementation, "_build_source_response", return_value=mock.MagicMock()),
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.bigquery.bigquery.delete_table",
        ) as mock_delete,
    ):
        BigQuerySource().source_for_pipeline(config, _make_inputs())

    assert mock_delete_all.call_args.kwargs["project_id"] == "524098457564"
    assert mock_delete_all.call_args.kwargs["dataset_id"] == "bigquery_aloalo"
    assert mock_delete.call_args.kwargs["table_id"] == expected_table_id


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
    ],
)
def test_non_retryable_errors_match_permission_denied(observed_error):
    non_retryable_errors = BigQuerySource().get_non_retryable_errors()
    assert any(key in observed_error for key in non_retryable_errors)


def test_temp_table_write_denial_surfaces_write_permission_guidance():
    # A tables.update denial on a PostHog temp table also contains "Access Denied:", so both keys
    # match. external_data_job surfaces the first matching key's message, so the write-specific key
    # must sit above "Access Denied:" — otherwise the customer is told to grant read access to fix a
    # write failure.
    observed_error = str(
        Forbidden(
            "Access Denied: Table prj:ds.__posthog_import_abc_123: Permission bigquery.tables.update "
            "denied on table prj:ds.__posthog_import_abc_123 (or it may not exist)."
        )
    )
    non_retryable_errors = BigQuerySource().get_non_retryable_errors()
    first_key, friendly = next((key, msg) for key, msg in non_retryable_errors.items() if key in observed_error)
    assert first_key == "bigquery.tables.update"
    assert friendly is not None
    assert "write access" in friendly


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
        # Federated EXTERNAL_QUERY view whose upstream schema drifted — a column the view selects was
        # renamed/dropped in the source database, so BigQuery can't compile the view.
        str(
            BadRequest(
                "GET https://bigquery.googleapis.com/bigquery/v2/projects/p/queries/j?maxResults=0"
                "&location=us-central1: Invalid table-valued function EXTERNAL_QUERY; failed to parse "
                "view 'analytics.SurveyResponse'\nFailed to get query schema from PostgreSQL server, "
                'prepare statement failed. Error: ERROR:  column "participantId" does not exist'
            )
        ),
    ],
)
def test_non_retryable_errors_match_unparseable_view(observed_error):
    """A view whose definition no longer matches the underlying data (e.g. a federated query
    references a dropped column) can't be recovered by retrying — the user must fix the view."""
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


@pytest.mark.parametrize(
    "other_error",
    [
        # Transient server / connection errors must stay retryable
        "503 Service unavailable, please retry",
        "500 Internal error encountered",
        "Connection reset by peer",
        # A federated-read failure that isn't a permission problem must stay retryable
        "Error while reading data, error message: Failed to fetch row from PostgreSQL server. "
        "Error: ERROR:  connection to server timed out",
        # Transient rate-limit quota errors ("Quota exceeded" / `rateLimitExceeded`) are NOT the
        # administrator-set custom cost control and must stay retryable — the "Custom quota
        # exceeded" key must not catch them.
        "403 Quota exceeded: Your project exceeded quota for concurrent queries; reason: quotaExceeded",
        "403 Exceeded rate limits: too many concurrent queries for this project; reason: rateLimitExceeded",
    ],
)
def test_non_retryable_errors_does_not_match_transient(other_error):
    non_retryable_errors = BigQuerySource().get_non_retryable_errors()
    assert not any(key in other_error for key in non_retryable_errors)


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


@pytest.mark.parametrize(
    "exc",
    [
        # The transient `jobInternalError` from `jobs.getQueryResults` (volatile project/job id redacted).
        BadRequest(
            "GET https://bigquery.googleapis.com/bigquery/v2/projects/<redacted>/queries/<redacted>"
            "?maxResults=0&location=US&prettyPrint=false: The job encountered an error during execution. "
            "Retrying the job may solve the problem."
        ),
        # The library default's own retryable reasons must still be honoured.
        BadRequest("query failed", errors=[{"reason": "backendError", "message": "internal error"}]),
        BadRequest("query failed", errors=[{"reason": "rateLimitExceeded", "message": "slow down"}]),
    ],
)
def test_bigquery_query_job_retry_retries_transient_job_errors(exc):
    assert BIGQUERY_QUERY_JOB_RETRY._predicate(exc) is True


@pytest.mark.parametrize(
    "exc",
    [
        # A genuinely malformed query is deterministic — retrying never helps, so it must surface.
        BadRequest("Syntax error: Unexpected keyword SELECT"),
        BadRequest("query failed", errors=[{"reason": "invalidQuery", "message": "bad SQL"}]),
    ],
)
def test_bigquery_query_job_retry_does_not_retry_deterministic_errors(exc):
    assert BIGQUERY_QUERY_JOB_RETRY._predicate(exc) is False


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


@pytest.mark.parametrize(
    "message",
    [
        "404 GET https://bigquery.googleapis.com/.../jobs/abc?projection=full: Not found: Job prj:US.abc",
        "Not found: Job prj:EU.job_xyz",
        "Job not found: job_xyz",
    ],
)
def test_is_transient_job_not_found_matches_job_race(message):
    assert _is_transient_job_not_found(NotFound(message)) is True


@pytest.mark.parametrize(
    "message",
    [
        # A missing dataset/table (or a dataset absent from the queried region) is genuinely
        # non-retryable and must not be mistaken for the job race, even though the raw dataset 404
        # can carry a trailing "Job ID:".
        "404 Not found: Dataset prj:ds was not found in location US Job ID: b3abc342-16a7",
        "404 Not found: Table prj:ds.tbl",
    ],
)
def test_is_transient_job_not_found_ignores_other_not_found(message):
    assert _is_transient_job_not_found(NotFound(message)) is False


@mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.bigquery.bigquery.time.sleep")
def test_run_destination_query_retries_transient_job_not_found(mock_sleep):
    """The copy-into-temp-table query is where the production sync crashed on BigQuery's job-metadata
    race; a transient job-not-found must be retried with a fresh job instead of aborting the import."""
    client = mock.MagicMock()
    ok_job = mock.MagicMock()
    client.query.side_effect = [NotFound("404 Not found: Job prj:US.abc"), ok_job]

    _run_destination_query_with_job_retry(
        client, "SELECT 1", destination_table=mock.MagicMock(), query_parameters=[], project="prj"
    )

    assert client.query.call_count == 2
    ok_job.result.assert_called_once()
    mock_sleep.assert_called_once()
    # WRITE_TRUNCATE keeps the re-run idempotent against a temp table a lost first attempt populated.
    assert client.query.call_args.kwargs["job_config"].write_disposition == "WRITE_TRUNCATE"


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


@pytest.mark.parametrize(
    "location",
    ["US", "EU", "asia-northeast1"],
)
def test_bigquery_dataset_not_found_in_location_is_non_retryable(location):
    """A deleted/renamed dataset (or one in a region we don't query) surfaces from schema
    discovery as a google-api-core NotFound. Its str() is "404 Not found: Dataset ... was
    not found in location <X>", which must be recognised as non-retryable via the
    "was not found in location" pattern instead of retrying forever."""
    error = NotFound(
        f"Not found: Dataset my-proj:my_dataset was not found in location {location}; "
        f"reason: notFound, message: Not found: Dataset my-proj:my_dataset was not found in location {location}"
    )

    # Mirror the substring match in `sync_new_schemas_activity` / `update_external_data_job_model`.
    error_msg = str(error)
    non_retryable_errors = BigQuerySource().get_non_retryable_errors()

    assert any(pattern in error_msg for pattern in non_retryable_errors)


@pytest.mark.parametrize(
    "location",
    ["ua", "us-fake1", "EU "],
)
def test_bigquery_unsupported_region_is_non_retryable(location):
    """A custom/auto-detected region BigQuery can't run query jobs in surfaces from job creation as
    a 400 BadRequest whose str() is "... Location <X> does not support this operation.". It's a
    deterministic config error — retrying the same location always fails — so it must be recognised
    as non-retryable via the "does not support this operation" pattern rather than retrying forever.
    The volatile location code must not be part of the match."""
    error_msg = str(
        BadRequest(
            f"POST https://bigquery.googleapis.com/bigquery/v2/projects/my-proj/jobs?prettyPrint=false: "
            f"Location {location} does not support this operation."
        )
    )

    non_retryable_errors = BigQuerySource().get_non_retryable_errors()
    matching = [key for key in non_retryable_errors if key in error_msg]

    assert matching, "an unsupported-region 400 should be recognised as non-retryable"
    assert all(non_retryable_errors[key] is not None for key in matching)
    assert all(location not in key for key in matching), "match must not depend on the volatile location"


def test_bigquery_table_not_found_during_sync_is_non_retryable():
    """A table deleted/renamed after schema discovery surfaces from `get_table()` at sync time as a
    google NotFound whose str() is "... Not found: Table <project>:<dataset>.<table>" — distinct from
    the dataset-region "was not found in location" wording. It must be recognised as non-retryable via
    the "Not found: Table" pattern instead of retrying a table that can't reappear within the run."""
    error = NotFound(
        "GET https://bigquery.googleapis.com/bigquery/v2/projects/my-proj/datasets/my_dataset/"
        "tables/my_table?prettyPrint=false: Not found: Table my-proj:my_dataset.my_table"
    )

    # Mirror the substring match in `update_external_data_job_model`.
    error_msg = str(error)
    non_retryable_errors = BigQuerySource().get_non_retryable_errors()
    matching = [key for key in non_retryable_errors if key in error_msg]

    assert matching, "a table-not-found 404 during sync should be recognised as non-retryable"
    assert all(non_retryable_errors[key] is not None for key in matching)
    assert "was not found in location" not in error_msg


@pytest.mark.parametrize(
    "other_error",
    [
        # Transient server errors must stay retryable.
        "503 Service unavailable, please retry",
        "500 Internal error encountered, please retry",
    ],
)
def test_bigquery_table_not_found_key_does_not_match_unrelated_errors(other_error):
    non_retryable_errors = BigQuerySource().get_non_retryable_errors()
    assert "Not found: Table" not in other_error
    assert not any(key in other_error for key in non_retryable_errors)


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
        with bq_module.bigquery_storage_read_client(
            project_id="project-id",
            private_key="private-key",
            private_key_id="private-key-id",
            client_email="client-email",
            token_uri="token-uri",
        ):
            pass

    mock_transport_cls.create_channel.assert_called_once()
    options = dict(mock_transport_cls.create_channel.call_args.kwargs["options"])
    assert options["grpc.max_receive_message_length"] == -1
    assert options["grpc.max_send_message_length"] == -1


def test_bigquery_billing_not_enabled_is_non_retryable():
    # A `billingNotEnabled` Forbidden 403 is a customer config issue — retrying never helps.
    # Representative message from a real failed job (the `reason: billingNotEnabled` 403 raised
    # by `job.result()` when the source project has BigQuery billing disabled / is in sandbox mode).
    internal_error = (
        "Forbidden: 403 Billing has not been enabled for this project. Enable billing at "
        "https://console.cloud.google.com/billing. Datasets must have a default expiration time "
        "and default partition expiration time of less than 60 days while in sandbox mode.; "
        "reason: billingNotEnabled, message: Billing has not been enabled for this project."
    )

    non_retryable_errors = BigQuerySource().get_non_retryable_errors()

    billing_key = "Billing has not been enabled for this project"
    assert billing_key in non_retryable_errors, "expected billing key to be non-retryable"
    # Mirror the substring match used by `update_external_data_job_model`.
    assert billing_key in internal_error


def test_bigquery_cdc_staleness_is_non_retryable():
    """A CDC table whose pending upserts are staler than its max_staleness can't be read via the
    Storage Read API (it never applies CDC changes), so the read fails as an InvalidArgument.
    Retrying within the sync's window can't recover it — the apply happens on BigQuery's schedule —
    so it must be recognised as non-retryable instead of hammering the Read API every attempt."""
    error_msg = str(
        InvalidArgument(
            "request failed: The table has un-applied upsert data that is not fresh enough to meet "
            "table's max_staleness."
        )
    )

    non_retryable_errors = BigQuerySource().get_non_retryable_errors()
    matching = [key for key in non_retryable_errors if key in error_msg]

    assert matching, "CDC max_staleness read failure should be recognised as non-retryable"
    assert all(non_retryable_errors[key] is not None for key in matching)


@pytest.mark.parametrize(
    "other_error",
    [
        # A genuine config error about max_staleness must not be swallowed by the freshness key.
        "400 Invalid value for max_staleness: must be a valid INTERVAL",
        # Transient server errors must stay retryable.
        "503 Service unavailable, please retry",
    ],
)
def test_bigquery_cdc_staleness_key_does_not_match_unrelated_errors(other_error):
    non_retryable_errors = BigQuerySource().get_non_retryable_errors()
    assert "un-applied upsert data that is not fresh enough" not in other_error
    assert not any(key in other_error for key in non_retryable_errors)
