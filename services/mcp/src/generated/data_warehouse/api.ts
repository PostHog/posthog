/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 34 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * Returns failed/disabled data pipeline items for the Pipeline status side panel.
Includes: materializations, syncs, sources, destinations, and transformations.
 */
export const DataWarehouseDataHealthIssuesRetrieveParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ExternalDataSchemasListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ExternalDataSchemasListQueryParams = /* @__PURE__ */ zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
    search: zod.string().optional().describe('A search term.'),
})

export const ExternalDataSchemasRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this external data schema.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ExternalDataSchemasPartialUpdateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this external data schema.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ExternalDataSchemasPartialUpdateBody = /* @__PURE__ */ zod.object({
    should_sync: zod.boolean().optional(),
    sync_type: zod
        .union([
            zod
                .enum(['full_refresh', 'incremental', 'append', 'webhook', 'cdc'])
                .describe(
                    '* `full_refresh` - full_refresh\n* `incremental` - incremental\n* `append` - append\n* `webhook` - webhook\n* `cdc` - cdc'
                ),
            zod.literal(null),
        ])
        .nullish()
        .describe(
            'Sync strategy: incremental, full_refresh, append, or cdc.\n\n* `full_refresh` - full_refresh\n* `incremental` - incremental\n* `append` - append\n* `webhook` - webhook\n* `cdc` - cdc'
        ),
    incremental_field: zod.string().nullish().describe('Column name used to track sync progress.'),
    incremental_field_type: zod
        .union([
            zod
                .enum(['integer', 'numeric', 'datetime', 'date', 'timestamp', 'objectid'])
                .describe(
                    '* `integer` - integer\n* `numeric` - numeric\n* `datetime` - datetime\n* `date` - date\n* `timestamp` - timestamp\n* `objectid` - objectid'
                ),
            zod.literal(null),
        ])
        .nullish()
        .describe(
            'Data type of the incremental field.\n\n* `integer` - integer\n* `numeric` - numeric\n* `datetime` - datetime\n* `date` - date\n* `timestamp` - timestamp\n* `objectid` - objectid'
        ),
    sync_frequency: zod
        .union([
            zod
                .enum([
                    'never',
                    '1min',
                    '5min',
                    '15min',
                    '30min',
                    '1hour',
                    '6hour',
                    '12hour',
                    '24hour',
                    '7day',
                    '30day',
                ])
                .describe(
                    '* `never` - never\n* `1min` - 1min\n* `5min` - 5min\n* `15min` - 15min\n* `30min` - 30min\n* `1hour` - 1hour\n* `6hour` - 6hour\n* `12hour` - 12hour\n* `24hour` - 24hour\n* `7day` - 7day\n* `30day` - 30day'
                ),
            zod.literal(null),
        ])
        .nullish()
        .describe(
            'How often to sync.\n\n* `never` - never\n* `1min` - 1min\n* `5min` - 5min\n* `15min` - 15min\n* `30min` - 30min\n* `1hour` - 1hour\n* `6hour` - 6hour\n* `12hour` - 12hour\n* `24hour` - 24hour\n* `7day` - 7day\n* `30day` - 30day'
        ),
    sync_time_of_day: zod.iso.time({}).nullish().describe('UTC time of day to run the sync (HH:MM:SS).'),
    primary_key_columns: zod.array(zod.string()).nullish().describe('Column names for primary key deduplication.'),
    cdc_table_mode: zod
        .union([
            zod
                .enum(['consolidated', 'cdc_only', 'both'])
                .describe('* `consolidated` - consolidated\n* `cdc_only` - cdc_only\n* `both` - both'),
            zod.literal(null),
        ])
        .nullish()
        .describe(
            'For CDC syncs: consolidated, cdc_only, or both.\n\n* `consolidated` - consolidated\n* `cdc_only` - cdc_only\n* `both` - both'
        ),
})

export const ExternalDataSchemasCancelCreateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this external data schema.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ExternalDataSchemasCancelCreateBody = /* @__PURE__ */ zod.object({
    should_sync: zod.boolean().optional(),
    sync_type: zod
        .union([
            zod
                .enum(['full_refresh', 'incremental', 'append', 'webhook', 'cdc'])
                .describe(
                    '* `full_refresh` - full_refresh\n* `incremental` - incremental\n* `append` - append\n* `webhook` - webhook\n* `cdc` - cdc'
                ),
            zod.literal(null),
        ])
        .nullish()
        .describe(
            'Sync strategy: incremental, full_refresh, append, or cdc.\n\n* `full_refresh` - full_refresh\n* `incremental` - incremental\n* `append` - append\n* `webhook` - webhook\n* `cdc` - cdc'
        ),
    incremental_field: zod.string().nullish().describe('Column name used to track sync progress.'),
    incremental_field_type: zod
        .union([
            zod
                .enum(['integer', 'numeric', 'datetime', 'date', 'timestamp', 'objectid'])
                .describe(
                    '* `integer` - integer\n* `numeric` - numeric\n* `datetime` - datetime\n* `date` - date\n* `timestamp` - timestamp\n* `objectid` - objectid'
                ),
            zod.literal(null),
        ])
        .nullish()
        .describe(
            'Data type of the incremental field.\n\n* `integer` - integer\n* `numeric` - numeric\n* `datetime` - datetime\n* `date` - date\n* `timestamp` - timestamp\n* `objectid` - objectid'
        ),
    sync_frequency: zod
        .union([
            zod
                .enum([
                    'never',
                    '1min',
                    '5min',
                    '15min',
                    '30min',
                    '1hour',
                    '6hour',
                    '12hour',
                    '24hour',
                    '7day',
                    '30day',
                ])
                .describe(
                    '* `never` - never\n* `1min` - 1min\n* `5min` - 5min\n* `15min` - 15min\n* `30min` - 30min\n* `1hour` - 1hour\n* `6hour` - 6hour\n* `12hour` - 12hour\n* `24hour` - 24hour\n* `7day` - 7day\n* `30day` - 30day'
                ),
            zod.literal(null),
        ])
        .nullish()
        .describe(
            'How often to sync.\n\n* `never` - never\n* `1min` - 1min\n* `5min` - 5min\n* `15min` - 15min\n* `30min` - 30min\n* `1hour` - 1hour\n* `6hour` - 6hour\n* `12hour` - 12hour\n* `24hour` - 24hour\n* `7day` - 7day\n* `30day` - 30day'
        ),
    sync_time_of_day: zod.iso.time({}).nullish().describe('UTC time of day to run the sync (HH:MM:SS).'),
    primary_key_columns: zod.array(zod.string()).nullish().describe('Column names for primary key deduplication.'),
    cdc_table_mode: zod
        .union([
            zod
                .enum(['consolidated', 'cdc_only', 'both'])
                .describe('* `consolidated` - consolidated\n* `cdc_only` - cdc_only\n* `both` - both'),
            zod.literal(null),
        ])
        .nullish()
        .describe(
            'For CDC syncs: consolidated, cdc_only, or both.\n\n* `consolidated` - consolidated\n* `cdc_only` - cdc_only\n* `both` - both'
        ),
})

