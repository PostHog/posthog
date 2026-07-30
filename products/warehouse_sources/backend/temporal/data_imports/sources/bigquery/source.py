from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
    SourceFieldFileUploadConfig,
    SourceFieldFileUploadJsonFormatConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldSwitchGroupConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.bigquery.bigquery import (
    BIGQUERY_DATASET_NOT_FOUND_ERROR,
    BIGQUERY_INVALID_IDENTIFIER_ERROR,
    BIGQUERY_RESOURCES_EXCEEDED_ERROR,
    BIGQUERY_TOKEN_RESPONSE_ERROR,
    BigQueryImplementation,
    build_destination_table_prefix,
    validate_bigquery_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.base import SQLSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import BigQuerySourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType

__all__ = ["BigQuerySource", "build_destination_table_prefix"]

_BIGQUERY_IMPLEMENTATION = BigQueryImplementation()


@SourceRegistry.register
class BigQuerySource(SQLSource[BigQuerySourceConfig]):
    api_docs_url = "https://cloud.google.com/bigquery/docs/release-notes"

    @property
    def get_implementation(self) -> BigQueryImplementation:
        return _BIGQUERY_IMPLEMENTATION

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.BIGQUERY

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "PermissionDenied: 403 request failed": "BigQuery permission denied. Please check that your service account has the necessary permissions.",
            # OAuth2 error code returned by Google's token endpoint when the service account grant
            # is rejected — a rotated/revoked private key ("Invalid JWT Signature") or a deleted
            # service account ("account not found"). Raised as a `RefreshError` while refreshing the
            # token, so it surfaces on every BigQuery call rather than at a single site. Retrying
            # can't recover invalid credentials; the user must upload a new key file. Matched on the
            # stable `invalid_grant` code rather than `RefreshError`, which can also wrap transient
            # token-endpoint failures that should stay retryable.
            "invalid_grant": "Your BigQuery service account credentials were rejected by Google. The key may have been rotated or revoked, or the service account deleted. Please upload a new Google Cloud JSON key file.",
            # Raised from `bigquery_client` when `service_account.Credentials.from_service_account_info`
            # parses the uploaded key file's `private_key`. A truncated or corrupted PEM body (wrong
            # padding, stray characters, copy-paste damage) makes the `cryptography` backend reject it
            # as a `ValueError: Unable to load PEM file. ... InvalidData(InvalidPadding)`. The key can't
            # be repaired by retrying — the user must re-upload an intact JSON key file. Matched on the
            # stable "Unable to load PEM file" wording rather than the volatile InvalidData detail.
            "Unable to load PEM file": "We couldn't read the private key in your Google Cloud JSON key file — it appears truncated or corrupted. Please download a fresh service account key from Google Cloud and re-upload the JSON file.",
            # Writing query results into the `__posthog_import_...` temp tables PostHog creates
            # (`WRITE_TRUNCATE` in `_run_destination_query_with_job_retry`, on incremental / view /
            # row-filtered reads) needs write access on the dataset those tables live in. When the
            # service account only has read access, BigQuery rejects the copy with "Permission
            # bigquery.tables.update denied on table <temp id>". This is a distinct problem from the
            # read-side denials the "Access Denied:" key below covers — and that key would match this
            # message first and misdirect the customer to grant *read* access (Data Viewer), which
            # can't fix a *write* failure. Keep this key above "Access Denied:" so the write-specific
            # guidance wins. Deterministic IAM config problem — retrying can't grant the permission.
            # Matched on the stable permission name (also covers `bigquery.tables.updateData`), not
            # the volatile temp-table id.
            "bigquery.tables.update": "BigQuery denied write access to a temporary table PostHog creates in your dataset. PostHog copies query results into temporary tables before reading them, so read access alone isn't enough. Please grant your service account write access (for example the BigQuery Data Editor role) on the dataset where these temporary tables are created — your main dataset, or the temporary dataset if you configured one — then reconnect the source.",
            # Creating the `__posthog_import_...` temp tables (the `WRITE_TRUNCATE` destination in
            # `_run_destination_query_with_job_retry`, on incremental / view / row-filtered reads) needs
            # create access on the dataset those tables live in. When the service account only has read
            # access, BigQuery rejects it with "Permission bigquery.tables.create denied on dataset
            # <id>" — the create-side twin of the `bigquery.tables.update` denial above. Like that key,
            # it also starts with "Access Denied:", so it must sit above that key or the customer is told
            # to grant *read* access (Data Viewer), which can't fix a *create* failure. Deterministic IAM
            # config problem — retrying can't grant the permission. Matched on the stable permission name,
            # not the volatile dataset id.
            "bigquery.tables.create": "BigQuery denied permission to create a temporary table PostHog needs in your dataset. PostHog copies query results into temporary tables before reading them, so read access alone isn't enough. Please grant your service account permission to create tables (for example the BigQuery Data Editor role) on the dataset where these temporary tables are created — your main dataset, or the temporary dataset if you configured one — then reconnect the source.",
            # BigQuery rejects query-job creation (POST .../jobs) with "Access Denied: Project <id>:
            # User does not have bigquery.jobs.create permission in project <id>." when the service
            # account can read the data but can't run query jobs in the project the jobs bill to. We
            # create query jobs throughout the sync (primary-key discovery, row counts, temp-table
            # copies), so this fails before any rows are read. Like the tables.update key above, the
            # generic "Access Denied:" key would match first and misdirect the customer to grant
            # *read* access (Data Viewer), which can't grant job creation — so keep this key above it.
            # Deterministic IAM config problem; retrying can't grant the permission. Matched on the
            # stable permission name, not the volatile project id.
            "bigquery.jobs.create": "BigQuery denied your service account permission to run query jobs — it's missing the bigquery.jobs.create permission on the project it queries. Read access alone isn't enough, because PostHog runs query jobs to sync your data. Please grant your service account permission to run jobs (for example the BigQuery Job User role) on that project, then reconnect the source.",
            # BigQuery prefixes every IAM/permission failure with "Access Denied:" — e.g.
            # "Access Denied: Table <id>: Permission bigquery.tables.getData denied on table <id>
            # (or it may not exist).". The matched string above only covers the REST client's
            # "PermissionDenied: 403 request failed" wording; the Storage Read API raises a
            # google.api_core PermissionDenied whose `str()` is "403 Access Denied: ..." instead,
            # so it slips through and retries forever. These are config/permission problems on the
            # customer's service account — retrying can't resolve them; the user must grant the
            # missing permission (or the referenced table/dataset must exist).
            "Access Denied:": "BigQuery denied access to a table or dataset. Please ensure your service account has read access (the bigquery.tables.getData permission, e.g. the BigQuery Data Viewer role) on every dataset and table you're syncing, then reconnect the source.",
            # Federated/external BigQuery tables (e.g. a Cloud SQL connection) read through to the
            # underlying database. When that database's role lacks read access, BigQuery surfaces the
            # upstream ACL failure inside a 400 BadRequest, e.g. "Error while reading data ...
            # Failed to fetch row from PostgreSQL server. Error: ERROR:  permission denied for table
            # <name>". This is a deterministic permission problem on the customer's data source —
            # retrying can't resolve it; the user must grant the federation's database user read
            # access. The "Access Denied:"/403 keys above only cover BigQuery's own IAM wording, so
            # this lowercase upstream form slips through and retries forever.
            "permission denied for table": 'BigQuery couldn\'t read a federated table because the underlying database denied permission ("permission denied for table"). Please grant the database user behind your BigQuery connection read access to the table, then reconnect the source.',
            # BigQuery raises this 400 BadRequest when it can't compile a view it's importing, e.g.
            # "Invalid table-valued function EXTERNAL_QUERY; failed to parse view '<dataset>.<view>'".
            # For a federated EXTERNAL_QUERY view this means the upstream schema drifted away from the
            # view definition — a column the view selects was renamed or dropped in the source database
            # ("prepare statement failed. Error: ERROR:  column \"x\" does not exist"). It's a
            # deterministic mismatch between the customer's view and their data; retrying can't recover
            # it — they must fix the view definition or restore the column. The "permission denied for
            # table" / "Access Denied:" keys only cover federation ACL failures, so this slips through
            # and retries forever. Matched on BigQuery's stable "failed to parse view" wording rather
            # than the volatile view/column names.
            "failed to parse view": "BigQuery couldn't read a view it was importing because its definition no longer matches the underlying data — a column it references was renamed or removed (for federated query views, in the upstream database). Please update the view definition (or restore the column), then reconnect the source.",
            # Raised from the Storage Read API's `create_read_session` (see `get_rows` in
            # `bigquery.py`) when the service account is missing the `bigquery.readsessions.create`
            # permission the Read API requires. The google.api_core PermissionDenied stringifies as
            # "403 request failed: the user does not have 'bigquery.readsessions.create' permission
            # for 'projects/<id>'", so neither the "Access Denied:"/403 keys nor "PermissionDenied:
            # 403 request failed" cover this wording, and it retries forever. This is an IAM config
            # problem on the customer's service account — retrying can't resolve it; the user must
            # grant the missing permission (e.g. the BigQuery Read Session User role). Matched on the
            # stable permission name rather than the volatile project id.
            "bigquery.readsessions.create": "BigQuery denied access to the Storage Read API: your service account is missing the bigquery.readsessions.create permission. Please grant it (for example via the BigQuery Read Session User role) on the project you're syncing, then reconnect the source.",
            # Raised while reading rows from a Storage Read API stream (see `get_rows` in `bigquery.py`)
            # when the service account can create a read session but lacks `bigquery.readsessions.getData`,
            # the separate permission required to pull data from the session's streams. The
            # google.api_core PermissionDenied stringifies as "there was an error operating on
            # 'projects/<id>/.../streams/<id>': the user does not have 'bigquery.readsessions.getData'
            # permission for '...'", so neither the "Access Denied:"/403 keys nor the readsessions.create
            # key cover this wording, and it retries forever. Same IAM config fix as create — the BigQuery
            # Read Session User role grants both. Matched on the stable permission name rather than the
            # volatile session/stream ids.
            "bigquery.readsessions.getData": "BigQuery denied access to the Storage Read API: your service account is missing the bigquery.readsessions.getData permission needed to read data from a read session. Please grant it (for example via the BigQuery Read Session User role) on the project you're syncing, then reconnect the source.",
            # Raised from query jobs when the configured dataset/table doesn't exist in the location
            # we query — the dataset was deleted or renamed, or it lives in a different region than the
            # one we run against. The google exception stringifies as "404 Not found: Dataset ... was
            # not found in location US", so match the stable phrasing here. Retrying can't recover —
            # the user must fix the dataset or set the correct region.
            "was not found in location": BIGQUERY_DATASET_NOT_FOUND_ERROR,
            # Schema discovery (`get_columns`) re-raises the same 404 as `BigQueryDatasetNotFoundError`
            # carrying this exact wording (so the create/validate path shows it instead of the raw
            # 404). Match it here too so the discovery activity treats it as non-retryable.
            BIGQUERY_DATASET_NOT_FOUND_ERROR: BIGQUERY_DATASET_NOT_FOUND_ERROR,
            # A syntactically invalid project/dataset ID (e.g. a value carrying parentheses like
            # "(default)") is rejected as a 400 "Invalid dataset ID ..." / "Invalid project ID ...".
            # Schema discovery re-raises it as `BigQueryInvalidIdentifierError` carrying the friendly
            # wording, so match that here, plus the raw 400 phrasings for occurrences elsewhere in the
            # sync. Deterministic config error — retrying never succeeds until the id is corrected.
            BIGQUERY_INVALID_IDENTIFIER_ERROR: BIGQUERY_INVALID_IDENTIFIER_ERROR,
            "Invalid dataset ID": BIGQUERY_INVALID_IDENTIFIER_ERROR,
            "Invalid project ID": BIGQUERY_INVALID_IDENTIFIER_ERROR,
            # Raised as a 400 BadRequest from job creation (POST .../jobs) when the location the
            # client runs in — the custom region from the source form, or the dataset's own location
            # auto-detected in `connect` — isn't a region BigQuery can run query jobs in, e.g.
            # "Location ua does not support this operation.". It's a deterministic config problem:
            # retrying the same location always fails identically, so the user must set a valid
            # BigQuery region. The "was not found in location" key only covers a dataset missing from
            # a queried region, not an unsupported region, so this slips through and retries forever.
            # Matched on the stable wording rather than the volatile location code.
            "does not support this operation": "BigQuery rejected the dataset region this source runs in — it isn't a location BigQuery can run queries in. Please set a valid BigQuery region (for example US, EU, or us-east1) in your source configuration, then reconnect the source.",
            # Raised from `bq_client.get_table(...)` in `_build_source_response` when the table being
            # synced no longer exists at sync time — it was deleted or renamed in BigQuery (common with
            # dbt-managed datasets) after schema discovery selected it. The google exception stringifies
            # as "... Not found: Table <project>:<dataset>.<table>", which the "was not found in
            # location" key (dataset-region 404s) doesn't cover, so it slips through and retries forever.
            # Retrying within the sync's window can't recover a missing table; the user must restore or
            # rename it back, or remove it from the sync. Matched on the stable "Not found: Table"
            # wording rather than the volatile table id.
            "Not found: Table": "BigQuery couldn't find a table this source is syncing — it was deleted or renamed after the source was set up. Restore or rename the table in BigQuery, or remove it from this source's synced tables, then re-enable the source.",
            # Raised from `bq_client.get_table(...)` in `_build_source_response` (and other calls) when
            # the GCP project the source references no longer exists — it was deleted, or the Project ID
            # in the service account key file (or the configured dataset project) is wrong. The google
            # exception stringifies as "... Project <id> is not found. Make sure it references valid GCP
            # project that hasn't been deleted.", which the table/dataset "Not found" keys don't cover, so
            # it slips through and retries forever. Retrying can't conjure a missing project; the user
            # must fix the project reference. Matched on the stable guidance wording rather than the
            # volatile project id that appears earlier in the message.
            "Make sure it references valid GCP project": "BigQuery couldn't find the Google Cloud project this source references — it may have been deleted, or the Project ID in your service account key file (or the configured dataset project) may be incorrect. Verify the project exists in Google Cloud and correct the project details in your source configuration, then reconnect the source.",
            # Raised by google-cloud-bigquery's `TableReference.from_string` when a table id has
            # more than the three `project.dataset.table` components. This happens when the
            # Dataset ID field is set to `project.dataset` instead of just `dataset` — we then
            # build `project.project.dataset.table` and the client rejects it. It's a deterministic
            # config error, so retrying never succeeds.
            "table_id must be a fully-qualified ID in standard SQL format": "Your BigQuery Dataset ID looks misconfigured — it should be just the dataset name (for example `analytics`), not `project.dataset`. Please update the Dataset ID in your source configuration.",
            # Forbidden 403 with `reason: billingNotEnabled` — the customer's Google Cloud project
            # has billing disabled (BigQuery sandbox mode), so any query job is rejected before it
            # runs. There's nothing we can do but stop retrying until they enable billing.
            "Billing has not been enabled for this project": "BigQuery billing is not enabled for your Google Cloud project. Enable billing in the Google Cloud console (https://console.cloud.google.com/billing), then resume this source.",
            # Raised from the shared `evolve_pyarrow_schema` in `pipelines/pipeline/utils.py`
            # when an integer column's source type was widened (e.g. `INT64` widened from a
            # narrower numeric type) after the destination table was created with the narrower
            # type. Delta Lake can't widen an existing column in place, so retrying won't help —
            # the table must be reset and fully re-synced to adopt the new type.
            "Source column type changed": "A column's type changed in your source database (for example an integer column was widened to bigint) and no longer fits the type we stored. We can't widen an existing column in place — please reset and fully re-sync this table to adopt the new type.",
            # Raised from `BigQueryImplementation.get_columns` when the service-account OAuth
            # token endpoint returns a non-JSON-object 200 (bad `token_uri`, or an intercepting
            # proxy). Authentication can't succeed until the key file is fixed, so retrying just
            # hammers the endpoint and spams error tracking.
            BIGQUERY_TOKEN_RESPONSE_ERROR: "We couldn't authenticate with BigQuery — Google's OAuth token endpoint returned an unexpected response. Please re-upload your service account key file and verify its token_uri.",
            # A service-account key whose `token_uri` points at an ngrok tunnel that's offline:
            # google-auth POSTs the token request and gets back ngrok's HTML error page instead of
            # an OAuth JSON response, so it raises a `RefreshError` carrying that page. Google's real
            # token endpoint is never fronted by ngrok, so this is a misconfigured `token_uri` — the
            # user must fix their key file; retrying can't recover. Matched on ngrok's stable
            # offline-endpoint code rather than the volatile tunnel subdomain in the page.
            "ERR_NGROK_3200": "We couldn't authenticate with BigQuery — your service account key's token_uri points at an offline endpoint, not Google's OAuth token endpoint. Please re-upload your service account key file and verify its token_uri.",
            # Raised as a `Forbidden` (403, reason `quotaExceeded`) when the customer's BigQuery
            # project hits an administrator-configured custom cost control, e.g. "Custom quota
            # exceeded: Your usage exceeded the custom quota for QueryUsagePerDay, which is set by
            # your administrator.". This is a deliberate spend cap on the customer's GCP project,
            # not a transient limit — retrying within the sync's retry window can't recover it (the
            # cap resets on Google's daily schedule), so it just hammers the endpoint and spams
            # error tracking. We match the stable "Custom quota exceeded" wording, which is distinct
            # from transient rate-limit quota errors ("Quota exceeded: ..." / reason
            # `rateLimitExceeded`) that must stay retryable.
            "Custom quota exceeded": "Your BigQuery project hit a custom usage quota set by your administrator (for example QueryUsagePerDay). Raise the custom cost-control quota in Google Cloud, or reduce how much data you're syncing, then re-enable the source.",
            # Raised from the Storage Read API's `create_read_session` (see `get_rows` in
            # `bigquery.py`) when the source table uses change data capture with a `max_staleness`
            # window and has pending upserts older than that window. The Storage Read API can't
            # apply CDC changes on the fly — only GoogleSQL queries and BigQuery's background apply
            # jobs do — so it rejects the read as a google.api_core InvalidArgument whose str() is
            # "400 request failed: The table has un-applied upsert data that is not fresh enough to
            # meet table's max_staleness.". Retrying within the sync's window can't recover it: the
            # pending changes are applied on BigQuery's own schedule, not ours, so it just hammers
            # the Read API and spams error tracking until a later sync finds the table caught up.
            # Matched on the stable freshness phrasing rather than the volatile table id.
            "un-applied upsert data that is not fresh enough": "BigQuery couldn't read this table through the Storage Read API because it uses change data capture and has pending upserts that haven't been applied within the table's max_staleness window. This usually clears once BigQuery applies the pending changes, so a later sync should recover. If it persists, lower the table's max_staleness or run a query against the table in BigQuery to apply the changes.",
            # BigQuery aborts a query job with "Resources exceeded during query execution" (reason
            # `resourcesExceeded`) when the query can't run within a worker's memory — heavy sorts or
            # analytic OVER() clauses over a large table or view. We copy incremental / view /
            # row-filtered reads into a temp table before reading them (`_run_destination_query_with_job_retry`
            # in `bigquery.py`), and that copy carries the offending shape, so it fails here. It's a
            # deterministic property of the customer's data volume and query shape — retrying the same
            # query always fails identically (Google's own default job-retry doesn't retry this reason),
            # so it just spams error tracking. The user must reduce the data synced or simplify the
            # source view. Matched on BigQuery's stable wording, not the volatile peak-usage percentage
            # or job id.
            BIGQUERY_RESOURCES_EXCEEDED_ERROR: "BigQuery couldn't run a query for this source because it exceeded the memory allowed for a single query. This is usually caused by heavy sorts or analytic (window) functions over a large table or view. Retrying won't help — please reduce how much data you're syncing (for example add row filters or an incremental field), or simplify the source view, then re-enable the source.",
        }

    def validate_credentials(
        self, config: BigQuerySourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        region: str | None = None
        if (
            config.use_custom_region
            and config.use_custom_region.enabled
            and config.use_custom_region.region is not None
            and config.use_custom_region.region != ""
        ):
            region = config.use_custom_region.region
        if validate_bigquery_credentials(
            config.dataset_id,
            {
                "project_id": config.key_file.project_id,
                "private_key": config.key_file.private_key,
                "private_key_id": config.key_file.private_key_id,
                "client_email": config.key_file.client_email,
                "token_uri": config.key_file.token_uri,
            },
            config.dataset_project.dataset_project_id if config.dataset_project else None,
            region,
        ):
            return True, None

        return False, "Invalid BigQuery credentials"

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.BIG_QUERY,
            category=DataWarehouseSourceCategory.DATABASES,
            featured=True,
            iconPath="/static/services/bigquery.png",
            docsUrl="https://posthog.com/docs/cdp/sources/bigquery",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldFileUploadConfig(
                        name="key_file",
                        label="Google Cloud JSON key file",
                        fileFormat=SourceFieldFileUploadJsonFormatConfig(
                            format=".json",
                            keys=["project_id", "private_key", "private_key_id", "client_email", "token_uri"],
                        ),
                        required=True,
                    ),
                    SourceFieldSwitchGroupConfig(
                        name="use_custom_region",
                        label="Manually specify your dataset region?",
                        caption="In most cases, BigQuery is able to automatically determine the region your dataset is located in. For the rare instances that BigQuery fails to do so, you can manually specify your dataset region here.",
                        default=False,
                        fields=cast(
                            list[FieldType],
                            [
                                SourceFieldInputConfig(
                                    name="region",
                                    label="Region",
                                    type=SourceFieldInputConfigType.TEXT,
                                    required=True,
                                    placeholder="us-east1",
                                    secret=False,
                                ),
                            ],
                        ),
                    ),
                    SourceFieldInputConfig(
                        name="dataset_id",
                        label="Dataset ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="",
                        secret=False,
                    ),
                    SourceFieldSwitchGroupConfig(
                        name="temporary-dataset",
                        label="Use a different dataset for the temporary tables?",
                        caption="We have to create and delete temporary tables when querying your data, this is a requirement of querying large BigQuery tables. We can use a different dataset if you'd like to limit the permissions available to the service account provided.",
                        default=False,
                        fields=cast(
                            list[FieldType],
                            [
                                SourceFieldInputConfig(
                                    name="temporary_dataset_id",
                                    label="Dataset ID for temporary tables",
                                    type=SourceFieldInputConfigType.TEXT,
                                    required=True,
                                    placeholder="",
                                    secret=False,
                                )
                            ],
                        ),
                    ),
                    SourceFieldSwitchGroupConfig(
                        name="dataset_project",
                        label="Use a different project for the dataset than your service account project?",
                        caption="If the dataset you're wanting to sync exists in a different project than that of your service account, use this to provide the project ID of the BigQuery dataset.",
                        default=False,
                        fields=cast(
                            list[FieldType],
                            [
                                SourceFieldInputConfig(
                                    name="dataset_project_id",
                                    label="Project ID for dataset",
                                    type=SourceFieldInputConfigType.TEXT,
                                    required=True,
                                    placeholder="",
                                    secret=False,
                                )
                            ],
                        ),
                    ),
                ],
            ),
        )
