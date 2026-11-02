/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 6 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * Manage where warehouse sources write their synced rows.
 *
 * A destination can be attached to several sources, or to a single table on a source.
 * Credentials come from an integration, so one connection can be reused across syncs.
 */
export const ExternalDataDestinationsListParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const ExternalDataDestinationsListQueryParams = () => zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

/**
 * Manage where warehouse sources write their synced rows.
 *
 * A destination can be attached to several sources, or to a single table on a source.
 * Credentials come from an integration, so one connection can be reused across syncs.
 */
export const ExternalDataDestinationsCreateParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const externalDataDestinationsCreateBodyNameMax = 400

export const ExternalDataDestinationsCreateBody = () => zod.object({
    type: zod
        .enum(['PostHogWarehouse', 'Redshift', 'Snowflake', 'BigQuery', 'Postgres', 'Databricks', 'AzureBlob', 'S3'])
        .describe(
            '\* `PostHogWarehouse` - PostHog warehouse\n\* `Redshift` - Redshift\n\* `Snowflake` - Snowflake\n\* `BigQuery` - BigQuery\n\* `Postgres` - Postgres\n\* `Databricks` - Databricks\n\* `AzureBlob` - Azure Blob\n\* `S3` - S3'
        )
        .describe(
            'Where synced rows are written. The PostHog warehouse is managed for you, so you cannot create one here.\n\n\* `PostHogWarehouse` - PostHog warehouse\n\* `Redshift` - Redshift\n\* `Snowflake` - Snowflake\n\* `BigQuery` - BigQuery\n\* `Postgres` - Postgres\n\* `Databricks` - Databricks\n\* `AzureBlob` - Azure Blob\n\* `S3` - S3'
        ),
    name: zod
        .string()
        .max(externalDataDestinationsCreateBodyNameMax)
        .describe('Human-readable name shown when picking destinations for a source or table.'),
    config: zod
        .unknown()
        .optional()
        .describe(
            'Settings for this destination: target database, schema or dataset, bucket and prefix, file format. Credentials are not stored here. They live on the linked integration.'
        ),
    integration: zod
        .number()
        .nullish()
        .describe(
            "Integration holding this destination's credentials. Required for every type except the PostHog warehouse."
        ),
})

/**
 * Manage where warehouse sources write their synced rows.
 *
 * A destination can be attached to several sources, or to a single table on a source.
 * Credentials come from an integration, so one connection can be reused across syncs.
 */
export const ExternalDataDestinationsRetrieveParams = () => zod.object({
    id: zod.string().describe('A UUID string identifying this external data destination.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * Manage where warehouse sources write their synced rows.
 *
 * A destination can be attached to several sources, or to a single table on a source.
 * Credentials come from an integration, so one connection can be reused across syncs.
 */
export const ExternalDataDestinationsAddSourcesCreateParams = () => zod.object({
    id: zod.string().describe('A UUID string identifying this external data destination.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const externalDataDestinationsAddSourcesCreateBodySourceIdsMax = 50

export const externalDataDestinationsAddSourcesCreateBodyResyncDefault = false

export const ExternalDataDestinationsAddSourcesCreateBody = () => zod.object({
    source_ids: zod
        .array(zod.string())
        .max(externalDataDestinationsAddSourcesCreateBodySourceIdsMax)
        .describe('IDs of up to 50 existing sources to attach to this destination.'),
    resync: zod
        .boolean()
        .default(externalDataDestinationsAddSourcesCreateBodyResyncDefault)
        .describe('Start a full resync for each enabled table newly attached.'),
})

/**
 * Test the credentials and target of an existing destination, and return the result of each step.
 */
export const ExternalDataDestinationsTestConnectionCreateParams = () => zod.object({
    id: zod.string().describe('A UUID string identifying this external data destination.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * Return a secure browser link where the user connects the credentials for a destination.
 *
 * The page saves an integration and does not create the destination, so secrets never pass
 * through the agent. The agent then creates the destination with the new integration's id.
 */
export const ExternalDataDestinationsConnectLinkRetrieveParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const ExternalDataDestinationsConnectLinkRetrieveQueryParams = () => zod.object({
    destination_type: zod
        .enum(['Redshift', 'Snowflake', 'BigQuery', 'Postgres', 'Databricks', 'AzureBlob', 'S3'])
        .describe(
            "The destination type to connect, e.g. 'Snowflake' or 'S3'.\n\n\* `Redshift` - Redshift\n\* `Snowflake` - Snowflake\n\* `BigQuery` - BigQuery\n\* `Postgres` - Postgres\n\* `Databricks` - Databricks\n\* `AzureBlob` - Azure Blob\n\* `S3` - S3"
        ),
    integration_kind: zod
        .string()
        .min(1)
        .optional()
        .describe(
            "Which integration kind to connect when the type accepts more than one. Only S3 does: 'aws-s3' (the default) or 's3-compatible' for MinIO, Wasabi, R2, GCS and similar."
        ),
})