export const ExternalDataSchemasDeleteDataDestroyParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this external data schema.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ExternalDataSchemasIncrementalFieldsCreateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this external data schema.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ExternalDataSchemasIncrementalFieldsCreateBody = /* @__PURE__ */ zod.object({
    should_sync: zod.boolean().optional(),
    sync_type: zod
        .union([
            zod
                .enum(['full_refresh', 'incremental', 'append', 'webhook', 'cdc'])
                .describe(
                    '* `full_refresh` - full_refresh\n* `incremental` - incremental\n* `append` - append\n* `webhook` - webhook\n* `cdc` - cdc'
                ),
            zod.literal(null),
        ])
        .nullish()
        .describe(
            'Sync strategy: incremental, full_refresh, append, or cdc.\n\n* `full_refresh` - full_refresh\n* `incremental` - incremental\n* `append` - append\n* `webhook` - webhook\n* `cdc` - cdc'
        ),
    incremental_field: zod.string().nullish().describe('Column name used to track sync progress.'),
    incremental_field_type: zod
        .union([
            zod
                .enum(['integer', 'numeric', 'datetime', 'date', 'timestamp', 'objectid'])
                .describe(
                    '* `integer` - integer\n* `numeric` - numeric\n* `datetime` - datetime\n* `date` - date\n* `timestamp` - timestamp\n* `objectid` - objectid'
                ),
            zod.literal(null),
        ])
        .nullish()
        .describe(
            'Data type of the incremental field.\n\n* `integer` - integer\n* `numeric` - numeric\n* `datetime` - datetime\n* `date` - date\n* `timestamp` - timestamp\n* `objectid` - objectid'
        ),
    sync_frequency: zod
        .union([
            zod
                .enum([
                    'never',
                    '1min',
                    '5min',
                    '15min',
                    '30min',
                    '1hour',
                    '6hour',
                    '12hour',
                    '24hour',
                    '7day',
                    '30day',
                ])
                .describe(
                    '* `never` - never\n* `1min` - 1min\n* `5min` - 5min\n* `15min` - 15min\n* `30min` - 30min\n* `1hour` - 1hour\n* `6hour` - 6hour\n* `12hour` - 12hour\n* `24hour` - 24hour\n* `7day` - 7day\n* `30day` - 30day'
                ),
            zod.literal(null),
        ])
        .nullish()
        .describe(
            'How often to sync.\n\n* `never` - never\n* `1min` - 1min\n* `5min` - 5min\n* `15min` - 15min\n* `30min` - 30min\n* `1hour` - 1hour\n* `6hour` - 6hour\n* `12hour` - 12hour\n* `24hour` - 24hour\n* `7day` - 7day\n* `30day` - 30day'
        ),
    sync_time_of_day: zod.iso.time({}).nullish().describe('UTC time of day to run the sync (HH:MM:SS).'),
    primary_key_columns: zod.array(zod.string()).nullish().describe('Column names for primary key deduplication.'),
    cdc_table_mode: zod
        .union([
            zod
                .enum(['consolidated', 'cdc_only', 'both'])
                .describe('* `consolidated` - consolidated\n* `cdc_only` - cdc_only\n* `both` - both'),
            zod.literal(null),
        ])
        .nullish()
        .describe(
            'For CDC syncs: consolidated, cdc_only, or both.\n\n* `consolidated` - consolidated\n* `cdc_only` - cdc_only\n* `both` - both'
        ),
})

export const ExternalDataSchemasReloadCreateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this external data schema.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ExternalDataSchemasReloadCreateBody = /* @__PURE__ */ zod.object({
    should_sync: zod.boolean().optional(),
    sync_type: zod
        .union([
            zod
                .enum(['full_refresh', 'incremental', 'append', 'webhook', 'cdc'])
                .describe(
                    '* `full_refresh` - full_refresh\n* `incremental` - incremental\n* `append` - append\n* `webhook` - webhook\n* `cdc` - cdc'
                ),
            zod.literal(null),
        ])
        .nullish()
        .describe(
            'Sync strategy: incremental, full_refresh, append, or cdc.\n\n* `full_refresh` - full_refresh\n* `incremental` - incremental\n* `append` - append\n* `webhook` - webhook\n* `cdc` - cdc'
        ),
    incremental_field: zod.string().nullish().describe('Column name used to track sync progress.'),
    incremental_field_type: zod
        .union([
            zod
                .enum(['integer', 'numeric', 'datetime', 'date', 'timestamp', 'objectid'])
                .describe(
                    '* `integer` - integer\n* `numeric` - numeric\n* `datetime` - datetime\n* `date` - date\n* `timestamp` - timestamp\n* `objectid` - objectid'
                ),
            zod.literal(null),
        ])
        .nullish()
        .describe(
            'Data type of the incremental field.\n\n* `integer` - integer\n* `numeric` - numeric\n* `datetime` - datetime\n* `date` - date\n* `timestamp` - timestamp\n* `objectid` - objectid'
        ),
    sync_frequency: zod
        .union([
            zod
                .enum([
                    'never',
                    '1min',
                    '5min',
                    '15min',
                    '30min',
                    '1hour',
                    '6hour',
                    '12hour',
                    '24hour',
                    '7day',
                    '30day',
                ])
                .describe(
                    '* `never` - never\n* `1min` - 1min\n* `5min` - 5min\n* `15min` - 15min\n* `30min` - 30min\n* `1hour` - 1hour\n* `6hour` - 6hour\n* `12hour` - 12hour\n* `24hour` - 24hour\n* `7day` - 7day\n* `30day` - 30day'
                ),
            zod.literal(null),
        ])
        .nullish()
        .describe(
            'How often to sync.\n\n* `never` - never\n* `1min` - 1min\n* `5min` - 5min\n* `15min` - 15min\n* `30min` - 30min\n* `1hour` - 1hour\n* `6hour` - 6hour\n* `12hour` - 12hour\n* `24hour` - 24hour\n* `7day` - 7day\n* `30day` - 30day'
        ),
    sync_time_of_day: zod.iso.time({}).nullish().describe('UTC time of day to run the sync (HH:MM:SS).'),
    primary_key_columns: zod.array(zod.string()).nullish().describe('Column names for primary key deduplication.'),
    cdc_table_mode: zod
        .union([
            zod
                .enum(['consolidated', 'cdc_only', 'both'])
                .describe('* `consolidated` - consolidated\n* `cdc_only` - cdc_only\n* `both` - both'),
            zod.literal(null),
        ])
        .nullish()
        .describe(
            'For CDC syncs: consolidated, cdc_only, or both.\n\n* `consolidated` - consolidated\n* `cdc_only` - cdc_only\n* `both` - both'
        ),
})

export const ExternalDataSchemasResyncCreateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this external data schema.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ExternalDataSchemasResyncCreateBody = /* @__PURE__ */ zod.object({
    should_sync: zod.boolean().optional(),
    sync_type: zod
        .union([
            zod
                .enum(['full_refresh', 'incremental', 'append', 'webhook', 'cdc'])
                .describe(
                    '* `full_refresh` - full_refresh\n* `incremental` - incremental\n* `append` - append\n* `webhook` - webhook\n* `cdc` - cdc'
                ),
            zod.literal(null),
        ])
        .nullish()
        .describe(
            'Sync strategy: incremental, full_refresh, append, or cdc.\n\n* `full_refresh` - full_refresh\n* `incremental` - incremental\n* `append` - append\n* `webhook` - webhook\n* `cdc` - cdc'
        ),
    incremental_field: zod.string().nullish().describe('Column name used to track sync progress.'),
    incremental_field_type: zod
        .union([
            zod
                .enum(['integer', 'numeric', 'datetime', 'date', 'timestamp', 'objectid'])
                .describe(
                    '* `integer` - integer\n* `numeric` - numeric\n* `datetime` - datetime\n* `date` - date\n* `timestamp` - timestamp\n* `objectid` - objectid'
                ),
            zod.literal(null),
        ])
        .nullish()
        .describe(
            'Data type of the incremental field.\n\n* `integer` - integer\n* `numeric` - numeric\n* `datetime` - datetime\n* `date` - date\n* `timestamp` - timestamp\n* `objectid` - objectid'
        ),
    sync_frequency: zod
        .union([
            zod
                .enum([
                    'never',
                    '1min',
                    '5min',
                    '15min',
                    '30min',
                    '1hour',
                    '6hour',
                    '12hour',
                    '24hour',
                    '7day',
                    '30day',
                ])
                .describe(
                    '* `never` - never\n* `1min` - 1min\n* `5min` - 5min\n* `15min` - 15min\n* `30min` - 30min\n* `1hour` - 1hour\n* `6hour` - 6hour\n* `12hour` - 12hour\n* `24hour` - 24hour\n* `7day` - 7day\n* `30day` - 30day'
                ),
            zod.literal(null),
        ])
        .nullish()
        .describe(
            'How often to sync.\n\n* `never` - never\n* `1min` - 1min\n* `5min` - 5min\n* `15min` - 15min\n* `30min` - 30min\n* `1hour` - 1hour\n* `6hour` - 6hour\n* `12hour` - 12hour\n* `24hour` - 24hour\n* `7day` - 7day\n* `30day` - 30day'
        ),
    sync_time_of_day: zod.iso.time({}).nullish().describe('UTC time of day to run the sync (HH:MM:SS).'),
    primary_key_columns: zod.array(zod.string()).nullish().describe('Column names for primary key deduplication.'),
    cdc_table_mode: zod
        .union([
            zod
                .enum(['consolidated', 'cdc_only', 'both'])
                .describe('* `consolidated` - consolidated\n* `cdc_only` - cdc_only\n* `both` - both'),
            zod.literal(null),
        ])
        .nullish()
        .describe(
            'For CDC syncs: consolidated, cdc_only, or both.\n\n* `consolidated` - consolidated\n* `cdc_only` - cdc_only\n* `both` - both'
        ),
})

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const ExternalDataSourcesListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ExternalDataSourcesListQueryParams = /* @__PURE__ */ zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
    search: zod.string().optional().describe('A search term.'),
})

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const ExternalDataSourcesCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const externalDataSourcesCreateBodyPrefixMax = 100

export const externalDataSourcesCreateBodyDescriptionMax = 400

export const externalDataSourcesCreateBodyAccessMethodDefault = `warehouse`

