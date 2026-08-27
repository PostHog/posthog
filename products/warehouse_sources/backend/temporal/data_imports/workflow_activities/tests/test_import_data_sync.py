import uuid
import contextlib
from datetime import datetime
from typing import Any, cast

import pytest
from posthog.test.base import BaseTest
from unittest import mock

from django.db import InterfaceError, InternalError, OperationalError

from jsonpath_ng.exceptions import JsonPathParserError
from parameterized import parameterized
from requests.exceptions import HTTPError

from posthog.integration_secrets.errors import (
    IntegrationServiceMisconfiguredError,
    IntegrationServiceUnreachableError,
    SecretInRecoveryError,
    SecretMissingError,
)
from posthog.temporal.common.errors import NonReportableError

from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.arrow_utils import (
    SchemaColumnTypeChangedException,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientNonRetryableError,
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.util import (
    NonRetryableException,
    PostHogInternalDatabaseError,
)
from products.warehouse_sources.backend.temporal.data_imports.workflow_activities import import_data_sync as module
from products.warehouse_sources.backend.temporal.data_imports.workflow_activities.import_data_sync import (
    ImportDataActivityInputs,
    import_data_activity_sync,
)
from products.warehouse_sources.backend.types import IncrementalFieldType


class _FakeAsyncCM:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


def _passthrough(fn):
    """Stand-in for database_sync_to_async_pool that just calls the wrapped fn."""

    async def _inner(*args, **kwargs):
        return fn(*args, **kwargs)

    return _inner


@contextlib.contextmanager
def _patched_activity(source_mock):
    """Patch out every dependency import_data_activity_sync touches before source setup."""
    model = mock.MagicMock()
    model.pipeline.source_type = "MongoDB"
    model.pipeline.job_inputs = {}
    model.folder_path = mock.Mock(return_value="dataset")

    schema = mock.MagicMock()
    schema.should_use_incremental_field = False
    schema.row_filters = None

    with (
        mock.patch.object(module, "tag_queries"),
        mock.patch.object(module, "report_heartbeat_timeout"),
        mock.patch.object(module, "Heartbeater", return_value=_FakeAsyncCM()),
        mock.patch.object(module, "ShutdownMonitor", return_value=_FakeAsyncCM()),
        mock.patch.object(module, "setup_row_tracking", new=mock.AsyncMock()),
        mock.patch.object(module, "_get_external_data_job", new=mock.AsyncMock(return_value=model)),
        mock.patch.object(module, "_get_external_data_schema", new=mock.AsyncMock(return_value=schema)),
        mock.patch.object(module, "ExternalDataSourceType", return_value="MongoDB"),
        mock.patch.object(module, "bind_job_context"),
        mock.patch.object(module, "trim_source_job_inputs", new=mock.AsyncMock()),
        mock.patch.object(module, "database_sync_to_async_pool", new=_passthrough),
        mock.patch.object(module.SourceRegistry, "is_registered", return_value=True),
        mock.patch.object(module.SourceRegistry, "get_source", return_value=source_mock),
        mock.patch.object(module, "handle_non_retryable_error", new=mock.AsyncMock()) as handle_mock,
    ):
        yield handle_mock


def _make_source(error: Exception, non_retryable: dict[str, str | None]):
    source = mock.MagicMock(spec=SimpleSource)
    source.parse_config.return_value = {}
    source.get_non_retryable_errors.return_value = non_retryable
    source.get_required_parent_schemas.return_value = []
    source.source_for_pipeline.side_effect = error
    return source


def _inputs() -> ImportDataActivityInputs:
    return ImportDataActivityInputs(
        team_id=1,
        schema_id=uuid.uuid4(),
        source_id=uuid.uuid4(),
        run_id=str(uuid.uuid4()),
        reset_pipeline=True,
    )


class TestGetModelsPrefetchesSource(BaseTest):
    def test_folder_path_needs_no_query_after_load(self) -> None:
        # folder_path() reads schema.source.source_type. If _get_models stops prefetching
        # schema__source, that read fires a lazy SELECT later in the run, on a pooled app-DB
        # connection the transaction pooler can drop mid-sync — surfacing as a spurious
        # OperationalError/DNS failure far from where the real query would have been.
        source = ExternalDataSource.objects.create(
            source_id=str(uuid.uuid4()), connection_id=str(uuid.uuid4()), team=self.team, source_type="Stripe"
        )
        schema = ExternalDataSchema.objects.create(name="Invoice", team=self.team, source=source, sync_type_config={})
        job = ExternalDataJob.objects.create(
            team=self.team, pipeline=source, schema=schema, status=ExternalDataJob.Status.RUNNING
        )

        # Call the undecorated sync loader directly so the query capture runs on this thread.
        # `.func` is the wrapped sync callable on database_sync_to_async_pool's DatabaseSyncToAsync
        # (asgiref); it isn't on the decorator's static type, hence the cast.
        models = cast(Any, module._get_models).func(str(job.id))

        with self.assertNumQueries(0):
            models.job.folder_path()


@pytest.mark.asyncio
async def test_non_retryable_setup_error_routes_through_handler():
    # A MongoDB mongodb+srv:// URI resolves DNS in the MongoClient constructor, so a deleted
    # cluster hostname raises during source setup (source_for_pipeline), before the run phase.
    error = Exception("The DNS query name does not exist: _mongodb._tcp.cluster0.example.mongodb.net.")
    source = _make_source(error, {"The DNS query name does not exist": None})

    with _patched_activity(source) as handle_mock:
        # handle_non_retryable_error always raises (re-raises the error, or NonRetryableException
        # once retries are exhausted) — mirror that so the activity doesn't fall through to _run.
        handle_mock.side_effect = NonRetryableException()
        with pytest.raises(NonRetryableException):
            await import_data_activity_sync(_inputs())

    handle_mock.assert_awaited_once()
    assert handle_mock.await_args.args[5] is error


@pytest.mark.asyncio
async def test_retryable_setup_error_is_reraised():
    error = Exception("connection reset by peer")
    source = _make_source(error, {"The DNS query name does not exist": None})

    with _patched_activity(source) as handle_mock:
        with pytest.raises(Exception, match="connection reset by peer"):
            await import_data_activity_sync(_inputs())

    handle_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_unparseable_config_routes_through_handler():
    # A corrupt / double-encoded stored config makes parse_config raise deterministically before
    # source setup. It must be treated as non-retryable instead of crash-looping on every attempt.
    error = ValueError("invalid literal for int() with base 10: 'not-an-int'")
    source = mock.MagicMock(spec=SimpleSource)
    source.parse_config.side_effect = error
    source.get_non_retryable_errors.return_value = {}

    with _patched_activity(source) as handle_mock:
        handle_mock.side_effect = NonRetryableException()
        with pytest.raises(NonRetryableException):
            await import_data_activity_sync(_inputs())

    handle_mock.assert_awaited_once()
    assert handle_mock.await_args.args[5] is error
    source.source_for_pipeline.assert_not_called()


@pytest.mark.asyncio
async def test_schema_deleted_mid_sync_routes_through_handler():
    # The schema can be deleted (or soft-deleted) between the job being created and this
    # activity's mid-run re-fetch of it, e.g. a user removes the table while its sync is in
    # flight. Every retry re-reads the same gone row, so it must be treated as non-retryable
    # instead of crash-looping on every attempt.
    error = ExternalDataSchema.DoesNotExist("ExternalDataSchema matching query does not exist.")
    source = mock.MagicMock(spec=SimpleSource)
    source.get_non_retryable_errors.return_value = {}

    with (
        _patched_activity(source) as handle_mock,
        mock.patch.object(module, "_get_external_data_schema", new=mock.AsyncMock(side_effect=error)),
    ):
        handle_mock.side_effect = NonRetryableException()
        with pytest.raises(NonRetryableException):
            await import_data_activity_sync(_inputs())

    handle_mock.assert_awaited_once()
    assert handle_mock.await_args.args[5] is error
    source.parse_config.assert_not_called()


@parameterized.expand(
    [
        ("pooler_cooldown", OperationalError, "server login has been failing, cached error: (server_login_retry)"),
        ("failover_read_only", InternalError, "cannot execute INSERT in a read-only transaction"),
    ]
)
@pytest.mark.asyncio
async def test_transient_app_db_error_in_setup_is_retryable_not_raw(
    _name: str, error_cls: type[Exception], message: str
):
    # The setup phase resolves this run's job/schema/source rows over the Django ORM (our own app
    # DB). A transient blip there — a PgBouncer server_login_retry cooldown, or a pooled connection
    # left on a demoted standby after a failover — raises before the source's error handling runs.
    # It's our infra, not the customer's source, so it must be re-raised as NonReportableError
    # (Temporal retries the whole activity and it self-heals) rather than escaping raw and being
    # stored verbatim as latest_error while minting error-tracking noise. Both driver strings are
    # wording the Postgres source's non-retryable map matches, so the message must not survive.
    error = error_cls(message)
    source = mock.MagicMock(spec=SimpleSource)

    with (
        _patched_activity(source) as handle_mock,
        mock.patch.object(module, "_get_external_data_job", new=mock.AsyncMock(side_effect=error)),
    ):
        with pytest.raises(NonReportableError) as exc_info:
            await import_data_activity_sync(_inputs())

    assert exc_info.value.__cause__ is error
    assert str(exc_info.value) == module.POSTHOG_DATABASE_UNAVAILABLE_MESSAGE
    handle_mock.assert_not_awaited()
    source.source_for_pipeline.assert_not_called()


@pytest.mark.asyncio
async def test_non_failover_internal_error_in_setup_is_not_hidden_as_a_platform_outage():
    # InternalError is the Django class for the failover case above, but also for corrupted data or
    # indexes and failed-transaction states. Those are deterministic defects: wrapping them as
    # NonReportableError would spend the retry budget on an error no retry fixes, and keep it out of
    # error tracking behind a message telling the customer nothing is wrong.
    error = InternalError('index "posthog_team_pkey" contains unexpected zero page at block 0')
    source = mock.MagicMock(spec=SimpleSource)

    with (
        _patched_activity(source),
        mock.patch.object(module, "_get_external_data_job", new=mock.AsyncMock(side_effect=error)),
    ):
        with pytest.raises(InternalError) as exc_info:
            await import_data_activity_sync(_inputs())

    assert exc_info.value is error


@pytest.mark.asyncio
async def test_source_classified_retryable_error_logged_as_warning_not_exception():
    # A rate-limit / transient error the source retries internally reaches _handle_import_error only
    # once those retries exhaust. Temporal retries the whole activity, so it must be logged at
    # warning (not aexception, which mints error-tracking noise) while still being re-raised. Logging
    # alone doesn't keep it out of error tracking though: the Temporal activity interceptor
    # (posthog_client.py) captures whatever exception type escapes the activity regardless of log
    # level, unless it's a NonReportableError — so the re-raise must wrap it as one, the same way
    # RESTClientRetryableError already does for REST sources.
    error = Exception("Mixpanel API error (retryable): status=429, url=https://data.mixpanel.com/api/2.0/export")
    source = mock.MagicMock(spec=SimpleSource)
    source.get_non_retryable_errors.return_value = {}
    source.get_retryable_errors.return_value = {"Mixpanel API error (retryable)"}

    logger = mock.MagicMock()
    logger.awarning = mock.AsyncMock()
    logger.aexception = mock.AsyncMock()
    logger.adebug = mock.AsyncMock()

    with mock.patch.object(module.SourceRegistry, "get_source", return_value=source):
        with pytest.raises(NonReportableError, match="retryable") as exc_info:
            await module._handle_import_error(mock.MagicMock(), logger, error)

    assert exc_info.value.__cause__ is error
    logger.awarning.assert_awaited_once()
    logger.aexception.assert_not_awaited()


@pytest.mark.asyncio
async def test_rest_client_non_retryable_error_routes_through_handler_without_source_opt_in():
    # RESTClientNonRetryableError is the REST engine's "retrying can never help" signal (a non-JSON
    # body on an otherwise-successful response). It must be honored by type even when the source's
    # get_non_retryable_errors doesn't list the message, so any REST-based source stops instead of
    # retrying the deterministic failure to the activity max and minting error-tracking noise.
    error = RESTClientNonRetryableError("Non-JSON response from https://api.example.com/v1/data/leads")
    source = mock.MagicMock(spec=SimpleSource)
    source.get_non_retryable_errors.return_value = {}
    source.get_retryable_errors.return_value = set()

    logger = mock.MagicMock()
    logger.awarning = mock.AsyncMock()
    logger.aexception = mock.AsyncMock()
    logger.adebug = mock.AsyncMock()

    with (
        mock.patch.object(module.SourceRegistry, "get_source", return_value=source),
        mock.patch.object(module, "handle_non_retryable_error", new=mock.AsyncMock()) as handle_mock,
    ):
        handle_mock.side_effect = NonRetryableException()
        with pytest.raises(NonRetryableException):
            await module._handle_import_error(mock.MagicMock(), logger, error)

    handle_mock.assert_awaited_once()
    assert handle_mock.await_args is not None
    assert handle_mock.await_args.args[5] is error
    logger.aexception.assert_not_awaited()


@pytest.mark.asyncio
async def test_http_404_routes_through_handler_without_source_opt_in():
    # A 404 from the shared REST engine's fallback raise_for_status() path means the configured
    # endpoint/resource doesn't exist — every retry hits the identical dead URL. It must be honored
    # by status code even when the source's get_non_retryable_errors doesn't list the message, so
    # any REST-based source stops instead of retrying to the activity max and minting error-tracking
    # noise on every attempt.
    error = HTTPError(
        "404 Client Error: Not Found for url: https://api.example.com/export", response=mock.MagicMock(status_code=404)
    )
    source = mock.MagicMock(spec=SimpleSource)
    source.get_non_retryable_errors.return_value = {}
    source.get_retryable_errors.return_value = set()

    logger = mock.MagicMock()
    logger.awarning = mock.AsyncMock()
    logger.aexception = mock.AsyncMock()
    logger.adebug = mock.AsyncMock()

    with (
        mock.patch.object(module.SourceRegistry, "get_source", return_value=source),
        mock.patch.object(module, "handle_non_retryable_error", new=mock.AsyncMock()) as handle_mock,
    ):
        handle_mock.side_effect = NonRetryableException()
        with pytest.raises(NonRetryableException):
            await module._handle_import_error(mock.MagicMock(), logger, error)

    handle_mock.assert_awaited_once()
    assert handle_mock.await_args is not None
    assert handle_mock.await_args.args[5] is error
    logger.aexception.assert_not_awaited()


@pytest.mark.asyncio
async def test_http_401_is_reraised_for_activity_retry():
    # A 401 can mean an access token expired mid-run — the REST engine's own auth layer re-mints
    # the token on the next attempt, so this must stay retryable rather than being swept into the
    # same non-retryable bucket as a 404 (which has no self-recovering path).
    error = HTTPError(
        "401 Client Error: Unauthorized for url: https://api.example.com/export",
        response=mock.MagicMock(status_code=401),
    )
    source = mock.MagicMock(spec=SimpleSource)
    source.get_non_retryable_errors.return_value = {}
    source.get_retryable_errors.return_value = set()

    logger = mock.MagicMock()
    logger.awarning = mock.AsyncMock()
    logger.aexception = mock.AsyncMock()
    logger.adebug = mock.AsyncMock()

    with (
        mock.patch.object(module.SourceRegistry, "get_source", return_value=source),
        mock.patch.object(module, "handle_non_retryable_error", new=mock.AsyncMock()) as handle_mock,
    ):
        with pytest.raises(HTTPError):
            await module._handle_import_error(mock.MagicMock(), logger, error)

    handle_mock.assert_not_awaited()
    logger.aexception.assert_awaited_once()


@pytest.mark.asyncio
async def test_rest_client_retryable_error_logged_as_warning_without_source_opt_in():
    # RESTClientRetryableError only escapes the shared REST engine's tenacity retry loop once its
    # own attempts (rate limits, transient 5xx, connection resets/timeouts) are exhausted. It must
    # be honored by type even when the source's get_retryable_errors doesn't list the message, so
    # every REST-based source gets this benign, self-recovering failure logged as a warning instead
    # of minting error-tracking noise.
    error = RESTClientRetryableError("HTTP 429 for https://api.example.com/v3/orders/")
    source = mock.MagicMock(spec=SimpleSource)
    source.get_non_retryable_errors.return_value = {}
    source.get_retryable_errors.return_value = set()

    logger = mock.MagicMock()
    logger.awarning = mock.AsyncMock()
    logger.aexception = mock.AsyncMock()
    logger.adebug = mock.AsyncMock()

    with mock.patch.object(module.SourceRegistry, "get_source", return_value=source):
        with pytest.raises(RESTClientRetryableError):
            await module._handle_import_error(mock.MagicMock(), logger, error)

    logger.awarning.assert_awaited_once()
    logger.aexception.assert_not_awaited()


@parameterized.expand(
    [
        ("operational_error", OperationalError, "query_wait_timeout"),
        ("interface_error", InterfaceError, "connection already closed"),
        # Raised by shared pipeline code (e.g. cdp_producer's should_run check) when a lookup
        # against PostHog's own app DB fails — already reclassified clear of wording a customer's
        # misconfigured source host would produce, so it must get the same NonReportableError
        # treatment as the Django exception types above, not fall through to the default branch.
        ("posthog_internal_database_error", PostHogInternalDatabaseError, "Failed to check hog function triggers"),
        # A pooled connection that outlived a primary failover now talks to a demoted standby, so
        # our own writes fail with SQLSTATE 25006. Django surfaces psycopg's ReadOnlySqlTransaction
        # as InternalError, a different DB-API class from the two above, so it needs its own arm
        # here. Without one it falls through to the source's non-retryable map, whose Postgres entry
        # matches the identical wording a customer's write-on-read view produces.
        ("read_only_transaction", InternalError, "cannot execute UPDATE in a read-only transaction"),
    ]
)
@pytest.mark.asyncio
async def test_app_db_connection_error_reraised_as_non_reportable(_name: str, error_cls: type[Exception], message: str):
    # A Django OperationalError/InterfaceError here can only come from a lookup against PostHog's
    # own app DB (e.g. resolving a team or CustomPropertySource for the person-property staging
    # hook) — sources talk to a customer's own database over a raw driver connection, never Django's
    # ORM. It's a transient connection-pool blip on our side (e.g. a PgBouncer query_wait_timeout
    # under load), so it must be re-raised as NonReportableError (like RESTClientRetryableError
    # above) rather than the bare exception, which the activity interceptor would still capture.
    error = error_cls(message)
    source = mock.MagicMock(spec=SimpleSource)
    source.get_non_retryable_errors.return_value = {}
    source.get_retryable_errors.return_value = set()

    logger = mock.MagicMock()
    logger.awarning = mock.AsyncMock()
    logger.aexception = mock.AsyncMock()
    logger.adebug = mock.AsyncMock()

    with mock.patch.object(module.SourceRegistry, "get_source", return_value=source):
        with pytest.raises(NonReportableError) as exc_info:
            await module._handle_import_error(mock.MagicMock(), logger, error)

    assert exc_info.value.__cause__ is error
    # The raw driver string is wording the source non-retryable maps match on, and the workflow
    # hands whatever escapes here to the finalization activity as the customer's latest_error.
    # Carry the platform message instead so neither can mistake our outage for their source.
    assert str(exc_info.value) == module.POSTHOG_DATABASE_UNAVAILABLE_MESSAGE
    logger.awarning.assert_awaited_once()
    logger.aexception.assert_not_awaited()


@pytest.mark.asyncio
async def test_non_failover_internal_error_falls_through_to_the_default_branch():
    # Same narrowing as the setup phase, at the mid-run handler: only the failover read-only case is
    # ours to retry silently. A corrupted index has to keep escaping so error tracking sees it.
    error = InternalError('index "posthog_team_pkey" contains unexpected zero page at block 0')
    source = mock.MagicMock(spec=SimpleSource)
    source.get_non_retryable_errors.return_value = {}
    source.get_retryable_errors.return_value = set()

    logger = mock.MagicMock()
    logger.awarning = mock.AsyncMock()
    logger.aexception = mock.AsyncMock()
    logger.adebug = mock.AsyncMock()

    with mock.patch.object(module.SourceRegistry, "get_source", return_value=source):
        with pytest.raises(InternalError) as exc_info:
            await module._handle_import_error(mock.MagicMock(), logger, error)

    assert exc_info.value is error
    logger.aexception.assert_awaited_once()


@pytest.mark.asyncio
async def test_transient_object_store_error_reraised_as_non_reportable():
    # A transient S3 credential-provider blip (IMDS/STS) talking to our own data-warehouse bucket,
    # e.g. while resetting the Delta table. It's retryable (Temporal retries the activity as usual),
    # but re-raising the bare OSError would still be captured by the activity interceptor, which
    # only skips reporting for NonReportableError — so it must be wrapped, not just logged at warning.
    error = OSError(
        "Operation not supported: the credential provider was not enabled: no providers in chain provided credentials"
    )
    source = mock.MagicMock(spec=SimpleSource)
    source.get_non_retryable_errors.return_value = {}
    source.get_retryable_errors.return_value = set()

    logger = mock.MagicMock()
    logger.awarning = mock.AsyncMock()
    logger.aexception = mock.AsyncMock()
    logger.adebug = mock.AsyncMock()

    with mock.patch.object(module.SourceRegistry, "get_source", return_value=source):
        with pytest.raises(NonReportableError) as exc_info:
            await module._handle_import_error(mock.MagicMock(), logger, error)

    assert exc_info.value.__cause__ is error
    logger.awarning.assert_awaited_once()
    logger.aexception.assert_not_awaited()


@pytest.mark.asyncio
async def test_schema_column_type_changed_routes_through_handler_without_source_opt_in():
    # SchemaColumnTypeChangedException is raised in shared pipeline code when incoming data can't be
    # cast into the stored Delta column type — a deterministic failure that only a reset and re-sync
    # fixes. It must be non-retryable by type for every source, not just the SQL sources that list
    # "Source column type changed" in get_non_retryable_errors, so non-SQL sources stop retrying it.
    error = SchemaColumnTypeChangedException(
        "Source column type changed: 'val' has values that no longer fit its stored type int32 "
        "(incoming data is now string). Reset and fully re-sync this table to adopt the new type."
    )
    source = mock.MagicMock(spec=SimpleSource)
    source.get_non_retryable_errors.return_value = {}
    source.get_retryable_errors.return_value = set()

    logger = mock.MagicMock()
    logger.awarning = mock.AsyncMock()
    logger.aexception = mock.AsyncMock()
    logger.adebug = mock.AsyncMock()

    # autospec enforces handle_non_retryable_error's real signature, so a call with the wrong
    # positional args (as this branch once had) fails here instead of only at runtime.
    with (
        mock.patch.object(module.SourceRegistry, "get_source", return_value=source),
        mock.patch.object(module, "handle_non_retryable_error", autospec=True) as handle_mock,
    ):
        handle_mock.side_effect = NonRetryableException()
        with pytest.raises(NonRetryableException):
            await module._handle_import_error(mock.MagicMock(), logger, error)

    handle_mock.assert_awaited_once()
    assert handle_mock.await_args is not None
    assert handle_mock.await_args.args[5] is error
    logger.aexception.assert_not_awaited()


@pytest.mark.asyncio
async def test_jsonpath_error_routes_through_handler_without_source_opt_in():
    # The shared REST engine compiles data_selector/cursor_path/resolve-param fields as JSONPath at
    # sync time, not manifest-validation time — a malformed path (e.g. a typo'd data_selector) raises
    # jsonpath_ng's JSONPathError deep in shared code. It's a fixed string, so it fails identically on
    # every retry regardless of source. It must be non-retryable by type, since jsonpath_ng's error
    # messages vary across parse/lex failure shapes and can't be matched via get_non_retryable_errors.
    error = JsonPathParserError("Parse error at 1:0 near token . (.)")
    source = mock.MagicMock(spec=SimpleSource)
    source.get_non_retryable_errors.return_value = {}
    source.get_retryable_errors.return_value = set()

    logger = mock.MagicMock()
    logger.awarning = mock.AsyncMock()
    logger.aexception = mock.AsyncMock()
    logger.adebug = mock.AsyncMock()

    with (
        mock.patch.object(module.SourceRegistry, "get_source", return_value=source),
        mock.patch.object(module, "handle_non_retryable_error", autospec=True) as handle_mock,
    ):
        handle_mock.side_effect = NonRetryableException()
        with pytest.raises(NonRetryableException):
            await module._handle_import_error(mock.MagicMock(), logger, error)

    handle_mock.assert_awaited_once()
    assert handle_mock.await_args is not None
    assert handle_mock.await_args.args[5] is error
    logger.aexception.assert_not_awaited()


@parameterized.expand(
    [
        # Raised in shared pipeline code (delta merge) when a keyless table syncs incrementally.
        ("primary_key", "Primary key required for incremental syncs"),
        # Raised by botocore when the object storage endpoint hostname is one it rejects (e.g. an
        # underscore in a self-hosted OBJECT_STORAGE_ENDPOINT). Deterministic for the deployment, so
        # it must stop retrying instead of looping the activity's budget and reporting every attempt.
        ("invalid_endpoint", "Invalid endpoint: http://posthog_objectstorage:19000"),
    ]
)
@pytest.mark.asyncio
async def test_shared_non_retryable_error_routes_through_handler_without_source_opt_in(_name: str, message: str):
    # These messages are raised in shared pipeline code, not any one source, and live in the shared
    # Any_Source_Errors dict. Each must be non-retryable in this in-activity handler for every source,
    # not just those that duplicate the message into their own get_non_retryable_errors.
    error = Exception(message)
    source = mock.MagicMock(spec=SimpleSource)
    source.get_non_retryable_errors.return_value = {}
    source.get_retryable_errors.return_value = set()

    logger = mock.MagicMock()
    logger.awarning = mock.AsyncMock()
    logger.aexception = mock.AsyncMock()
    logger.adebug = mock.AsyncMock()

    with (
        mock.patch.object(module.SourceRegistry, "get_source", return_value=source),
        mock.patch.object(module, "handle_non_retryable_error", autospec=True) as handle_mock,
    ):
        handle_mock.side_effect = NonRetryableException()
        with pytest.raises(NonRetryableException):
            await module._handle_import_error(mock.MagicMock(), logger, error)

    handle_mock.assert_awaited_once()
    assert handle_mock.await_args is not None
    assert handle_mock.await_args.args[5] is error
    logger.aexception.assert_not_awaited()


def _incremental_schema(*, is_incremental: bool, lookback_seconds: int | None) -> mock.MagicMock:
    schema = mock.MagicMock()
    schema.should_use_incremental_field = True
    schema.is_incremental = is_incremental
    schema.incremental_field_type = IncrementalFieldType.Timestamp
    schema.incremental_field_lookback_seconds = lookback_seconds
    schema.incremental_field_earliest_value = None
    schema.row_filters = None
    schema.api_version = None
    schema.sync_type_config = {
        "incremental_field_last_value": "2026-06-14T15:33:31.802833",
        "incremental_field_type": "timestamp",
    }
    return schema


@contextlib.contextmanager
def _patched_activity_reaching_run(source_mock, schema, api_version=None):
    model = mock.MagicMock()
    model.pipeline.source_type = "MongoDB"
    model.pipeline.job_inputs = {}
    model.pipeline.api_version = api_version
    model.folder_path = mock.Mock(return_value="dataset")

    with (
        mock.patch.object(module, "tag_queries"),
        mock.patch.object(module, "report_heartbeat_timeout"),
        mock.patch.object(module, "Heartbeater", return_value=_FakeAsyncCM()),
        mock.patch.object(module, "ShutdownMonitor", return_value=_FakeAsyncCM()),
        mock.patch.object(module, "setup_row_tracking", new=mock.AsyncMock()),
        mock.patch.object(module, "_get_external_data_job", new=mock.AsyncMock(return_value=model)),
        mock.patch.object(module, "_get_external_data_schema", new=mock.AsyncMock(return_value=schema)),
        mock.patch.object(module, "ExternalDataSourceType", return_value="MongoDB"),
        mock.patch.object(module, "bind_job_context"),
        mock.patch.object(module, "trim_source_job_inputs", new=mock.AsyncMock()),
        mock.patch.object(module, "database_sync_to_async_pool", new=_passthrough),
        mock.patch.object(module.SourceRegistry, "is_registered", return_value=True),
        mock.patch.object(module.SourceRegistry, "get_source", return_value=source_mock),
        mock.patch.object(module, "_run", new=mock.AsyncMock(return_value=mock.sentinel.run_result)),
    ):
        yield


def _inputs_no_reset() -> ImportDataActivityInputs:
    return ImportDataActivityInputs(
        team_id=1,
        schema_id=uuid.uuid4(),
        source_id=uuid.uuid4(),
        run_id=str(uuid.uuid4()),
        reset_pipeline=False,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "is_incremental,expected_last_value,expected_before_lookback",
    [
        (True, datetime(2026, 6, 14, 14, 33, 31, 802833), datetime(2026, 6, 14, 15, 33, 31, 802833)),
        (False, datetime(2026, 6, 14, 15, 33, 31, 802833), None),
    ],
)
async def test_incremental_lookback_shifts_query_value_not_stored_watermark(
    is_incremental, expected_last_value, expected_before_lookback
):
    source = mock.MagicMock(spec=SimpleSource)
    source.parse_config.return_value = {}
    source.source_for_pipeline.return_value = mock.MagicMock()
    schema = _incremental_schema(is_incremental=is_incremental, lookback_seconds=3600)

    with _patched_activity_reaching_run(source, schema):
        await import_data_activity_sync(_inputs_no_reset())

    _, source_inputs = source.source_for_pipeline.call_args.args
    assert source_inputs.db_incremental_field_last_value == expected_last_value
    assert schema.sync_type_config["incremental_field_last_value"] == "2026-06-14T15:33:31.802833"
    # The unshifted cursor travels alongside the shifted one. A consumer needs both to tell overlap
    # from new ground, and capturing it after the shift would make them equal and silently disarm
    # that rule with every test still passing.
    assert source_inputs.db_incremental_field_last_value_before_lookback == expected_before_lookback


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "schema_override,pinned,expected",
    [
        (None, "2020-01-01", "2020-01-01"),  # a stored pin is honored verbatim
        (None, None, "vdefault"),  # no pin resolves to the source's default_version
        ("2021-05-05", "2020-01-01", "2021-05-05"),  # a user-managed schema override wins over the source pin
    ],
)
async def test_pinned_api_version_is_resolved_into_source_inputs(schema_override, pinned, expected):
    source = mock.MagicMock(spec=SimpleSource)
    source.parse_config.return_value = {}
    source.source_for_pipeline.return_value = mock.MagicMock()
    source.resolve_api_version = lambda p: p or "vdefault"
    schema = _incremental_schema(is_incremental=False, lookback_seconds=None)
    schema.api_version = schema_override

    with _patched_activity_reaching_run(source, schema, api_version=pinned):
        await import_data_activity_sync(_inputs_no_reset())

    _, source_inputs = source.source_for_pipeline.call_args.args
    assert source_inputs.api_version == expected


