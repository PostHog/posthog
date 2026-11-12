/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 10 enabled ops
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
    migration_item_id: zod
        .string()
        .optional()
        .describe(
            'The warehouse migration item that planned this destination. The integration must keep every setting the connect page prefilled from it, or creation fails before PostHog connects anywhere.'
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
export const ExternalDataDestinationsPartialUpdateParams = () => zod.object({
    id: zod.string().describe('A UUID string identifying this external data destination.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const externalDataDestinationsPartialUpdateBodyNameMax = 400

export const ExternalDataDestinationsPartialUpdateBody = () => zod.object({
    name: zod
        .string()
        .max(externalDataDestinationsPartialUpdateBodyNameMax)
        .optional()
        .describe('Human-readable name shown when picking destinations for a source or table.'),
    config: zod
        .unknown()
        .optional()
        .describe(
            'Settings for this destination: target database, schema or dataset, bucket and prefix, file format. Credentials are not stored here. They live on the linked integration.'
        ),
})

/**
 * Soft-delete, and detach it from everything that syncs to it.
 *
 * Runs already in flight keep their own snapshot of the destination, so deleting one
 * never strands a run part-way through. The next run of each affected table resolves
 * without it.
 */
export const ExternalDataDestinationsDestroyParams = () => zod.object({
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
 * through the agent. The link carries a connect token. The agent reads the saved integration's id
 * with the token from the connect link status endpoint, then creates the destination with it.
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
    migration_item_id: zod
        .string()
        .optional()
        .describe(
            "Optional warehouse migration item whose planned destination this link sets up. The page then shows the destination's non-secret settings from the vendor, so the user only enters the secret, and the instructions give the target config to create the destination with."
        ),
})

/**
 * Return whether the user saved a connection through a connect link, and which integration it is.
 *
 * Never returns credentials or integration config.
 */
export const ExternalDataDestinationsConnectLinkStatusRetrieveParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const externalDataDestinationsConnectLinkStatusRetrieveQueryConnectTokenMax = 128

export const ExternalDataDestinationsConnectLinkStatusRetrieveQueryParams = () => zod.object({
    connect_token: zod
        .string()
        .min(1)
        .max(externalDataDestinationsConnectLinkStatusRetrieveQueryConnectTokenMax)
        .describe('The connect_token that the connect link returned.'),
})

/**
 * Read or replace this table's destination override.
 *
 * Send `destination_ids: null` to clear the override so the table follows its source again.
 */
export const ExternalDataSchemasDestinationsPartialUpdateParams = () => zod.object({
    id: zod.string().describe('A UUID string identifying this external data schema.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const ExternalDataSchemasDestinationsPartialUpdateBody = () => zod.object({
    destination_ids: zod
        .array(zod.string())
        .nullish()
        .describe(
            'Destinations to sync to. On a table, null clears the override so the table follows its source again.'
        ),
})