export const ExternalDataSourcesCreateBody = /* @__PURE__ */ zod.object({
    source_type: zod
        .enum([
            'Ashby',
            'Supabase',
            'CustomerIO',
            'Github',
            'Stripe',
            'Hubspot',
            'Postgres',
            'Zendesk',
            'Snowflake',
            'Salesforce',
            'MySQL',
            'MongoDB',
            'MSSQL',
            'Vitally',
            'BigQuery',
            'Chargebee',
            'Clerk',
            'GoogleAds',
            'TemporalIO',
            'DoIt',
            'GoogleSheets',
            'MetaAds',
            'Klaviyo',
            'Mailchimp',
            'Braze',
            'Mailjet',
            'Redshift',
            'Polar',
            'RevenueCat',
            'LinkedinAds',
            'RedditAds',
            'TikTokAds',
            'BingAds',
            'Shopify',
            'Attio',
            'SnapchatAds',
            'Linear',
            'Intercom',
            'Amplitude',
            'Mixpanel',
            'Jira',
            'ActiveCampaign',
            'Marketo',
            'Adjust',
            'AppsFlyer',
            'Freshdesk',
            'GoogleAnalytics',
            'Pipedrive',
            'SendGrid',
            'Slack',
            'PagerDuty',
            'Asana',
            'Notion',
            'Airtable',
            'Greenhouse',
            'BambooHR',
            'Lever',
            'GitLab',
            'Datadog',
            'Sentry',
            'Pendo',
            'FullStory',
            'AmazonAds',
            'PinterestAds',
            'AppleSearchAds',
            'QuickBooks',
            'Xero',
            'NetSuite',
            'WooCommerce',
            'BigCommerce',
            'PayPal',
            'Square',
            'Zoom',
            'Trello',
            'Monday',
            'ClickUp',
            'Confluence',
            'Recurly',
            'SalesLoft',
            'Outreach',
            'Gong',
            'Calendly',
            'Typeform',
            'Iterable',
            'ZohoCRM',
            'Close',
            'Oracle',
            'DynamoDB',
            'Elasticsearch',
            'Kafka',
            'LaunchDarkly',
            'Braintree',
            'Recharge',
            'HelpScout',
            'Gorgias',
            'Instagram',
            'YouTubeAnalytics',
            'FacebookPages',
            'TwitterAds',
            'Workday',
            'ServiceNow',
            'Pardot',
            'Copper',
            'Front',
            'ChartMogul',
            'Zuora',
            'Paddle',
            'CircleCI',
            'CockroachDB',
            'Firebase',
            'AzureBlob',
            'GoogleDrive',
            'OneDrive',
            'SharePoint',
            'Box',
            'SFTP',
            'MicrosoftTeams',
            'Aircall',
            'Webflow',
            'Okta',
            'Auth0',
            'Productboard',
            'Smartsheet',
            'Wrike',
            'Plaid',
            'SurveyMonkey',
            'Eventbrite',
            'RingCentral',
            'Twilio',
            'Freshsales',
            'Shortcut',
            'ConvertKit',
            'Drip',
            'CampaignMonitor',
            'MailerLite',
            'Omnisend',
            'Brevo',
            'Postmark',
            'Granola',
            'BuildBetter',
            'Convex',
            'ClickHouse',
            'Plain',
        ])
        .describe(
            '* `Ashby` - Ashby\n* `Supabase` - Supabase\n* `CustomerIO` - CustomerIO\n* `Github` - Github\n* `Stripe` - Stripe\n* `Hubspot` - Hubspot\n* `Postgres` - Postgres\n* `Zendesk` - Zendesk\n* `Snowflake` - Snowflake\n* `Salesforce` - Salesforce\n* `MySQL` - MySQL\n* `MongoDB` - MongoDB\n* `MSSQL` - MSSQL\n* `Vitally` - Vitally\n* `BigQuery` - BigQuery\n* `Chargebee` - Chargebee\n* `Clerk` - Clerk\n* `GoogleAds` - GoogleAds\n* `TemporalIO` - TemporalIO\n* `DoIt` - DoIt\n* `GoogleSheets` - GoogleSheets\n* `MetaAds` - MetaAds\n* `Klaviyo` - Klaviyo\n* `Mailchimp` - Mailchimp\n* `Braze` - Braze\n* `Mailjet` - Mailjet\n* `Redshift` - Redshift\n* `Polar` - Polar\n* `RevenueCat` - RevenueCat\n* `LinkedinAds` - LinkedinAds\n* `RedditAds` - RedditAds\n* `TikTokAds` - TikTokAds\n* `BingAds` - BingAds\n* `Shopify` - Shopify\n* `Attio` - Attio\n* `SnapchatAds` - SnapchatAds\n* `Linear` - Linear\n* `Intercom` - Intercom\n* `Amplitude` - Amplitude\n* `Mixpanel` - Mixpanel\n* `Jira` - Jira\n* `ActiveCampaign` - ActiveCampaign\n* `Marketo` - Marketo\n* `Adjust` - Adjust\n* `AppsFlyer` - AppsFlyer\n* `Freshdesk` - Freshdesk\n* `GoogleAnalytics` - GoogleAnalytics\n* `Pipedrive` - Pipedrive\n* `SendGrid` - SendGrid\n* `Slack` - Slack\n* `PagerDuty` - PagerDuty\n* `Asana` - Asana\n* `Notion` - Notion\n* `Airtable` - Airtable\n* `Greenhouse` - Greenhouse\n* `BambooHR` - BambooHR\n* `Lever` - Lever\n* `GitLab` - GitLab\n* `Datadog` - Datadog\n* `Sentry` - Sentry\n* `Pendo` - Pendo\n* `FullStory` - FullStory\n* `AmazonAds` - AmazonAds\n* `PinterestAds` - PinterestAds\n* `AppleSearchAds` - AppleSearchAds\n* `QuickBooks` - QuickBooks\n* `Xero` - Xero\n* `NetSuite` - NetSuite\n* `WooCommerce` - WooCommerce\n* `BigCommerce` - BigCommerce\n* `PayPal` - PayPal\n* `Square` - Square\n* `Zoom` - Zoom\n* `Trello` - Trello\n* `Monday` - Monday\n* `ClickUp` - ClickUp\n* `Confluence` - Confluence\n* `Recurly` - Recurly\n* `SalesLoft` - SalesLoft\n* `Outreach` - Outreach\n* `Gong` - Gong\n* `Calendly` - Calendly\n* `Typeform` - Typeform\n* `Iterable` - Iterable\n* `ZohoCRM` - ZohoCRM\n* `Close` - Close\n* `Oracle` - Oracle\n* `DynamoDB` - DynamoDB\n* `Elasticsearch` - Elasticsearch\n* `Kafka` - Kafka\n* `LaunchDarkly` - LaunchDarkly\n* `Braintree` - Braintree\n* `Recharge` - Recharge\n* `HelpScout` - HelpScout\n* `Gorgias` - Gorgias\n* `Instagram` - Instagram\n* `YouTubeAnalytics` - YouTubeAnalytics\n* `FacebookPages` - FacebookPages\n* `TwitterAds` - TwitterAds\n* `Workday` - Workday\n* `ServiceNow` - ServiceNow\n* `Pardot` - Pardot\n* `Copper` - Copper\n* `Front` - Front\n* `ChartMogul` - ChartMogul\n* `Zuora` - Zuora\n* `Paddle` - Paddle\n* `CircleCI` - CircleCI\n* `CockroachDB` - CockroachDB\n* `Firebase` - Firebase\n* `AzureBlob` - AzureBlob\n* `GoogleDrive` - GoogleDrive\n* `OneDrive` - OneDrive\n* `SharePoint` - SharePoint\n* `Box` - Box\n* `SFTP` - SFTP\n* `MicrosoftTeams` - MicrosoftTeams\n* `Aircall` - Aircall\n* `Webflow` - Webflow\n* `Okta` - Okta\n* `Auth0` - Auth0\n* `Productboard` - Productboard\n* `Smartsheet` - Smartsheet\n* `Wrike` - Wrike\n* `Plaid` - Plaid\n* `SurveyMonkey` - SurveyMonkey\n* `Eventbrite` - Eventbrite\n* `RingCentral` - RingCentral\n* `Twilio` - Twilio\n* `Freshsales` - Freshsales\n* `Shortcut` - Shortcut\n* `ConvertKit` - ConvertKit\n* `Drip` - Drip\n* `CampaignMonitor` - CampaignMonitor\n* `MailerLite` - MailerLite\n* `Omnisend` - Omnisend\n* `Brevo` - Brevo\n* `Postmark` - Postmark\n* `Granola` - Granola\n* `BuildBetter` - BuildBetter\n* `Convex` - Convex\n* `ClickHouse` - ClickHouse\n* `Plain` - Plain'
        )
        .describe(
            "The source type (e.g. 'Postgres', 'Stripe').\n\n* `Ashby` - Ashby\n* `Supabase` - Supabase\n* `CustomerIO` - CustomerIO\n* `Github` - Github\n* `Stripe` - Stripe\n* `Hubspot` - Hubspot\n* `Postgres` - Postgres\n* `Zendesk` - Zendesk\n* `Snowflake` - Snowflake\n* `Salesforce` - Salesforce\n* `MySQL` - MySQL\n* `MongoDB` - MongoDB\n* `MSSQL` - MSSQL\n* `Vitally` - Vitally\n* `BigQuery` - BigQuery\n* `Chargebee` - Chargebee\n* `Clerk` - Clerk\n* `GoogleAds` - GoogleAds\n* `TemporalIO` - TemporalIO\n* `DoIt` - DoIt\n* `GoogleSheets` - GoogleSheets\n* `MetaAds` - MetaAds\n* `Klaviyo` - Klaviyo\n* `Mailchimp` - Mailchimp\n* `Braze` - Braze\n* `Mailjet` - Mailjet\n* `Redshift` - Redshift\n* `Polar` - Polar\n* `RevenueCat` - RevenueCat\n* `LinkedinAds` - LinkedinAds\n* `RedditAds` - RedditAds\n* `TikTokAds` - TikTokAds\n* `BingAds` - BingAds\n* `Shopify` - Shopify\n* `Attio` - Attio\n* `SnapchatAds` - SnapchatAds\n* `Linear` - Linear\n* `Intercom` - Intercom\n* `Amplitude` - Amplitude\n* `Mixpanel` - Mixpanel\n* `Jira` - Jira\n* `ActiveCampaign` - ActiveCampaign\n* `Marketo` - Marketo\n* `Adjust` - Adjust\n* `AppsFlyer` - AppsFlyer\n* `Freshdesk` - Freshdesk\n* `GoogleAnalytics` - GoogleAnalytics\n* `Pipedrive` - Pipedrive\n* `SendGrid` - SendGrid\n* `Slack` - Slack\n* `PagerDuty` - PagerDuty\n* `Asana` - Asana\n* `Notion` - Notion\n* `Airtable` - Airtable\n* `Greenhouse` - Greenhouse\n* `BambooHR` - BambooHR\n* `Lever` - Lever\n* `GitLab` - GitLab\n* `Datadog` - Datadog\n* `Sentry` - Sentry\n* `Pendo` - Pendo\n* `FullStory` - FullStory\n* `AmazonAds` - AmazonAds\n* `PinterestAds` - PinterestAds\n* `AppleSearchAds` - AppleSearchAds\n* `QuickBooks` - QuickBooks\n* `Xero` - Xero\n* `NetSuite` - NetSuite\n* `WooCommerce` - WooCommerce\n* `BigCommerce` - BigCommerce\n* `PayPal` - PayPal\n* `Square` - Square\n* `Zoom` - Zoom\n* `Trello` - Trello\n* `Monday` - Monday\n* `ClickUp` - ClickUp\n* `Confluence` - Confluence\n* `Recurly` - Recurly\n* `SalesLoft` - SalesLoft\n* `Outreach` - Outreach\n* `Gong` - Gong\n* `Calendly` - Calendly\n* `Typeform` - Typeform\n* `Iterable` - Iterable\n* `ZohoCRM` - ZohoCRM\n* `Close` - Close\n* `Oracle` - Oracle\n* `DynamoDB` - DynamoDB\n* `Elasticsearch` - Elasticsearch\n* `Kafka` - Kafka\n* `LaunchDarkly` - LaunchDarkly\n* `Braintree` - Braintree\n* `Recharge` - Recharge\n* `HelpScout` - HelpScout\n* `Gorgias` - Gorgias\n* `Instagram` - Instagram\n* `YouTubeAnalytics` - YouTubeAnalytics\n* `FacebookPages` - FacebookPages\n* `TwitterAds` - TwitterAds\n* `Workday` - Workday\n* `ServiceNow` - ServiceNow\n* `Pardot` - Pardot\n* `Copper` - Copper\n* `Front` - Front\n* `ChartMogul` - ChartMogul\n* `Zuora` - Zuora\n* `Paddle` - Paddle\n* `CircleCI` - CircleCI\n* `CockroachDB` - CockroachDB\n* `Firebase` - Firebase\n* `AzureBlob` - AzureBlob\n* `GoogleDrive` - GoogleDrive\n* `OneDrive` - OneDrive\n* `SharePoint` - SharePoint\n* `Box` - Box\n* `SFTP` - SFTP\n* `MicrosoftTeams` - MicrosoftTeams\n* `Aircall` - Aircall\n* `Webflow` - Webflow\n* `Okta` - Okta\n* `Auth0` - Auth0\n* `Productboard` - Productboard\n* `Smartsheet` - Smartsheet\n* `Wrike` - Wrike\n* `Plaid` - Plaid\n* `SurveyMonkey` - SurveyMonkey\n* `Eventbrite` - Eventbrite\n* `RingCentral` - RingCentral\n* `Twilio` - Twilio\n* `Freshsales` - Freshsales\n* `Shortcut` - Shortcut\n* `ConvertKit` - ConvertKit\n* `Drip` - Drip\n* `CampaignMonitor` - CampaignMonitor\n* `MailerLite` - MailerLite\n* `Omnisend` - Omnisend\n* `Brevo` - Brevo\n* `Postmark` - Postmark\n* `Granola` - Granola\n* `BuildBetter` - BuildBetter\n* `Convex` - Convex\n* `ClickHouse` - ClickHouse\n* `Plain` - Plain"
        ),
    payload: zod
        .record(zod.string(), zod.unknown())
        .describe("Connection credentials and a 'schemas' array. Keys depend on source_type."),
    prefix: zod.string().max(externalDataSourcesCreateBodyPrefixMax).nullish().describe('Table name prefix in HogQL.'),
    description: zod
        .string()
        .max(externalDataSourcesCreateBodyDescriptionMax)
        .nullish()
        .describe('Human-readable description.'),
    access_method: zod
        .enum(['warehouse', 'direct'])
        .describe('* `warehouse` - warehouse\n* `direct` - direct')
        .default(externalDataSourcesCreateBodyAccessMethodDefault)
        .describe(
            "Connection mode: 'warehouse' (import) or 'direct' (live query).\n\n* `warehouse` - warehouse\n* `direct` - direct"
        ),
})

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const ExternalDataSourcesRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this external data source.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const ExternalDataSourcesPartialUpdateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this external data source.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const externalDataSourcesPartialUpdateBodyPrefixMax = 100