def _fanout_child_schema() -> mock.MagicMock:
    schema = mock.MagicMock()
    schema.name = "issue_events"
    return schema


def _fanout_source() -> mock.MagicMock:
    source = mock.MagicMock(spec=SimpleSource)
    source.get_required_parent_schemas.return_value = ["issues"]
    return source


def _parent(
    should_sync: bool,
    initial_sync_complete: bool,
    sync_type: str = ExternalDataSchema.SyncType.INCREMENTAL,
) -> mock.MagicMock:
    parent = mock.MagicMock()
    parent.should_sync = should_sync
    parent.initial_sync_complete = initial_sync_complete
    parent.sync_type = sync_type
    parent.is_incremental = sync_type == ExternalDataSchema.SyncType.INCREMENTAL
    return parent


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "parent",
    [None, "disabled", "never_synced", "append_mode", "cdc_mode"],
)
async def test_unusable_parent_falls_back_to_the_api_path(parent):
    # A child enabled without its parent is a config that syncs today, so turning the flag on
    # must leave it working: fall back to the parent API instead of failing the run. Append and
    # CDC parents hold more than one row per key, so the reader must not stream them either.
    parent_obj = None
    if parent == "disabled":
        parent_obj = _parent(should_sync=False, initial_sync_complete=True)
    elif parent == "never_synced":
        parent_obj = _parent(should_sync=True, initial_sync_complete=False)
    elif parent == "append_mode":
        parent_obj = _parent(should_sync=True, initial_sync_complete=True, sync_type=ExternalDataSchema.SyncType.APPEND)
    elif parent == "cdc_mode":
        parent_obj = _parent(should_sync=True, initial_sync_complete=True, sync_type=ExternalDataSchema.SyncType.CDC)

    with (
        mock.patch.object(module, "database_sync_to_async_pool", new=_passthrough),
        mock.patch.object(module, "is_fanout_warehouse_reuse_enabled", return_value=True),
        mock.patch.object(module, "get_schema_if_exists", return_value=parent_obj),
    ):
        result = await module._warehouse_parent_reuse_available(
            _fanout_source(), _fanout_child_schema(), uuid.uuid4(), 1, mock.AsyncMock()
        )

    assert result is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "sync_type",
    [ExternalDataSchema.SyncType.INCREMENTAL, ExternalDataSchema.SyncType.FULL_REFRESH],
)
async def test_synced_parent_uses_the_warehouse_path(sync_type):
    # Merge and full-refresh parents both hold one row per key, so both drive the reader.
    with (
        mock.patch.object(module, "database_sync_to_async_pool", new=_passthrough),
        mock.patch.object(module, "is_fanout_warehouse_reuse_enabled", return_value=True),
        mock.patch.object(
            module,
            "get_schema_if_exists",
            return_value=_parent(should_sync=True, initial_sync_complete=True, sync_type=sync_type),
        ),
    ):
        result = await module._warehouse_parent_reuse_available(
            _fanout_source(), _fanout_child_schema(), uuid.uuid4(), 1, mock.AsyncMock()
        )

    assert result is True


