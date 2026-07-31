/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import {
    DatabaseSchemaRequestApi,
    DraftCustomManifestRequestApi,
    ExternalDataSchemaApi,
    ExternalDataSourceCreateApi,
    ExternalDataSourceSerializersApi,
    PatchedExternalDataSchemaApi,
    PatchedExternalDataSourceBulkUpdateSchemasApi,
    PatchedExternalDataSourceSerializersApi,
    SourceCredentialCreateApi,
    SourcePreviewRequestApi,
    SourceSetupApi,
} from './api.zod.schemas'

export const ExternalDataSchemasUpdateBody = ExternalDataSchemaApi

export const ExternalDataSchemasPartialUpdateBody = PatchedExternalDataSchemaApi

export const ExternalDataSchemasIncrementalFieldsCreateBody = ExternalDataSchemaApi

export const ExternalDataSchemasReloadCreateBody = ExternalDataSchemaApi

export const ExternalDataSchemasResyncCreateBody = ExternalDataSchemaApi

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const ExternalDataSourcesCreateBody = ExternalDataSourceCreateApi

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const ExternalDataSourcesUpdateBody = ExternalDataSourceSerializersApi

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const ExternalDataSourcesPartialUpdateBody = PatchedExternalDataSourceSerializersApi

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const ExternalDataSourcesBulkUpdateSchemasPartialUpdateBody = PatchedExternalDataSourceBulkUpdateSchemasApi

/**
 * Validate CDC prerequisites for an existing source using its stored credentials.
 *
 * The detail=False ``check_cdc_prerequisites`` action is for the creation wizard,
 * where the client still holds the raw connection config (incl. password) in the
 * form. On the Configuration page the source already exists and secret fields are
 * stripped from API responses — so the client can't supply them. This reads the
 * stored (encrypted) credentials from the DB via the adapter instead.
 *
 * Body params: ``cdc_management_mode`` (``"posthog"`` | ``"self_managed"``),
 * ``cdc_slot_name`` (optional), ``cdc_publication_name`` (optional).
 */
export const ExternalDataSourcesCheckCdcPrerequisitesForSourceCreateBody = ExternalDataSourceSerializersApi

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const ExternalDataSourcesCreateWebhookCreateBody = ExternalDataSourceSerializersApi

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const ExternalDataSourcesDeleteWebhookCreateBody = ExternalDataSourceSerializersApi

/**
 * Disable CDC on an existing source.
 *
 * Cancels any running CDC extraction workflow, deletes the extraction schedule,
 * delegates engine-side teardown to the source's adapter (drops slot/publication
 * for Postgres; equivalent for other engines), clears ``cdc_*`` keys from
 * ``job_inputs``, soft-deletes companion CDC tables, and sets all CDC schemas to
 * ``sync_type=None``, ``should_sync=False`` so the user must pick a new sync
 * strategy before they resume.
 */
export const ExternalDataSourcesDisableCdcCreateBody = ExternalDataSourceSerializersApi

/**
 * Enable CDC on an existing source.
 *
 * Provisions engine-side CDC resources via the source's adapter, writes the CDC
 * config into ``source.job_inputs``, and ensures the CDC extraction schedule
 * exists. Re-runs prereq checks server-side so we never trust a stale
 * client-side check.
 *
 * Body params: ``cdc_management_mode`` (``"posthog"`` | ``"self_managed"``),
 * plus engine-specific identifier hints (e.g. ``cdc_slot_name``,
 * ``cdc_publication_name`` for Postgres). Universal tuning fields:
 * ``cdc_auto_drop_slot`` (optional bool), ``cdc_lag_warning_threshold_mb``
 * (optional int), ``cdc_lag_critical_threshold_mb`` (optional int).
 */
export const ExternalDataSourcesEnableCdcCreateBody = ExternalDataSourceSerializersApi

/**
 * Fetch current schema/table list from the source and create any new ExternalDataSchema rows (no data sync).
 */
export const ExternalDataSourcesRefreshSchemasCreateBody = ExternalDataSourceSerializersApi

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const ExternalDataSourcesReloadCreateBody = ExternalDataSourceSerializersApi

/**
 * Update the revenue analytics configuration and return the full external data source.
 */
export const ExternalDataSourcesRevenueAnalyticsConfigPartialUpdateBody = PatchedExternalDataSourceSerializersApi

/**
 * Update CDC tuning fields without enabling/disabling.
 *
 * Lets users edit ``cdc_auto_drop_slot``, ``cdc_lag_warning_threshold_mb``, and
 * ``cdc_lag_critical_threshold_mb`` independently. These fields are universal
 * across engines. Engine-specific identifiers (slot name, management mode, …)
 * are immutable post-enable — switching them requires disable + enable.
 */
export const ExternalDataSourcesUpdateCdcSettingsCreateBody = ExternalDataSourceSerializersApi

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const ExternalDataSourcesUpdateWebhookInputsCreateBody = ExternalDataSourceSerializersApi

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const ExternalDataSourcesDatabaseSchemaCreateBody = DatabaseSchemaRequestApi

/**
 * Draft a Custom REST source manifest from API documentation using an LLM.
 *
 * Reads the docs (a URL fetched server-side, or pasted text / OpenAPI spec), asks the model to
 * author a RESTAPIConfig manifest, and validates it against the create-path checks — repairing
 * against validation errors up to a small budget. Returns the manifest for the user to review
 * and tweak in the builder before creating the source; it does NOT create anything. Gated by the
 * `dwh-custom-source-ai-builder` flag, and requires the org to have approved AI data processing,
 * since the docs are sent to the LLM gateway.
 */
export const ExternalDataSourcesDraftCustomManifestCreateBody = DraftCustomManifestRequestApi

/**
 * Read a bounded sample of rows for one resource of a Custom REST source.
 *
 * Lets a manifest author verify `data_selector`, `primary_key`, and the incremental
 * `cursor_path` against live data before creating the source. Only `source_type: "Custom"`
 * is supported — other source types return 400. The read is bounded (single page per
 * resource, capped row count, short timeouts, no redirects). Manifest, validation, and SSRF
 * problems return 400; a live fetch failure returns 200 with `error` set and empty `rows`.
 */
export const ExternalDataSourcesPreviewResourceCreateBody = SourcePreviewRequestApi

/**
 * One-shot data warehouse source setup.
 *
 * Validate credentials, discover available tables, enable them all with sensible sync defaults
 * (incremental where supported, else append, else full refresh), and create the source in a single
 * call — the caller never has to assemble a `schemas` array. For sources that support webhooks
 * (e.g. Stripe), a webhook is auto-registered after creation: on success webhook-capable tables
 * switch to real-time webhook sync (unlocking webhook-only tables); on failure the polling
 * defaults stay in place. For fine-grained table/sync control, use the lower-level
 * `database_schema` + `create` flow instead.
 */
export const ExternalDataSourcesSetupCreateBody = SourceSetupApi

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const ExternalDataSourcesSourcePrefixCreateBody = ExternalDataSourceSerializersApi

/**
 * Validate and store credentials for a data warehouse source without creating the source.
 *
 * Backs the source connect page: the user enters credentials directly in PostHog, they are
 * checked against a live connection, then stashed encrypted in a temporary store. The returned
 * credential id can be passed to `setup` as {'credential_id': <id>} to create the source — so
 * secrets never travel through an agent conversation. The stash is single-use: it is deleted
 * as soon as `setup` consumes it, and expires after 24 hours if never consumed.
 */
export const ExternalDataSourcesStoreCredentialsCreateBody = SourceCredentialCreateApi