export const externalDataSourcesPartialUpdateBodyDescriptionMax = 400

export const ExternalDataSourcesPartialUpdateBody = /* @__PURE__ */ zod
    .object({
        client_secret: zod.string().optional(),
        account_id: zod.string().optional(),
        prefix: zod.string().max(externalDataSourcesPartialUpdateBodyPrefixMax).nullish(),
        description: zod.string().max(externalDataSourcesPartialUpdateBodyDescriptionMax).nullish(),
        job_inputs: zod.unknown().nullish(),
    })
    .describe('Mixin for serializers to add user access control fields')

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const ExternalDataSourcesDestroyParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this external data source.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const ExternalDataSourcesCreateWebhookCreateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this external data source.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const externalDataSourcesCreateWebhookCreateBodyPrefixMax = 100

export const externalDataSourcesCreateWebhookCreateBodyDescriptionMax = 400

export const ExternalDataSourcesCreateWebhookCreateBody = /* @__PURE__ */ zod
    .object({
        client_secret: zod.string(),
        account_id: zod.string(),
        prefix: zod.string().max(externalDataSourcesCreateWebhookCreateBodyPrefixMax).nullish(),
        description: zod.string().max(externalDataSourcesCreateWebhookCreateBodyDescriptionMax).nullish(),
        job_inputs: zod.unknown().nullish(),
    })
    .describe('Mixin for serializers to add user access control fields')

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const ExternalDataSourcesDeleteWebhookCreateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this external data source.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const externalDataSourcesDeleteWebhookCreateBodyPrefixMax = 100