@pytest.mark.asyncio
async def test_fanout_gate_result_threaded_into_source_inputs():
    # The gate's decision must reach the source via SourceInputs — if this wiring drops,
    # every child silently falls back to re-pulling the parent API with the flag on.
    source = mock.MagicMock(spec=SimpleSource)
    source.parse_config.return_value = {}
    source.get_required_parent_schemas.return_value = ["issues"]
    source.source_for_pipeline.return_value = mock.MagicMock()
    source.resolve_api_version = lambda p: p or "v1"
    schema = _incremental_schema(is_incremental=False, lookback_seconds=None)

    with (
        _patched_activity_reaching_run(source, schema),
        mock.patch.object(module, "is_fanout_warehouse_reuse_enabled", return_value=True),
        mock.patch.object(
            module, "get_schema_if_exists", return_value=_parent(should_sync=True, initial_sync_complete=True)
        ),
    ):
        await import_data_activity_sync(_inputs_no_reset())

    _, source_inputs = source.source_for_pipeline.call_args.args
    assert source_inputs.fanout_warehouse_reuse is True


@pytest.mark.asyncio
async def test_parent_gate_inert_when_flag_disabled():
    with (
        mock.patch.object(module, "database_sync_to_async_pool", new=_passthrough),
        mock.patch.object(module, "is_fanout_warehouse_reuse_enabled", return_value=False),
        mock.patch.object(module, "get_schema_if_exists") as schema_lookup,
    ):
        result = await module._warehouse_parent_reuse_available(
            _fanout_source(), _fanout_child_schema(), uuid.uuid4(), 1, mock.AsyncMock()
        )

    assert result is False
    schema_lookup.assert_not_called()


@pytest.mark.asyncio
async def test_parent_gate_inert_for_sources_without_requirements():
    source = mock.MagicMock(spec=SimpleSource)
    source.get_required_parent_schemas.return_value = []

    with mock.patch.object(module, "is_fanout_warehouse_reuse_enabled") as flag_check:
        result = await module._warehouse_parent_reuse_available(
            source, _fanout_child_schema(), uuid.uuid4(), 1, mock.AsyncMock()
        )

    assert result is False
    flag_check.assert_not_called()


# Credentials the integration service holds are PostHog's own — the OAuth app secrets and API keys
# we own, not anything a customer configured. Every failure state it has is therefore ours, and
# every one of them ends on its own (a key in recovery is re-provisioned, a missing key is added, an
# unreachable service comes back). The classification has to reflect both facts: retry, and never
# reach handle_non_retryable_error, which disables the schema and makes the customer re-enable a
# sync they never broke. Without this, one key going into recovery would disable every sync of that
# source type across every customer.
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error,reported",
    [
        (SecretInRecoveryError("HUBSPOT_APP_CLIENT_SECRET"), False),
        (SecretMissingError("HUBSPOT_APP_CLIENT_SECRET"), True),
        (SecretMissingError("HUBSPOT_APP_CLIENT_SECRET", disabled_reason="unconfigured"), True),
        (IntegrationServiceMisconfiguredError("INTEGRATION_SERVICE_URL"), True),
        (IntegrationServiceUnreachableError("connection refused"), False),
    ],
)
async def test_integration_secret_failure_retries_without_disabling_the_schema(error, reported):
    source = mock.MagicMock(spec=SimpleSource)
    source.get_non_retryable_errors.return_value = {}
    source.get_retryable_errors.return_value = set()

    logger = mock.MagicMock()
    logger.awarning = mock.AsyncMock()
    logger.aexception = mock.AsyncMock()
    logger.adebug = mock.AsyncMock()

    with (
        mock.patch.object(module.SourceRegistry, "get_source", return_value=source),
        mock.patch.object(module, "handle_non_retryable_error", new=mock.AsyncMock()) as handle_mock,
        mock.patch.object(module, "capture_exception") as capture_mock,
    ):
        with pytest.raises(NonReportableError) as exc_info:
            await module._handle_import_error(mock.MagicMock(), logger, error)

    # Never disabled: that is the behaviour this whole branch exists to prevent.
    handle_mock.assert_not_awaited()
    assert exc_info.value.__cause__ is error

    # The customer reads a message that names no internal credential and asks nothing of them.
    assert str(exc_info.value) == module.INTEGRATION_CREDENTIAL_UNAVAILABLE_MESSAGE
    assert "HUBSPOT_APP_CLIENT_SECRET" not in str(exc_info.value)
    assert "INTEGRATION_SERVICE_URL" not in str(exc_info.value)

    # Reported only when a person has to act. NonReportableError already keeps the activity
    # interceptor from capturing on escape, so an explicit capture is the only way these reach
    # error tracking at all — and the only way the ones that don't need a human stay quiet.
    assert capture_mock.call_count == (1 if reported else 0)
    if reported:
        assert capture_mock.call_args.args[0] is error
        logger.aexception.assert_awaited_once()
    else:
        logger.awarning.assert_awaited_once()
        logger.aexception.assert_not_awaited()