export const externalDataSourcesDeleteWebhookCreateBodyDescriptionMax = 400

export const ExternalDataSourcesDeleteWebhookCreateBody = /* @__PURE__ */ zod
    .object({
        client_secret: zod.string(),
        account_id: zod.string(),
        prefix: zod.string().max(externalDataSourcesDeleteWebhookCreateBodyPrefixMax).nullish(),
        description: zod.string().max(externalDataSourcesDeleteWebhookCreateBodyDescriptionMax).nullish(),
        job_inputs: zod.unknown().nullish(),
    })
    .describe('Mixin for serializers to add user access control fields')

/**
 * Fetch current schema/table list from the source and create any new ExternalDataSchema rows (no data sync).
 */
export const ExternalDataSourcesRefreshSchemasCreateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this external data source.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ExternalDataSourcesRefreshSchemasCreateBody = /* @__PURE__ */ zod
    .object({})
    .describe('Mixin for serializers to add user access control fields')

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const ExternalDataSourcesReloadCreateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this external data source.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ExternalDataSourcesReloadCreateBody = /* @__PURE__ */ zod
    .object({})
    .describe('Mixin for serializers to add user access control fields')

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const ExternalDataSourcesUpdateWebhookInputsCreateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this external data source.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const externalDataSourcesUpdateWebhookInputsCreateBodyPrefixMax = 100