# The bare-404 rule below this branch reads a 404 as "the customer's configured endpoint is gone"
# and stops the sync for good. A misrouted INTEGRATION_SERVICE_URL answers 404 too, so ordering
# decides whether our own deploy error is charged to the customer. The client wraps its transport
# failures precisely so the two can't collide; this pins the ordering that keeps it true anyway.
@pytest.mark.asyncio
async def test_integration_failure_is_classified_before_the_bare_404_rule():
    error = IntegrationServiceUnreachableError("404 Client Error: Not Found for url: http://integration-service")
    source = mock.MagicMock(spec=SimpleSource)
    source.get_non_retryable_errors.return_value = {}
    source.get_retryable_errors.return_value = set()

    logger = mock.MagicMock()
    logger.awarning = mock.AsyncMock()
    logger.aexception = mock.AsyncMock()
    logger.adebug = mock.AsyncMock()

    with (
        mock.patch.object(module.SourceRegistry, "get_source", return_value=source),
        mock.patch.object(module, "handle_non_retryable_error", new=mock.AsyncMock()) as handle_mock,
        mock.patch.object(module, "capture_exception"),
    ):
        with pytest.raises(NonReportableError):
            await module._handle_import_error(mock.MagicMock(), logger, error)

    handle_mock.assert_not_awaited()