export const externalDataSourcesUpdateWebhookInputsCreateBodyDescriptionMax = 400

export const ExternalDataSourcesUpdateWebhookInputsCreateBody = /* @__PURE__ */ zod
    .object({
        client_secret: zod.string(),
        account_id: zod.string(),
        prefix: zod.string().max(externalDataSourcesUpdateWebhookInputsCreateBodyPrefixMax).nullish(),
        description: zod.string().max(externalDataSourcesUpdateWebhookInputsCreateBodyDescriptionMax).nullish(),
        job_inputs: zod.unknown().nullish(),
    })
    .describe('Mixin for serializers to add user access control fields')

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const ExternalDataSourcesWebhookInfoRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this external data source.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Validate CDC prerequisites against a live Postgres connection.

Used by the source wizard to surface ✅/❌ checks before source creation,
and by the self-managed setup popup to verify user-created publications.
 */
export const ExternalDataSourcesCheckCdcPrerequisitesCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const ExternalDataSourcesWizardRetrieveParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const InsightVariablesCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const insightVariablesCreateBodyNameMax = 400

export const InsightVariablesCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(insightVariablesCreateBodyNameMax).describe('Human-readable name for the SQL variable.'),
    type: zod
        .enum(['String', 'Number', 'Boolean', 'List', 'Date'])
        .describe('* `String` - String\n* `Number` - Number\n* `Boolean` - Boolean\n* `List` - List\n* `Date` - Date')
        .describe(
            'Variable type. Controls how the value is rendered and substituted in HogQL.\n\n* `String` - String\n* `Number` - Number\n* `Boolean` - Boolean\n* `List` - List\n* `Date` - Date'
        ),
    default_value: zod.unknown().nullish().describe('Default value used when a query references this variable.'),
    values: zod.unknown().nullish().describe('Allowed values for List variables. Null for other variable types.'),
})

export const InsightVariablesPartialUpdateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this insight variable.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const insightVariablesPartialUpdateBodyNameMax = 400

export const InsightVariablesPartialUpdateBody = /* @__PURE__ */ zod.object({
    name: zod
        .string()
        .max(insightVariablesPartialUpdateBodyNameMax)
        .optional()
        .describe('Human-readable name for the SQL variable.'),
    type: zod
        .enum(['String', 'Number', 'Boolean', 'List', 'Date'])
        .describe('* `String` - String\n* `Number` - Number\n* `Boolean` - Boolean\n* `List` - List\n* `Date` - Date')
        .optional()
        .describe(
            'Variable type. Controls how the value is rendered and substituted in HogQL.\n\n* `String` - String\n* `Number` - Number\n* `Boolean` - Boolean\n* `List` - List\n* `Date` - Date'
        ),
    default_value: zod.unknown().nullish().describe('Default value used when a query references this variable.'),
    values: zod.unknown().nullish().describe('Allowed values for List variables. Null for other variable types.'),
})

export const InsightVariablesDestroyParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this insight variable.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Create, Read, Update and Delete Warehouse Tables.
 */
export const WarehouseSavedQueriesListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const WarehouseSavedQueriesListQueryParams = /* @__PURE__ */ zod.object({
    page: zod.number().optional().describe('A page number within the paginated result set.'),
    search: zod.string().optional().describe('A search term.'),
})

/**
 * Create, Read, Update and Delete Warehouse Tables.
 */
export const WarehouseSavedQueriesCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const warehouseSavedQueriesCreateBodyNameMax = 128

export const WarehouseSavedQueriesCreateBody = /* @__PURE__ */ zod
    .object({
        name: zod
            .string()
            .max(warehouseSavedQueriesCreateBodyNameMax)
            .describe(
                'Unique name for the view. Used as the table name in HogQL queries and the node name in the data modeling Node.'
            ),
        query: zod
            .unknown()
            .nullish()
            .describe(
                'HogQL query definition as a JSON object with a "query" key containing the SQL string and a "kind" key containing the query type. Example: {"query": "SELECT * FROM events LIMIT 100", "kind": "HogQLQuery"}'
            ),
        folder_id: zod
            .string()
            .nullish()
            .describe('Optional folder ID used to organize this view in the SQL editor sidebar.'),
        dag_id: zod.string().nullish().describe('Optional DAG to place this view into'),
        is_test: zod.boolean().optional().describe('Whether this view is for testing only and will auto-expire.'),
    })
    .describe(
        'Shared methods for DataWarehouseSavedQuery serializers.\n\nThis mixin is intended to be used with serializers.ModelSerializer subclasses.'
    )

/**
 * Create, Read, Update and Delete Warehouse Tables.
 */
export const WarehouseSavedQueriesRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this data warehouse saved query.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Create, Read, Update and Delete Warehouse Tables.
 */
export const WarehouseSavedQueriesPartialUpdateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this data warehouse saved query.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const warehouseSavedQueriesPartialUpdateBodyNameMax = 128