# The retry budget can run out while the credential is still unavailable. When it does, the
# customer-facing message above becomes the run's `internal_error`, and finalization
# (update_external_data_job_model) matches that text against every non-retryable pattern — a
# case-insensitive substring test. A match there would disable the schema, which is the exact
# outcome the whole classification exists to avoid, arriving by the back door.
#
# So the message is not free text: no pattern may be a substring of it. This sweeps every
# registered source rather than the shared dict alone, because a source-specific pattern
# (a bare word like "unavailable") would do it just as well.
@parameterized.expand(
    [
        ("integration_credential", "INTEGRATION_CREDENTIAL_UNAVAILABLE_MESSAGE"),
        ("posthog_database", "POSTHOG_DATABASE_UNAVAILABLE_MESSAGE"),
    ]
)
def test_the_customer_facing_message_matches_no_non_retryable_pattern(_name: str, message_attr: str):
    from products.warehouse_sources.backend.temporal.data_imports.external_data_job import Any_Source_Errors
    from products.warehouse_sources.backend.temporal.data_imports.sources import SourceRegistry
    from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import error_message_matches

    patterns = set(Any_Source_Errors.keys())
    for source in SourceRegistry.get_all_sources().values():
        patterns |= set(source.get_non_retryable_errors().keys())

    # Guard the guard: if the registry ever fails to load, an empty pattern set would make this
    # test pass while checking nothing.
    assert len(patterns) > 20, f"expected the source registry to contribute patterns, got {len(patterns)}"

    message = getattr(module, message_attr)
    offenders = [p for p in patterns if error_message_matches(message, [p])]
    assert offenders == [], (
        f"These non-retryable patterns match {message_attr}, so an exhausted "
        f"retry budget would disable the customer's schema: {offenders}"
    )