export const WarehouseSavedQueriesPartialUpdateBody = /* @__PURE__ */ zod
    .object({
        name: zod
            .string()
            .max(warehouseSavedQueriesPartialUpdateBodyNameMax)
            .optional()
            .describe(
                'Unique name for the view. Used as the table name in HogQL queries and the node name in the data modeling Node.'
            ),
        query: zod
            .unknown()
            .nullish()
            .describe(
                'HogQL query definition as a JSON object with a "query" key containing the SQL string and a "kind" key containing the query type. Example: {"query": "SELECT * FROM events LIMIT 100", "kind": "HogQLQuery"}'
            ),
        folder_id: zod
            .string()
            .nullish()
            .describe('Optional folder ID used to organize this view in the SQL editor sidebar.'),
        edited_history_id: zod
            .string()
            .nullish()
            .describe('Activity log ID from the last known edit. Used for conflict detection.'),
        dag_id: zod.string().nullish().describe('Optional DAG to place this view into'),
        is_test: zod.boolean().optional().describe('Whether this view is for testing only and will auto-expire.'),
    })
    .describe(
        'Shared methods for DataWarehouseSavedQuery serializers.\n\nThis mixin is intended to be used with serializers.ModelSerializer subclasses.'
    )

/**
 * Create, Read, Update and Delete Warehouse Tables.
 */
export const WarehouseSavedQueriesDestroyParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this data warehouse saved query.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Enable materialization for this saved query with a 24-hour sync frequency.
 */
export const WarehouseSavedQueriesMaterializeCreateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this data warehouse saved query.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const warehouseSavedQueriesMaterializeCreateBodyNameMax = 128

export const WarehouseSavedQueriesMaterializeCreateBody = /* @__PURE__ */ zod
    .object({
        deleted: zod.boolean().nullish(),
        name: zod
            .string()
            .max(warehouseSavedQueriesMaterializeCreateBodyNameMax)
            .describe(
                'Unique name for the view. Used as the table name in HogQL queries and the node name in the data modeling Node.'
            ),
        query: zod
            .unknown()
            .nullish()
            .describe(
                'HogQL query definition as a JSON object with a "query" key containing the SQL string and a "kind" key containing the query type. Example: {"query": "SELECT * FROM events LIMIT 100", "kind": "HogQLQuery"}'
            ),
        folder_id: zod
            .string()
            .nullish()
            .describe('Optional folder ID used to organize this view in the SQL editor sidebar.'),
        edited_history_id: zod
            .string()
            .nullish()
            .describe('Activity log ID from the last known edit. Used for conflict detection.'),
        soft_update: zod
            .boolean()
            .nullish()
            .describe('If true, skip column inference and validation. For saving drafts.'),
        dag_id: zod.string().nullish().describe('Optional DAG to place this view into'),
        is_test: zod.boolean().optional().describe('Whether this view is for testing only and will auto-expire.'),
    })
    .describe(
        'Shared methods for DataWarehouseSavedQuery serializers.\n\nThis mixin is intended to be used with serializers.ModelSerializer subclasses.'
    )

/**
 * Undo materialization, revert back to the original view.
(i.e. delete the materialized table and the schedule)
 */
export const WarehouseSavedQueriesRevertMaterializationCreateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this data warehouse saved query.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const warehouseSavedQueriesRevertMaterializationCreateBodyNameMax = 128

export const WarehouseSavedQueriesRevertMaterializationCreateBody = /* @__PURE__ */ zod
    .object({
        deleted: zod.boolean().nullish(),
        name: zod
            .string()
            .max(warehouseSavedQueriesRevertMaterializationCreateBodyNameMax)
            .describe(
                'Unique name for the view. Used as the table name in HogQL queries and the node name in the data modeling Node.'
            ),
        query: zod
            .unknown()
            .nullish()
            .describe(
                'HogQL query definition as a JSON object with a "query" key containing the SQL string and a "kind" key containing the query type. Example: {"query": "SELECT * FROM events LIMIT 100", "kind": "HogQLQuery"}'
            ),
        folder_id: zod
            .string()
            .nullish()
            .describe('Optional folder ID used to organize this view in the SQL editor sidebar.'),
        edited_history_id: zod
            .string()
            .nullish()
            .describe('Activity log ID from the last known edit. Used for conflict detection.'),
        soft_update: zod
            .boolean()
            .nullish()
            .describe('If true, skip column inference and validation. For saving drafts.'),
        dag_id: zod.string().nullish().describe('Optional DAG to place this view into'),
        is_test: zod.boolean().optional().describe('Whether this view is for testing only and will auto-expire.'),
    })
    .describe(
        'Shared methods for DataWarehouseSavedQuery serializers.\n\nThis mixin is intended to be used with serializers.ModelSerializer subclasses.'
    )

/**
 * Run this saved query.
 */
export const WarehouseSavedQueriesRunCreateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this data warehouse saved query.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const warehouseSavedQueriesRunCreateBodyNameMax = 128

export const WarehouseSavedQueriesRunCreateBody = /* @__PURE__ */ zod
    .object({
        deleted: zod.boolean().nullish(),
        name: zod
            .string()
            .max(warehouseSavedQueriesRunCreateBodyNameMax)
            .describe(
                'Unique name for the view. Used as the table name in HogQL queries and the node name in the data modeling Node.'
            ),
        query: zod
            .unknown()
            .nullish()
            .describe(
                'HogQL query definition as a JSON object with a "query" key containing the SQL string and a "kind" key containing the query type. Example: {"query": "SELECT * FROM events LIMIT 100", "kind": "HogQLQuery"}'
            ),
        folder_id: zod
            .string()
            .nullish()
            .describe('Optional folder ID used to organize this view in the SQL editor sidebar.'),
        edited_history_id: zod
            .string()
            .nullish()
            .describe('Activity log ID from the last known edit. Used for conflict detection.'),
        soft_update: zod
            .boolean()
            .nullish()
            .describe('If true, skip column inference and validation. For saving drafts.'),
        dag_id: zod.string().nullish().describe('Optional DAG to place this view into'),
        is_test: zod.boolean().optional().describe('Whether this view is for testing only and will auto-expire.'),
    })
    .describe(
        'Shared methods for DataWarehouseSavedQuery serializers.\n\nThis mixin is intended to be used with serializers.ModelSerializer subclasses.'
    )

/**
 * Return the recent run history (up to 5 most recent) for this materialized view.
 */
export const WarehouseSavedQueriesRunHistoryRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this data warehouse saved query.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})
