/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 70 ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

export const FixHogqlRetrieveParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const FixHogqlCreateParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const LineageGetUpstreamRetrieveParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Get all views associated with a specific managed viewset.
GET /api/environments/{team_id}/managed_viewsets/{kind}/
 */
export const ManagedViewsetsRetrieveParams = zod.object({
    kind: zod.enum(['revenue_analytics']),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Enable or disable a managed viewset by kind.
PUT /api/environments/{team_id}/managed_viewsets/{kind}/ with body {"enabled": true/false}
 */
export const ManagedViewsetsUpdateParams = zod.object({
    kind: zod.enum(['revenue_analytics']),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const WarehouseSavedQueryDraftsListParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const WarehouseSavedQueryDraftsListQueryParams = zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

export const warehouseSavedQueryDraftsListResponseResultsItemEditedHistoryIdMax = 255

export const WarehouseSavedQueryDraftsListResponse = zod.object({
    count: zod.number(),
    next: zod.string().url().nullish(),
    previous: zod.string().url().nullish(),
    results: zod.array(
        zod.object({
            id: zod.string(),
            created_at: zod.string().datetime({}),
            updated_at: zod.string().datetime({}).nullable(),
            query: zod.unknown().optional().describe('HogQL query draft'),
            saved_query_id: zod.string().nullish(),
            name: zod.string().nullish(),
            edited_history_id: zod
                .string()
                .max(warehouseSavedQueryDraftsListResponseResultsItemEditedHistoryIdMax)
                .nullish()
                .describe('view history id that the draft branched from'),
        })
    ),
})

export const WarehouseSavedQueryDraftsCreateParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const warehouseSavedQueryDraftsCreateBodyEditedHistoryIdMax = 255

export const WarehouseSavedQueryDraftsCreateBody = zod.object({
    query: zod.unknown().optional().describe('HogQL query draft'),
    saved_query_id: zod.string().nullish(),
    name: zod.string().nullish(),
    edited_history_id: zod
        .string()
        .max(warehouseSavedQueryDraftsCreateBodyEditedHistoryIdMax)
        .nullish()
        .describe('view history id that the draft branched from'),
})

export const WarehouseSavedQueryDraftsRetrieveParams = zod.object({
    id: zod.string().describe('A UUID string identifying this data warehouse saved query draft.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const warehouseSavedQueryDraftsRetrieveResponseEditedHistoryIdMax = 255

export const WarehouseSavedQueryDraftsRetrieveResponse = zod.object({
    id: zod.string(),
    created_at: zod.string().datetime({}),
    updated_at: zod.string().datetime({}).nullable(),
    query: zod.unknown().optional().describe('HogQL query draft'),
    saved_query_id: zod.string().nullish(),
    name: zod.string().nullish(),
    edited_history_id: zod
        .string()
        .max(warehouseSavedQueryDraftsRetrieveResponseEditedHistoryIdMax)
        .nullish()
        .describe('view history id that the draft branched from'),
})

export const WarehouseSavedQueryDraftsUpdateParams = zod.object({
    id: zod.string().describe('A UUID string identifying this data warehouse saved query draft.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const warehouseSavedQueryDraftsUpdateBodyEditedHistoryIdMax = 255

export const WarehouseSavedQueryDraftsUpdateBody = zod.object({
    query: zod.unknown().optional().describe('HogQL query draft'),
    saved_query_id: zod.string().nullish(),
    name: zod.string().nullish(),
    edited_history_id: zod
        .string()
        .max(warehouseSavedQueryDraftsUpdateBodyEditedHistoryIdMax)
        .nullish()
        .describe('view history id that the draft branched from'),
})

export const warehouseSavedQueryDraftsUpdateResponseEditedHistoryIdMax = 255

export const WarehouseSavedQueryDraftsUpdateResponse = zod.object({
    id: zod.string(),
    created_at: zod.string().datetime({}),
    updated_at: zod.string().datetime({}).nullable(),
    query: zod.unknown().optional().describe('HogQL query draft'),
    saved_query_id: zod.string().nullish(),
    name: zod.string().nullish(),
    edited_history_id: zod
        .string()
        .max(warehouseSavedQueryDraftsUpdateResponseEditedHistoryIdMax)
        .nullish()
        .describe('view history id that the draft branched from'),
})

export const WarehouseSavedQueryDraftsPartialUpdateParams = zod.object({
    id: zod.string().describe('A UUID string identifying this data warehouse saved query draft.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const warehouseSavedQueryDraftsPartialUpdateBodyEditedHistoryIdMax = 255

export const WarehouseSavedQueryDraftsPartialUpdateBody = zod.object({
    query: zod.unknown().optional().describe('HogQL query draft'),
    saved_query_id: zod.string().nullish(),
    name: zod.string().nullish(),
    edited_history_id: zod
        .string()
        .max(warehouseSavedQueryDraftsPartialUpdateBodyEditedHistoryIdMax)
        .nullish()
        .describe('view history id that the draft branched from'),
})

export const warehouseSavedQueryDraftsPartialUpdateResponseEditedHistoryIdMax = 255

export const WarehouseSavedQueryDraftsPartialUpdateResponse = zod.object({
    id: zod.string(),
    created_at: zod.string().datetime({}),
    updated_at: zod.string().datetime({}).nullable(),
    query: zod.unknown().optional().describe('HogQL query draft'),
    saved_query_id: zod.string().nullish(),
    name: zod.string().nullish(),
    edited_history_id: zod
        .string()
        .max(warehouseSavedQueryDraftsPartialUpdateResponseEditedHistoryIdMax)
        .nullish()
        .describe('view history id that the draft branched from'),
})

export const WarehouseSavedQueryDraftsDestroyParams = zod.object({
    id: zod.string().describe('A UUID string identifying this data warehouse saved query draft.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * List data modeling jobs which are "runs" for our saved queries.
 */
export const DataModelingJobsListParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const DataModelingJobsListQueryParams = zod.object({
    cursor: zod.string().optional().describe('The pagination cursor value.'),
    limit: zod.number().optional().describe('Number of results to return per page.'),
    saved_query_id: zod.string().nullish(),
})

export const DataModelingJobsListResponse = zod.object({
    next: zod.string().url().nullish(),
    previous: zod.string().url().nullish(),
    results: zod.array(
        zod.object({
            id: zod.string(),
            saved_query_id: zod.string().nullable(),
            status: zod
                .enum(['Cancelled', 'Completed', 'Failed', 'Running'])
                .describe(
                    '* `Cancelled` - Cancelled\n* `Completed` - Completed\n* `Failed` - Failed\n* `Running` - Running'
                ),
            rows_materialized: zod.number(),
            error: zod.string().nullable(),
            created_at: zod.string().datetime({}),
            last_run_at: zod.string().datetime({}),
            workflow_id: zod.string().nullable(),
            workflow_run_id: zod.string().nullable(),
            rows_expected: zod.number().nullable().describe('Total rows expected to be materialized'),
        })
    ),
})

/**
 * List data modeling jobs which are "runs" for our saved queries.
 */
export const DataModelingJobsRetrieveParams = zod.object({
    id: zod.string().describe('A UUID string identifying this data modeling job.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const DataModelingJobsRetrieveResponse = zod.object({
    id: zod.string(),
    saved_query_id: zod.string().nullable(),
    status: zod
        .enum(['Cancelled', 'Completed', 'Failed', 'Running'])
        .describe('* `Cancelled` - Cancelled\n* `Completed` - Completed\n* `Failed` - Failed\n* `Running` - Running'),
    rows_materialized: zod.number(),
    error: zod.string().nullable(),
    created_at: zod.string().datetime({}),
    last_run_at: zod.string().datetime({}),
    workflow_id: zod.string().nullable(),
    workflow_run_id: zod.string().nullable(),
    rows_expected: zod.number().nullable().describe('Total rows expected to be materialized'),
})

/**
 * Get the most recent non-running job for each saved query from the v2 backend.
 */
export const DataModelingJobsRecentRetrieveParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const DataModelingJobsRecentRetrieveResponse = zod.object({
    id: zod.string(),
    saved_query_id: zod.string().nullable(),
    status: zod
        .enum(['Cancelled', 'Completed', 'Failed', 'Running'])
        .describe('* `Cancelled` - Cancelled\n* `Completed` - Completed\n* `Failed` - Failed\n* `Running` - Running'),
    rows_materialized: zod.number(),
    error: zod.string().nullable(),
    created_at: zod.string().datetime({}),
    last_run_at: zod.string().datetime({}),
    workflow_id: zod.string().nullable(),
    workflow_run_id: zod.string().nullable(),
    rows_expected: zod.number().nullable().describe('Total rows expected to be materialized'),
})

/**
 * Get all currently running jobs from the v2 backend.
 */
export const DataModelingJobsRunningRetrieveParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const DataModelingJobsRunningRetrieveResponse = zod.object({
    id: zod.string(),
    saved_query_id: zod.string().nullable(),
    status: zod
        .enum(['Cancelled', 'Completed', 'Failed', 'Running'])
        .describe('* `Cancelled` - Cancelled\n* `Completed` - Completed\n* `Failed` - Failed\n* `Running` - Running'),
    rows_materialized: zod.number(),
    error: zod.string().nullable(),
    created_at: zod.string().datetime({}),
    last_run_at: zod.string().datetime({}),
    workflow_id: zod.string().nullable(),
    workflow_run_id: zod.string().nullable(),
    rows_expected: zod.number().nullable().describe('Total rows expected to be materialized'),
})

/**
 * Returns completed/non-running activities (jobs with status 'Completed').
Supports pagination and cutoff time filtering.
 */
export const DataWarehouseCompletedActivityRetrieveParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Returns failed/disabled data pipeline items for the Pipeline status side panel.
Includes: materializations, syncs, sources, destinations, and transformations.
 */
export const DataWarehouseDataHealthIssuesRetrieveParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Returns success and failed job statistics for the last 1, 7, or 30 days.
Query parameter 'days' can be 1, 7, or 30 (default: 7).
 */
export const DataWarehouseJobStatsRetrieveParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * API endpoints for data warehouse aggregate statistics and operations.
 */
export const DataWarehousePropertyValuesRetrieveParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Returns currently running activities (jobs with status 'Running').
Supports pagination and cutoff time filtering.
 */
export const DataWarehouseRunningActivityRetrieveParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Returns aggregated statistics for the data warehouse total rows processed within the current billing period.
Used by the frontend data warehouse scene to display usage information.
 */
export const DataWarehouseTotalRowsStatsRetrieveParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ExternalDataSchemasListParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ExternalDataSchemasListQueryParams = zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
    search: zod.string().optional().describe('A search term.'),
})

export const ExternalDataSchemasListResponse = zod.object({
    count: zod.number(),
    next: zod.string().url().nullish(),
    previous: zod.string().url().nullish(),
    results: zod.array(
        zod.object({
            id: zod.string(),
            name: zod.string(),
            table: zod.record(zod.string(), zod.unknown()).nullable(),
            should_sync: zod.boolean().optional(),
            last_synced_at: zod.string().datetime({}).nullable(),
            latest_error: zod.string().nullable().describe('The latest error that occurred when syncing this schema.'),
            incremental: zod.boolean(),
            status: zod.string().nullable(),
            sync_type: zod.enum(['full_refresh', 'incremental', 'append']).nullable(),
            incremental_field: zod.string().nullable(),
            incremental_field_type: zod.string().nullable(),
            sync_frequency: zod.string(),
            sync_time_of_day: zod.string(),
        })
    ),
})

export const ExternalDataSchemasCreateParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ExternalDataSchemasCreateBody = zod.object({
    should_sync: zod.boolean().optional(),
})

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const ExternalDataSourcesListParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ExternalDataSourcesListQueryParams = zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
    search: zod.string().optional().describe('A search term.'),
})

export const externalDataSourcesListResponseResultsItemPrefixMax = 100

export const externalDataSourcesListResponseResultsItemDescriptionMax = 400

export const ExternalDataSourcesListResponse = zod.object({
    count: zod.number(),
    next: zod.string().url().nullish(),
    previous: zod.string().url().nullish(),
    results: zod.array(
        zod
            .object({
                id: zod.string(),
                created_at: zod.string().datetime({}),
                created_by: zod.string().nullable(),
                status: zod.string(),
                client_secret: zod.string(),
                account_id: zod.string(),
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
                    ])
                    .describe(
                        '* `Ashby` - Ashby\n* `Supabase` - Supabase\n* `CustomerIO` - CustomerIO\n* `Github` - Github\n* `Stripe` - Stripe\n* `Hubspot` - Hubspot\n* `Postgres` - Postgres\n* `Zendesk` - Zendesk\n* `Snowflake` - Snowflake\n* `Salesforce` - Salesforce\n* `MySQL` - MySQL\n* `MongoDB` - MongoDB\n* `MSSQL` - MSSQL\n* `Vitally` - Vitally\n* `BigQuery` - BigQuery\n* `Chargebee` - Chargebee\n* `Clerk` - Clerk\n* `GoogleAds` - GoogleAds\n* `TemporalIO` - TemporalIO\n* `DoIt` - DoIt\n* `GoogleSheets` - GoogleSheets\n* `MetaAds` - MetaAds\n* `Klaviyo` - Klaviyo\n* `Mailchimp` - Mailchimp\n* `Braze` - Braze\n* `Mailjet` - Mailjet\n* `Redshift` - Redshift\n* `Polar` - Polar\n* `RevenueCat` - RevenueCat\n* `LinkedinAds` - LinkedinAds\n* `RedditAds` - RedditAds\n* `TikTokAds` - TikTokAds\n* `BingAds` - BingAds\n* `Shopify` - Shopify\n* `Attio` - Attio\n* `SnapchatAds` - SnapchatAds\n* `Linear` - Linear\n* `Intercom` - Intercom\n* `Amplitude` - Amplitude\n* `Mixpanel` - Mixpanel\n* `Jira` - Jira\n* `ActiveCampaign` - ActiveCampaign\n* `Marketo` - Marketo\n* `Adjust` - Adjust\n* `AppsFlyer` - AppsFlyer\n* `Freshdesk` - Freshdesk\n* `GoogleAnalytics` - GoogleAnalytics\n* `Pipedrive` - Pipedrive\n* `SendGrid` - SendGrid\n* `Slack` - Slack\n* `PagerDuty` - PagerDuty\n* `Asana` - Asana\n* `Notion` - Notion\n* `Airtable` - Airtable\n* `Greenhouse` - Greenhouse\n* `BambooHR` - BambooHR\n* `Lever` - Lever\n* `GitLab` - GitLab\n* `Datadog` - Datadog\n* `Sentry` - Sentry\n* `Pendo` - Pendo\n* `FullStory` - FullStory\n* `AmazonAds` - AmazonAds\n* `PinterestAds` - PinterestAds\n* `AppleSearchAds` - AppleSearchAds\n* `QuickBooks` - QuickBooks\n* `Xero` - Xero\n* `NetSuite` - NetSuite\n* `WooCommerce` - WooCommerce\n* `BigCommerce` - BigCommerce\n* `PayPal` - PayPal\n* `Square` - Square\n* `Zoom` - Zoom\n* `Trello` - Trello\n* `Monday` - Monday\n* `ClickUp` - ClickUp\n* `Confluence` - Confluence\n* `Recurly` - Recurly\n* `SalesLoft` - SalesLoft\n* `Outreach` - Outreach\n* `Gong` - Gong\n* `Calendly` - Calendly\n* `Typeform` - Typeform\n* `Iterable` - Iterable\n* `ZohoCRM` - ZohoCRM\n* `Close` - Close\n* `Oracle` - Oracle\n* `DynamoDB` - DynamoDB\n* `Elasticsearch` - Elasticsearch\n* `Kafka` - Kafka\n* `LaunchDarkly` - LaunchDarkly\n* `Braintree` - Braintree\n* `Recharge` - Recharge\n* `HelpScout` - HelpScout\n* `Gorgias` - Gorgias\n* `Instagram` - Instagram\n* `YouTubeAnalytics` - YouTubeAnalytics\n* `FacebookPages` - FacebookPages\n* `TwitterAds` - TwitterAds\n* `Workday` - Workday\n* `ServiceNow` - ServiceNow\n* `Pardot` - Pardot\n* `Copper` - Copper\n* `Front` - Front\n* `ChartMogul` - ChartMogul\n* `Zuora` - Zuora\n* `Paddle` - Paddle\n* `CircleCI` - CircleCI\n* `CockroachDB` - CockroachDB\n* `Firebase` - Firebase\n* `AzureBlob` - AzureBlob\n* `GoogleDrive` - GoogleDrive\n* `OneDrive` - OneDrive\n* `SharePoint` - SharePoint\n* `Box` - Box\n* `SFTP` - SFTP\n* `MicrosoftTeams` - MicrosoftTeams\n* `Aircall` - Aircall\n* `Webflow` - Webflow\n* `Okta` - Okta\n* `Auth0` - Auth0\n* `Productboard` - Productboard\n* `Smartsheet` - Smartsheet\n* `Wrike` - Wrike\n* `Plaid` - Plaid\n* `SurveyMonkey` - SurveyMonkey\n* `Eventbrite` - Eventbrite\n* `RingCentral` - RingCentral\n* `Twilio` - Twilio\n* `Freshsales` - Freshsales\n* `Shortcut` - Shortcut\n* `ConvertKit` - ConvertKit\n* `Drip` - Drip\n* `CampaignMonitor` - CampaignMonitor\n* `MailerLite` - MailerLite\n* `Omnisend` - Omnisend\n* `Brevo` - Brevo\n* `Postmark` - Postmark\n* `Granola` - Granola\n* `BuildBetter` - BuildBetter'
                    ),
                latest_error: zod.string(),
                prefix: zod.string().max(externalDataSourcesListResponseResultsItemPrefixMax).nullish(),
                description: zod.string().max(externalDataSourcesListResponseResultsItemDescriptionMax).nullish(),
                access_method: zod
                    .enum(['warehouse', 'direct'])
                    .describe('* `warehouse` - warehouse\n* `direct` - direct'),
                last_run_at: zod.string(),
                schemas: zod.string(),
                job_inputs: zod.unknown().nullish(),
                revenue_analytics_config: zod.object({
                    enabled: zod.boolean().optional(),
                    include_invoiceless_charges: zod.boolean().optional(),
                }),
                user_access_level: zod
                    .string()
                    .nullable()
                    .describe('The effective access level the user has for this object'),
            })
            .describe('Mixin for serializers to add user access control fields')
    ),
})

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const ExternalDataSourcesCreateParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const externalDataSourcesCreateBodyPrefixMax = 100

export const externalDataSourcesCreateBodyDescriptionMax = 400

export const ExternalDataSourcesCreateBody = zod
    .object({
        client_secret: zod.string(),
        account_id: zod.string(),
        prefix: zod.string().max(externalDataSourcesCreateBodyPrefixMax).nullish(),
        description: zod.string().max(externalDataSourcesCreateBodyDescriptionMax).nullish(),
        job_inputs: zod.unknown().nullish(),
    })
    .describe('Mixin for serializers to add user access control fields')

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const ExternalDataSourcesRetrieveParams = zod.object({
    id: zod.string().describe('A UUID string identifying this external data source.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const externalDataSourcesRetrieveResponsePrefixMax = 100

export const externalDataSourcesRetrieveResponseDescriptionMax = 400

export const ExternalDataSourcesRetrieveResponse = zod
    .object({
        id: zod.string(),
        created_at: zod.string().datetime({}),
        created_by: zod.string().nullable(),
        status: zod.string(),
        client_secret: zod.string(),
        account_id: zod.string(),
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
            ])
            .describe(
                '* `Ashby` - Ashby\n* `Supabase` - Supabase\n* `CustomerIO` - CustomerIO\n* `Github` - Github\n* `Stripe` - Stripe\n* `Hubspot` - Hubspot\n* `Postgres` - Postgres\n* `Zendesk` - Zendesk\n* `Snowflake` - Snowflake\n* `Salesforce` - Salesforce\n* `MySQL` - MySQL\n* `MongoDB` - MongoDB\n* `MSSQL` - MSSQL\n* `Vitally` - Vitally\n* `BigQuery` - BigQuery\n* `Chargebee` - Chargebee\n* `Clerk` - Clerk\n* `GoogleAds` - GoogleAds\n* `TemporalIO` - TemporalIO\n* `DoIt` - DoIt\n* `GoogleSheets` - GoogleSheets\n* `MetaAds` - MetaAds\n* `Klaviyo` - Klaviyo\n* `Mailchimp` - Mailchimp\n* `Braze` - Braze\n* `Mailjet` - Mailjet\n* `Redshift` - Redshift\n* `Polar` - Polar\n* `RevenueCat` - RevenueCat\n* `LinkedinAds` - LinkedinAds\n* `RedditAds` - RedditAds\n* `TikTokAds` - TikTokAds\n* `BingAds` - BingAds\n* `Shopify` - Shopify\n* `Attio` - Attio\n* `SnapchatAds` - SnapchatAds\n* `Linear` - Linear\n* `Intercom` - Intercom\n* `Amplitude` - Amplitude\n* `Mixpanel` - Mixpanel\n* `Jira` - Jira\n* `ActiveCampaign` - ActiveCampaign\n* `Marketo` - Marketo\n* `Adjust` - Adjust\n* `AppsFlyer` - AppsFlyer\n* `Freshdesk` - Freshdesk\n* `GoogleAnalytics` - GoogleAnalytics\n* `Pipedrive` - Pipedrive\n* `SendGrid` - SendGrid\n* `Slack` - Slack\n* `PagerDuty` - PagerDuty\n* `Asana` - Asana\n* `Notion` - Notion\n* `Airtable` - Airtable\n* `Greenhouse` - Greenhouse\n* `BambooHR` - BambooHR\n* `Lever` - Lever\n* `GitLab` - GitLab\n* `Datadog` - Datadog\n* `Sentry` - Sentry\n* `Pendo` - Pendo\n* `FullStory` - FullStory\n* `AmazonAds` - AmazonAds\n* `PinterestAds` - PinterestAds\n* `AppleSearchAds` - AppleSearchAds\n* `QuickBooks` - QuickBooks\n* `Xero` - Xero\n* `NetSuite` - NetSuite\n* `WooCommerce` - WooCommerce\n* `BigCommerce` - BigCommerce\n* `PayPal` - PayPal\n* `Square` - Square\n* `Zoom` - Zoom\n* `Trello` - Trello\n* `Monday` - Monday\n* `ClickUp` - ClickUp\n* `Confluence` - Confluence\n* `Recurly` - Recurly\n* `SalesLoft` - SalesLoft\n* `Outreach` - Outreach\n* `Gong` - Gong\n* `Calendly` - Calendly\n* `Typeform` - Typeform\n* `Iterable` - Iterable\n* `ZohoCRM` - ZohoCRM\n* `Close` - Close\n* `Oracle` - Oracle\n* `DynamoDB` - DynamoDB\n* `Elasticsearch` - Elasticsearch\n* `Kafka` - Kafka\n* `LaunchDarkly` - LaunchDarkly\n* `Braintree` - Braintree\n* `Recharge` - Recharge\n* `HelpScout` - HelpScout\n* `Gorgias` - Gorgias\n* `Instagram` - Instagram\n* `YouTubeAnalytics` - YouTubeAnalytics\n* `FacebookPages` - FacebookPages\n* `TwitterAds` - TwitterAds\n* `Workday` - Workday\n* `ServiceNow` - ServiceNow\n* `Pardot` - Pardot\n* `Copper` - Copper\n* `Front` - Front\n* `ChartMogul` - ChartMogul\n* `Zuora` - Zuora\n* `Paddle` - Paddle\n* `CircleCI` - CircleCI\n* `CockroachDB` - CockroachDB\n* `Firebase` - Firebase\n* `AzureBlob` - AzureBlob\n* `GoogleDrive` - GoogleDrive\n* `OneDrive` - OneDrive\n* `SharePoint` - SharePoint\n* `Box` - Box\n* `SFTP` - SFTP\n* `MicrosoftTeams` - MicrosoftTeams\n* `Aircall` - Aircall\n* `Webflow` - Webflow\n* `Okta` - Okta\n* `Auth0` - Auth0\n* `Productboard` - Productboard\n* `Smartsheet` - Smartsheet\n* `Wrike` - Wrike\n* `Plaid` - Plaid\n* `SurveyMonkey` - SurveyMonkey\n* `Eventbrite` - Eventbrite\n* `RingCentral` - RingCentral\n* `Twilio` - Twilio\n* `Freshsales` - Freshsales\n* `Shortcut` - Shortcut\n* `ConvertKit` - ConvertKit\n* `Drip` - Drip\n* `CampaignMonitor` - CampaignMonitor\n* `MailerLite` - MailerLite\n* `Omnisend` - Omnisend\n* `Brevo` - Brevo\n* `Postmark` - Postmark\n* `Granola` - Granola\n* `BuildBetter` - BuildBetter'
            ),
        latest_error: zod.string(),
        prefix: zod.string().max(externalDataSourcesRetrieveResponsePrefixMax).nullish(),
        description: zod.string().max(externalDataSourcesRetrieveResponseDescriptionMax).nullish(),
        access_method: zod.enum(['warehouse', 'direct']).describe('* `warehouse` - warehouse\n* `direct` - direct'),
        last_run_at: zod.string(),
        schemas: zod.string(),
        job_inputs: zod.unknown().nullish(),
        revenue_analytics_config: zod.object({
            enabled: zod.boolean().optional(),
            include_invoiceless_charges: zod.boolean().optional(),
        }),
        user_access_level: zod.string().nullable().describe('The effective access level the user has for this object'),
    })
    .describe('Mixin for serializers to add user access control fields')

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const ExternalDataSourcesUpdateParams = zod.object({
    id: zod.string().describe('A UUID string identifying this external data source.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const externalDataSourcesUpdateBodyPrefixMax = 100

export const externalDataSourcesUpdateBodyDescriptionMax = 400

export const ExternalDataSourcesUpdateBody = zod
    .object({
        client_secret: zod.string(),
        account_id: zod.string(),
        prefix: zod.string().max(externalDataSourcesUpdateBodyPrefixMax).nullish(),
        description: zod.string().max(externalDataSourcesUpdateBodyDescriptionMax).nullish(),
        job_inputs: zod.unknown().nullish(),
    })
    .describe('Mixin for serializers to add user access control fields')

export const externalDataSourcesUpdateResponsePrefixMax = 100

export const externalDataSourcesUpdateResponseDescriptionMax = 400

export const ExternalDataSourcesUpdateResponse = zod
    .object({
        id: zod.string(),
        created_at: zod.string().datetime({}),
        created_by: zod.string().nullable(),
        status: zod.string(),
        client_secret: zod.string(),
        account_id: zod.string(),
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
            ])
            .describe(
                '* `Ashby` - Ashby\n* `Supabase` - Supabase\n* `CustomerIO` - CustomerIO\n* `Github` - Github\n* `Stripe` - Stripe\n* `Hubspot` - Hubspot\n* `Postgres` - Postgres\n* `Zendesk` - Zendesk\n* `Snowflake` - Snowflake\n* `Salesforce` - Salesforce\n* `MySQL` - MySQL\n* `MongoDB` - MongoDB\n* `MSSQL` - MSSQL\n* `Vitally` - Vitally\n* `BigQuery` - BigQuery\n* `Chargebee` - Chargebee\n* `Clerk` - Clerk\n* `GoogleAds` - GoogleAds\n* `TemporalIO` - TemporalIO\n* `DoIt` - DoIt\n* `GoogleSheets` - GoogleSheets\n* `MetaAds` - MetaAds\n* `Klaviyo` - Klaviyo\n* `Mailchimp` - Mailchimp\n* `Braze` - Braze\n* `Mailjet` - Mailjet\n* `Redshift` - Redshift\n* `Polar` - Polar\n* `RevenueCat` - RevenueCat\n* `LinkedinAds` - LinkedinAds\n* `RedditAds` - RedditAds\n* `TikTokAds` - TikTokAds\n* `BingAds` - BingAds\n* `Shopify` - Shopify\n* `Attio` - Attio\n* `SnapchatAds` - SnapchatAds\n* `Linear` - Linear\n* `Intercom` - Intercom\n* `Amplitude` - Amplitude\n* `Mixpanel` - Mixpanel\n* `Jira` - Jira\n* `ActiveCampaign` - ActiveCampaign\n* `Marketo` - Marketo\n* `Adjust` - Adjust\n* `AppsFlyer` - AppsFlyer\n* `Freshdesk` - Freshdesk\n* `GoogleAnalytics` - GoogleAnalytics\n* `Pipedrive` - Pipedrive\n* `SendGrid` - SendGrid\n* `Slack` - Slack\n* `PagerDuty` - PagerDuty\n* `Asana` - Asana\n* `Notion` - Notion\n* `Airtable` - Airtable\n* `Greenhouse` - Greenhouse\n* `BambooHR` - BambooHR\n* `Lever` - Lever\n* `GitLab` - GitLab\n* `Datadog` - Datadog\n* `Sentry` - Sentry\n* `Pendo` - Pendo\n* `FullStory` - FullStory\n* `AmazonAds` - AmazonAds\n* `PinterestAds` - PinterestAds\n* `AppleSearchAds` - AppleSearchAds\n* `QuickBooks` - QuickBooks\n* `Xero` - Xero\n* `NetSuite` - NetSuite\n* `WooCommerce` - WooCommerce\n* `BigCommerce` - BigCommerce\n* `PayPal` - PayPal\n* `Square` - Square\n* `Zoom` - Zoom\n* `Trello` - Trello\n* `Monday` - Monday\n* `ClickUp` - ClickUp\n* `Confluence` - Confluence\n* `Recurly` - Recurly\n* `SalesLoft` - SalesLoft\n* `Outreach` - Outreach\n* `Gong` - Gong\n* `Calendly` - Calendly\n* `Typeform` - Typeform\n* `Iterable` - Iterable\n* `ZohoCRM` - ZohoCRM\n* `Close` - Close\n* `Oracle` - Oracle\n* `DynamoDB` - DynamoDB\n* `Elasticsearch` - Elasticsearch\n* `Kafka` - Kafka\n* `LaunchDarkly` - LaunchDarkly\n* `Braintree` - Braintree\n* `Recharge` - Recharge\n* `HelpScout` - HelpScout\n* `Gorgias` - Gorgias\n* `Instagram` - Instagram\n* `YouTubeAnalytics` - YouTubeAnalytics\n* `FacebookPages` - FacebookPages\n* `TwitterAds` - TwitterAds\n* `Workday` - Workday\n* `ServiceNow` - ServiceNow\n* `Pardot` - Pardot\n* `Copper` - Copper\n* `Front` - Front\n* `ChartMogul` - ChartMogul\n* `Zuora` - Zuora\n* `Paddle` - Paddle\n* `CircleCI` - CircleCI\n* `CockroachDB` - CockroachDB\n* `Firebase` - Firebase\n* `AzureBlob` - AzureBlob\n* `GoogleDrive` - GoogleDrive\n* `OneDrive` - OneDrive\n* `SharePoint` - SharePoint\n* `Box` - Box\n* `SFTP` - SFTP\n* `MicrosoftTeams` - MicrosoftTeams\n* `Aircall` - Aircall\n* `Webflow` - Webflow\n* `Okta` - Okta\n* `Auth0` - Auth0\n* `Productboard` - Productboard\n* `Smartsheet` - Smartsheet\n* `Wrike` - Wrike\n* `Plaid` - Plaid\n* `SurveyMonkey` - SurveyMonkey\n* `Eventbrite` - Eventbrite\n* `RingCentral` - RingCentral\n* `Twilio` - Twilio\n* `Freshsales` - Freshsales\n* `Shortcut` - Shortcut\n* `ConvertKit` - ConvertKit\n* `Drip` - Drip\n* `CampaignMonitor` - CampaignMonitor\n* `MailerLite` - MailerLite\n* `Omnisend` - Omnisend\n* `Brevo` - Brevo\n* `Postmark` - Postmark\n* `Granola` - Granola\n* `BuildBetter` - BuildBetter'
            ),
        latest_error: zod.string(),
        prefix: zod.string().max(externalDataSourcesUpdateResponsePrefixMax).nullish(),
        description: zod.string().max(externalDataSourcesUpdateResponseDescriptionMax).nullish(),
        access_method: zod.enum(['warehouse', 'direct']).describe('* `warehouse` - warehouse\n* `direct` - direct'),
        last_run_at: zod.string(),
        schemas: zod.string(),
        job_inputs: zod.unknown().nullish(),
        revenue_analytics_config: zod.object({
            enabled: zod.boolean().optional(),
            include_invoiceless_charges: zod.boolean().optional(),
        }),
        user_access_level: zod.string().nullable().describe('The effective access level the user has for this object'),
    })
    .describe('Mixin for serializers to add user access control fields')

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const ExternalDataSourcesPartialUpdateParams = zod.object({
    id: zod.string().describe('A UUID string identifying this external data source.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const externalDataSourcesPartialUpdateBodyPrefixMax = 100

export const externalDataSourcesPartialUpdateBodyDescriptionMax = 400

export const ExternalDataSourcesPartialUpdateBody = zod
    .object({
        client_secret: zod.string().optional(),
        account_id: zod.string().optional(),
        prefix: zod.string().max(externalDataSourcesPartialUpdateBodyPrefixMax).nullish(),
        description: zod.string().max(externalDataSourcesPartialUpdateBodyDescriptionMax).nullish(),
        job_inputs: zod.unknown().nullish(),
    })
    .describe('Mixin for serializers to add user access control fields')

export const externalDataSourcesPartialUpdateResponsePrefixMax = 100

export const externalDataSourcesPartialUpdateResponseDescriptionMax = 400

export const ExternalDataSourcesPartialUpdateResponse = zod
    .object({
        id: zod.string(),
        created_at: zod.string().datetime({}),
        created_by: zod.string().nullable(),
        status: zod.string(),
        client_secret: zod.string(),
        account_id: zod.string(),
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
            ])
            .describe(
                '* `Ashby` - Ashby\n* `Supabase` - Supabase\n* `CustomerIO` - CustomerIO\n* `Github` - Github\n* `Stripe` - Stripe\n* `Hubspot` - Hubspot\n* `Postgres` - Postgres\n* `Zendesk` - Zendesk\n* `Snowflake` - Snowflake\n* `Salesforce` - Salesforce\n* `MySQL` - MySQL\n* `MongoDB` - MongoDB\n* `MSSQL` - MSSQL\n* `Vitally` - Vitally\n* `BigQuery` - BigQuery\n* `Chargebee` - Chargebee\n* `Clerk` - Clerk\n* `GoogleAds` - GoogleAds\n* `TemporalIO` - TemporalIO\n* `DoIt` - DoIt\n* `GoogleSheets` - GoogleSheets\n* `MetaAds` - MetaAds\n* `Klaviyo` - Klaviyo\n* `Mailchimp` - Mailchimp\n* `Braze` - Braze\n* `Mailjet` - Mailjet\n* `Redshift` - Redshift\n* `Polar` - Polar\n* `RevenueCat` - RevenueCat\n* `LinkedinAds` - LinkedinAds\n* `RedditAds` - RedditAds\n* `TikTokAds` - TikTokAds\n* `BingAds` - BingAds\n* `Shopify` - Shopify\n* `Attio` - Attio\n* `SnapchatAds` - SnapchatAds\n* `Linear` - Linear\n* `Intercom` - Intercom\n* `Amplitude` - Amplitude\n* `Mixpanel` - Mixpanel\n* `Jira` - Jira\n* `ActiveCampaign` - ActiveCampaign\n* `Marketo` - Marketo\n* `Adjust` - Adjust\n* `AppsFlyer` - AppsFlyer\n* `Freshdesk` - Freshdesk\n* `GoogleAnalytics` - GoogleAnalytics\n* `Pipedrive` - Pipedrive\n* `SendGrid` - SendGrid\n* `Slack` - Slack\n* `PagerDuty` - PagerDuty\n* `Asana` - Asana\n* `Notion` - Notion\n* `Airtable` - Airtable\n* `Greenhouse` - Greenhouse\n* `BambooHR` - BambooHR\n* `Lever` - Lever\n* `GitLab` - GitLab\n* `Datadog` - Datadog\n* `Sentry` - Sentry\n* `Pendo` - Pendo\n* `FullStory` - FullStory\n* `AmazonAds` - AmazonAds\n* `PinterestAds` - PinterestAds\n* `AppleSearchAds` - AppleSearchAds\n* `QuickBooks` - QuickBooks\n* `Xero` - Xero\n* `NetSuite` - NetSuite\n* `WooCommerce` - WooCommerce\n* `BigCommerce` - BigCommerce\n* `PayPal` - PayPal\n* `Square` - Square\n* `Zoom` - Zoom\n* `Trello` - Trello\n* `Monday` - Monday\n* `ClickUp` - ClickUp\n* `Confluence` - Confluence\n* `Recurly` - Recurly\n* `SalesLoft` - SalesLoft\n* `Outreach` - Outreach\n* `Gong` - Gong\n* `Calendly` - Calendly\n* `Typeform` - Typeform\n* `Iterable` - Iterable\n* `ZohoCRM` - ZohoCRM\n* `Close` - Close\n* `Oracle` - Oracle\n* `DynamoDB` - DynamoDB\n* `Elasticsearch` - Elasticsearch\n* `Kafka` - Kafka\n* `LaunchDarkly` - LaunchDarkly\n* `Braintree` - Braintree\n* `Recharge` - Recharge\n* `HelpScout` - HelpScout\n* `Gorgias` - Gorgias\n* `Instagram` - Instagram\n* `YouTubeAnalytics` - YouTubeAnalytics\n* `FacebookPages` - FacebookPages\n* `TwitterAds` - TwitterAds\n* `Workday` - Workday\n* `ServiceNow` - ServiceNow\n* `Pardot` - Pardot\n* `Copper` - Copper\n* `Front` - Front\n* `ChartMogul` - ChartMogul\n* `Zuora` - Zuora\n* `Paddle` - Paddle\n* `CircleCI` - CircleCI\n* `CockroachDB` - CockroachDB\n* `Firebase` - Firebase\n* `AzureBlob` - AzureBlob\n* `GoogleDrive` - GoogleDrive\n* `OneDrive` - OneDrive\n* `SharePoint` - SharePoint\n* `Box` - Box\n* `SFTP` - SFTP\n* `MicrosoftTeams` - MicrosoftTeams\n* `Aircall` - Aircall\n* `Webflow` - Webflow\n* `Okta` - Okta\n* `Auth0` - Auth0\n* `Productboard` - Productboard\n* `Smartsheet` - Smartsheet\n* `Wrike` - Wrike\n* `Plaid` - Plaid\n* `SurveyMonkey` - SurveyMonkey\n* `Eventbrite` - Eventbrite\n* `RingCentral` - RingCentral\n* `Twilio` - Twilio\n* `Freshsales` - Freshsales\n* `Shortcut` - Shortcut\n* `ConvertKit` - ConvertKit\n* `Drip` - Drip\n* `CampaignMonitor` - CampaignMonitor\n* `MailerLite` - MailerLite\n* `Omnisend` - Omnisend\n* `Brevo` - Brevo\n* `Postmark` - Postmark\n* `Granola` - Granola\n* `BuildBetter` - BuildBetter'
            ),
        latest_error: zod.string(),
        prefix: zod.string().max(externalDataSourcesPartialUpdateResponsePrefixMax).nullish(),
        description: zod.string().max(externalDataSourcesPartialUpdateResponseDescriptionMax).nullish(),
        access_method: zod.enum(['warehouse', 'direct']).describe('* `warehouse` - warehouse\n* `direct` - direct'),
        last_run_at: zod.string(),
        schemas: zod.string(),
        job_inputs: zod.unknown().nullish(),
        revenue_analytics_config: zod.object({
            enabled: zod.boolean().optional(),
            include_invoiceless_charges: zod.boolean().optional(),
        }),
        user_access_level: zod.string().nullable().describe('The effective access level the user has for this object'),
    })
    .describe('Mixin for serializers to add user access control fields')

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const ExternalDataSourcesDestroyParams = zod.object({
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
export const ExternalDataSourcesJobsRetrieveParams = zod.object({
    id: zod.string().describe('A UUID string identifying this external data source.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Fetch current schema/table list from the source and create any new ExternalDataSchema rows (no data sync).
 */
export const ExternalDataSourcesRefreshSchemasCreateParams = zod.object({
    id: zod.string().describe('A UUID string identifying this external data source.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const externalDataSourcesRefreshSchemasCreateBodyPrefixMax = 100

export const externalDataSourcesRefreshSchemasCreateBodyDescriptionMax = 400

export const ExternalDataSourcesRefreshSchemasCreateBody = zod
    .object({
        client_secret: zod.string(),
        account_id: zod.string(),
        prefix: zod.string().max(externalDataSourcesRefreshSchemasCreateBodyPrefixMax).nullish(),
        description: zod.string().max(externalDataSourcesRefreshSchemasCreateBodyDescriptionMax).nullish(),
        job_inputs: zod.unknown().nullish(),
    })
    .describe('Mixin for serializers to add user access control fields')

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const ExternalDataSourcesReloadCreateParams = zod.object({
    id: zod.string().describe('A UUID string identifying this external data source.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const externalDataSourcesReloadCreateBodyPrefixMax = 100

export const externalDataSourcesReloadCreateBodyDescriptionMax = 400

export const ExternalDataSourcesReloadCreateBody = zod
    .object({
        client_secret: zod.string(),
        account_id: zod.string(),
        prefix: zod.string().max(externalDataSourcesReloadCreateBodyPrefixMax).nullish(),
        description: zod.string().max(externalDataSourcesReloadCreateBodyDescriptionMax).nullish(),
        job_inputs: zod.unknown().nullish(),
    })
    .describe('Mixin for serializers to add user access control fields')

/**
 * Update the revenue analytics configuration and return the full external data source.
 */
export const ExternalDataSourcesRevenueAnalyticsConfigPartialUpdateParams = zod.object({
    id: zod.string().describe('A UUID string identifying this external data source.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const externalDataSourcesRevenueAnalyticsConfigPartialUpdateBodyPrefixMax = 100

export const externalDataSourcesRevenueAnalyticsConfigPartialUpdateBodyDescriptionMax = 400

export const ExternalDataSourcesRevenueAnalyticsConfigPartialUpdateBody = zod
    .object({
        client_secret: zod.string().optional(),
        account_id: zod.string().optional(),
        prefix: zod.string().max(externalDataSourcesRevenueAnalyticsConfigPartialUpdateBodyPrefixMax).nullish(),
        description: zod
            .string()
            .max(externalDataSourcesRevenueAnalyticsConfigPartialUpdateBodyDescriptionMax)
            .nullish(),
        job_inputs: zod.unknown().nullish(),
    })
    .describe('Mixin for serializers to add user access control fields')

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const ExternalDataSourcesDatabaseSchemaCreateParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const externalDataSourcesDatabaseSchemaCreateBodyPrefixMax = 100

export const externalDataSourcesDatabaseSchemaCreateBodyDescriptionMax = 400

export const ExternalDataSourcesDatabaseSchemaCreateBody = zod
    .object({
        client_secret: zod.string(),
        account_id: zod.string(),
        prefix: zod.string().max(externalDataSourcesDatabaseSchemaCreateBodyPrefixMax).nullish(),
        description: zod.string().max(externalDataSourcesDatabaseSchemaCreateBodyDescriptionMax).nullish(),
        job_inputs: zod.unknown().nullish(),
    })
    .describe('Mixin for serializers to add user access control fields')

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const ExternalDataSourcesSourcePrefixCreateParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const externalDataSourcesSourcePrefixCreateBodyPrefixMax = 100

export const externalDataSourcesSourcePrefixCreateBodyDescriptionMax = 400

export const ExternalDataSourcesSourcePrefixCreateBody = zod
    .object({
        client_secret: zod.string(),
        account_id: zod.string(),
        prefix: zod.string().max(externalDataSourcesSourcePrefixCreateBodyPrefixMax).nullish(),
        description: zod.string().max(externalDataSourcesSourcePrefixCreateBodyDescriptionMax).nullish(),
        job_inputs: zod.unknown().nullish(),
    })
    .describe('Mixin for serializers to add user access control fields')

/**
 * Create, Read, Update and Delete External data Sources.
 */
export const ExternalDataSourcesWizardRetrieveParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Create, Read, Update and Delete Query Tab State.
 */
export const QueryTabStateListParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const QueryTabStateListQueryParams = zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

export const QueryTabStateListResponse = zod.object({
    count: zod.number(),
    next: zod.string().url().nullish(),
    previous: zod.string().url().nullish(),
    results: zod.array(
        zod.object({
            id: zod.string(),
            state: zod
                .unknown()
                .nullish()
                .describe(
                    '\n            Dict of query tab state for a user. Keys are editorModelsStateKey, activeModelStateKey, activeModelVariablesStateKey\n            and values are the state for that key. EditorModelsStateKey is a list of all the editor models for a user.\n            ActiveModelStateKey is the active model for a user. ActiveModelVariablesStateKey is the active model variables\n            for a user.\n            '
                ),
        })
    ),
})

/**
 * Create, Read, Update and Delete Query Tab State.
 */
export const QueryTabStateCreateParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const QueryTabStateCreateBody = zod.object({
    state: zod
        .unknown()
        .nullish()
        .describe(
            '\n            Dict of query tab state for a user. Keys are editorModelsStateKey, activeModelStateKey, activeModelVariablesStateKey\n            and values are the state for that key. EditorModelsStateKey is a list of all the editor models for a user.\n            ActiveModelStateKey is the active model for a user. ActiveModelVariablesStateKey is the active model variables\n            for a user.\n            '
        ),
})

/**
 * Create, Read, Update and Delete Query Tab State.
 */
export const QueryTabStateRetrieveParams = zod.object({
    id: zod.string().describe('A UUID string identifying this query tab state.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const QueryTabStateRetrieveResponse = zod.object({
    id: zod.string(),
    state: zod
        .unknown()
        .nullish()
        .describe(
            '\n            Dict of query tab state for a user. Keys are editorModelsStateKey, activeModelStateKey, activeModelVariablesStateKey\n            and values are the state for that key. EditorModelsStateKey is a list of all the editor models for a user.\n            ActiveModelStateKey is the active model for a user. ActiveModelVariablesStateKey is the active model variables\n            for a user.\n            '
        ),
})

/**
 * Create, Read, Update and Delete Query Tab State.
 */
export const QueryTabStateUpdateParams = zod.object({
    id: zod.string().describe('A UUID string identifying this query tab state.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const QueryTabStateUpdateBody = zod.object({
    state: zod
        .unknown()
        .nullish()
        .describe(
            '\n            Dict of query tab state for a user. Keys are editorModelsStateKey, activeModelStateKey, activeModelVariablesStateKey\n            and values are the state for that key. EditorModelsStateKey is a list of all the editor models for a user.\n            ActiveModelStateKey is the active model for a user. ActiveModelVariablesStateKey is the active model variables\n            for a user.\n            '
        ),
})

export const QueryTabStateUpdateResponse = zod.object({
    id: zod.string(),
    state: zod
        .unknown()
        .nullish()
        .describe(
            '\n            Dict of query tab state for a user. Keys are editorModelsStateKey, activeModelStateKey, activeModelVariablesStateKey\n            and values are the state for that key. EditorModelsStateKey is a list of all the editor models for a user.\n            ActiveModelStateKey is the active model for a user. ActiveModelVariablesStateKey is the active model variables\n            for a user.\n            '
        ),
})

/**
 * Create, Read, Update and Delete Query Tab State.
 */
export const QueryTabStatePartialUpdateParams = zod.object({
    id: zod.string().describe('A UUID string identifying this query tab state.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const QueryTabStatePartialUpdateBody = zod.object({
    state: zod
        .unknown()
        .nullish()
        .describe(
            '\n            Dict of query tab state for a user. Keys are editorModelsStateKey, activeModelStateKey, activeModelVariablesStateKey\n            and values are the state for that key. EditorModelsStateKey is a list of all the editor models for a user.\n            ActiveModelStateKey is the active model for a user. ActiveModelVariablesStateKey is the active model variables\n            for a user.\n            '
        ),
})

export const QueryTabStatePartialUpdateResponse = zod.object({
    id: zod.string(),
    state: zod
        .unknown()
        .nullish()
        .describe(
            '\n            Dict of query tab state for a user. Keys are editorModelsStateKey, activeModelStateKey, activeModelVariablesStateKey\n            and values are the state for that key. EditorModelsStateKey is a list of all the editor models for a user.\n            ActiveModelStateKey is the active model for a user. ActiveModelVariablesStateKey is the active model variables\n            for a user.\n            '
        ),
})

/**
 * Create, Read, Update and Delete Query Tab State.
 */
export const QueryTabStateDestroyParams = zod.object({
    id: zod.string().describe('A UUID string identifying this query tab state.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Create, Read, Update and Delete Query Tab State.
 */
export const QueryTabStateUserRetrieveParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const QueryTabStateUserRetrieveResponse = zod.object({
    id: zod.string(),
    state: zod
        .unknown()
        .nullish()
        .describe(
            '\n            Dict of query tab state for a user. Keys are editorModelsStateKey, activeModelStateKey, activeModelVariablesStateKey\n            and values are the state for that key. EditorModelsStateKey is a list of all the editor models for a user.\n            ActiveModelStateKey is the active model for a user. ActiveModelVariablesStateKey is the active model variables\n            for a user.\n            '
        ),
})

/**
 * Return this team's DAG as a set of edges and nodes
 */
export const WarehouseDagRetrieveParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const WarehouseModelPathsListParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const WarehouseModelPathsListQueryParams = zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

export const warehouseModelPathsListResponseResultsItemCreatedByOneDistinctIdMax = 200

export const warehouseModelPathsListResponseResultsItemCreatedByOneFirstNameMax = 150

export const warehouseModelPathsListResponseResultsItemCreatedByOneLastNameMax = 150

export const warehouseModelPathsListResponseResultsItemCreatedByOneEmailMax = 254

export const WarehouseModelPathsListResponse = zod.object({
    count: zod.number(),
    next: zod.string().url().nullish(),
    previous: zod.string().url().nullish(),
    results: zod.array(
        zod.object({
            id: zod.string(),
            path: zod.string(),
            team: zod.number(),
            table: zod.string().nullish(),
            saved_query: zod.string().nullish(),
            created_at: zod.string().datetime({}),
            created_by: zod.object({
                id: zod.number(),
                uuid: zod.string(),
                distinct_id: zod
                    .string()
                    .max(warehouseModelPathsListResponseResultsItemCreatedByOneDistinctIdMax)
                    .nullish(),
                first_name: zod
                    .string()
                    .max(warehouseModelPathsListResponseResultsItemCreatedByOneFirstNameMax)
                    .optional(),
                last_name: zod
                    .string()
                    .max(warehouseModelPathsListResponseResultsItemCreatedByOneLastNameMax)
                    .optional(),
                email: zod.string().email().max(warehouseModelPathsListResponseResultsItemCreatedByOneEmailMax),
                is_email_verified: zod.boolean().nullish(),
                hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
                role_at_organization: zod
                    .union([
                        zod
                            .enum([
                                'engineering',
                                'data',
                                'product',
                                'founder',
                                'leadership',
                                'marketing',
                                'sales',
                                'other',
                            ])
                            .describe(
                                '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                            ),
                        zod.enum(['']),
                        zod.literal(null),
                    ])
                    .nullish(),
            }),
            updated_at: zod.string().datetime({}).nullable(),
        })
    ),
})

/**
 * Create, Read, Update and Delete Warehouse Tables.
 */
export const WarehouseSavedQueriesListParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const WarehouseSavedQueriesListQueryParams = zod.object({
    page: zod.number().optional().describe('A page number within the paginated result set.'),
    search: zod.string().optional().describe('A search term.'),
})

export const warehouseSavedQueriesListResponseResultsItemCreatedByOneDistinctIdMax = 200

export const warehouseSavedQueriesListResponseResultsItemCreatedByOneFirstNameMax = 150

export const warehouseSavedQueriesListResponseResultsItemCreatedByOneLastNameMax = 150

export const warehouseSavedQueriesListResponseResultsItemCreatedByOneEmailMax = 254

export const WarehouseSavedQueriesListResponse = zod.object({
    count: zod.number(),
    next: zod.string().url().nullish(),
    previous: zod.string().url().nullish(),
    results: zod.array(
        zod
            .object({
                id: zod.string(),
                deleted: zod.boolean().nullable(),
                name: zod.string(),
                created_by: zod.object({
                    id: zod.number(),
                    uuid: zod.string(),
                    distinct_id: zod
                        .string()
                        .max(warehouseSavedQueriesListResponseResultsItemCreatedByOneDistinctIdMax)
                        .nullish(),
                    first_name: zod
                        .string()
                        .max(warehouseSavedQueriesListResponseResultsItemCreatedByOneFirstNameMax)
                        .optional(),
                    last_name: zod
                        .string()
                        .max(warehouseSavedQueriesListResponseResultsItemCreatedByOneLastNameMax)
                        .optional(),
                    email: zod.string().email().max(warehouseSavedQueriesListResponseResultsItemCreatedByOneEmailMax),
                    is_email_verified: zod.boolean().nullish(),
                    hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
                    role_at_organization: zod
                        .union([
                            zod
                                .enum([
                                    'engineering',
                                    'data',
                                    'product',
                                    'founder',
                                    'leadership',
                                    'marketing',
                                    'sales',
                                    'other',
                                ])
                                .describe(
                                    '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                                ),
                            zod.enum(['']),
                            zod.literal(null),
                        ])
                        .nullish(),
                }),
                created_at: zod.string().datetime({}),
                sync_frequency: zod.string(),
                columns: zod.string(),
                status: zod
                    .union([
                        zod
                            .enum(['Cancelled', 'Modified', 'Completed', 'Failed', 'Running'])
                            .describe(
                                '* `Cancelled` - Cancelled\n* `Modified` - Modified\n* `Completed` - Completed\n* `Failed` - Failed\n* `Running` - Running'
                            ),
                        zod.literal(null),
                    ])
                    .nullable()
                    .describe(
                        'The status of when this SavedQuery last ran.\n\n* `Cancelled` - Cancelled\n* `Modified` - Modified\n* `Completed` - Completed\n* `Failed` - Failed\n* `Running` - Running'
                    ),
                last_run_at: zod.string().datetime({}).nullable(),
                managed_viewset_kind: zod.string(),
                latest_error: zod.string().nullable(),
                is_materialized: zod.boolean().nullable(),
                origin: zod
                    .union([
                        zod
                            .enum(['data_warehouse', 'endpoint', 'managed_viewset'])
                            .describe(
                                '* `data_warehouse` - Data Warehouse\n* `endpoint` - Endpoint\n* `managed_viewset` - Managed Viewset'
                            ),
                        zod.literal(null),
                    ])
                    .nullable()
                    .describe(
                        'Where this SavedQuery is created.\n\n* `data_warehouse` - Data Warehouse\n* `endpoint` - Endpoint\n* `managed_viewset` - Managed Viewset'
                    ),
            })
            .describe('Lightweight serializer for list views - excludes large query field to reduce memory usage.')
    ),
})

/**
 * Create, Read, Update and Delete Warehouse Tables.
 */
export const WarehouseSavedQueriesCreateParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const warehouseSavedQueriesCreateBodyNameMax = 128

export const WarehouseSavedQueriesCreateBody = zod
    .object({
        name: zod
            .string()
            .max(warehouseSavedQueriesCreateBodyNameMax)
            .describe('Unique name for the view. Used as the table name in HogQL queries.'),
        query: zod
            .unknown()
            .nullish()
            .describe(
                'HogQL query definition as a JSON object with a "query" key containing the SQL string. Example: {"query": "SELECT * FROM events LIMIT 100"}'
            ),
    })
    .describe(
        'Shared methods for DataWarehouseSavedQuery serializers.\n\nThis mixin is intended to be used with serializers.ModelSerializer subclasses.'
    )

/**
 * Create, Read, Update and Delete Warehouse Tables.
 */
export const WarehouseSavedQueriesRetrieveParams = zod.object({
    id: zod.string().describe('A UUID string identifying this data warehouse saved query.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const warehouseSavedQueriesRetrieveResponseNameMax = 128

export const WarehouseSavedQueriesRetrieveResponse = zod
    .object({
        id: zod.string(),
        name: zod
            .string()
            .max(warehouseSavedQueriesRetrieveResponseNameMax)
            .describe('Unique name for the view. Used as the table name in HogQL queries.'),
        query: zod
            .unknown()
            .nullish()
            .describe(
                'HogQL query definition as a JSON object with a "query" key containing the SQL string. Example: {"query": "SELECT * FROM events LIMIT 100"}'
            ),
        sync_frequency: zod.string(),
    })
    .describe(
        'Shared methods for DataWarehouseSavedQuery serializers.\n\nThis mixin is intended to be used with serializers.ModelSerializer subclasses.'
    )

/**
 * Create, Read, Update and Delete Warehouse Tables.
 */
export const WarehouseSavedQueriesUpdateParams = zod.object({
    id: zod.string().describe('A UUID string identifying this data warehouse saved query.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const warehouseSavedQueriesUpdateBodyNameMax = 128

export const WarehouseSavedQueriesUpdateBody = zod
    .object({
        name: zod
            .string()
            .max(warehouseSavedQueriesUpdateBodyNameMax)
            .describe('Unique name for the view. Used as the table name in HogQL queries.'),
        query: zod
            .unknown()
            .nullish()
            .describe(
                'HogQL query definition as a JSON object with a "query" key containing the SQL string. Example: {"query": "SELECT * FROM events LIMIT 100"}'
            ),
    })
    .describe(
        'Shared methods for DataWarehouseSavedQuery serializers.\n\nThis mixin is intended to be used with serializers.ModelSerializer subclasses.'
    )

export const warehouseSavedQueriesUpdateResponseNameMax = 128

export const WarehouseSavedQueriesUpdateResponse = zod
    .object({
        id: zod.string(),
        name: zod
            .string()
            .max(warehouseSavedQueriesUpdateResponseNameMax)
            .describe('Unique name for the view. Used as the table name in HogQL queries.'),
        query: zod
            .unknown()
            .nullish()
            .describe(
                'HogQL query definition as a JSON object with a "query" key containing the SQL string. Example: {"query": "SELECT * FROM events LIMIT 100"}'
            ),
        sync_frequency: zod.string(),
    })
    .describe(
        'Shared methods for DataWarehouseSavedQuery serializers.\n\nThis mixin is intended to be used with serializers.ModelSerializer subclasses.'
    )

/**
 * Create, Read, Update and Delete Warehouse Tables.
 */
export const WarehouseSavedQueriesPartialUpdateParams = zod.object({
    id: zod.string().describe('A UUID string identifying this data warehouse saved query.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const warehouseSavedQueriesPartialUpdateBodyNameMax = 128

export const WarehouseSavedQueriesPartialUpdateBody = zod
    .object({
        name: zod
            .string()
            .max(warehouseSavedQueriesPartialUpdateBodyNameMax)
            .optional()
            .describe('Unique name for the view. Used as the table name in HogQL queries.'),
        query: zod
            .unknown()
            .nullish()
            .describe(
                'HogQL query definition as a JSON object with a "query" key containing the SQL string. Example: {"query": "SELECT * FROM events LIMIT 100"}'
            ),
        edited_history_id: zod
            .string()
            .nullish()
            .describe('Activity log ID from the last known edit. Used for conflict detection.'),
    })
    .describe(
        'Shared methods for DataWarehouseSavedQuery serializers.\n\nThis mixin is intended to be used with serializers.ModelSerializer subclasses.'
    )

export const warehouseSavedQueriesPartialUpdateResponseNameMax = 128

export const WarehouseSavedQueriesPartialUpdateResponse = zod
    .object({
        id: zod.string(),
        name: zod
            .string()
            .max(warehouseSavedQueriesPartialUpdateResponseNameMax)
            .describe('Unique name for the view. Used as the table name in HogQL queries.'),
        query: zod
            .unknown()
            .nullish()
            .describe(
                'HogQL query definition as a JSON object with a "query" key containing the SQL string. Example: {"query": "SELECT * FROM events LIMIT 100"}'
            ),
        sync_frequency: zod.string(),
    })
    .describe(
        'Shared methods for DataWarehouseSavedQuery serializers.\n\nThis mixin is intended to be used with serializers.ModelSerializer subclasses.'
    )

/**
 * Create, Read, Update and Delete Warehouse Tables.
 */
export const WarehouseSavedQueriesDestroyParams = zod.object({
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
export const WarehouseSavedQueriesActivityRetrieveParams = zod.object({
    id: zod.string().describe('A UUID string identifying this data warehouse saved query.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const warehouseSavedQueriesActivityRetrieveResponseNameMax = 128

export const WarehouseSavedQueriesActivityRetrieveResponse = zod
    .object({
        id: zod.string(),
        name: zod
            .string()
            .max(warehouseSavedQueriesActivityRetrieveResponseNameMax)
            .describe('Unique name for the view. Used as the table name in HogQL queries.'),
        query: zod
            .unknown()
            .nullish()
            .describe(
                'HogQL query definition as a JSON object with a "query" key containing the SQL string. Example: {"query": "SELECT * FROM events LIMIT 100"}'
            ),
        sync_frequency: zod.string(),
    })
    .describe(
        'Shared methods for DataWarehouseSavedQuery serializers.\n\nThis mixin is intended to be used with serializers.ModelSerializer subclasses.'
    )

/**
 * Return the ancestors of this saved query.

By default, we return the immediate parents. The `level` parameter can be used to
look further back into the ancestor tree. If `level` overshoots (i.e. points to only
ancestors beyond the root), we return an empty list.
 */
export const WarehouseSavedQueriesAncestorsCreateParams = zod.object({
    id: zod.string().describe('A UUID string identifying this data warehouse saved query.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const warehouseSavedQueriesAncestorsCreateBodyNameMax = 128

export const WarehouseSavedQueriesAncestorsCreateBody = zod
    .object({
        name: zod
            .string()
            .max(warehouseSavedQueriesAncestorsCreateBodyNameMax)
            .describe('Unique name for the view. Used as the table name in HogQL queries.'),
        query: zod
            .unknown()
            .nullish()
            .describe(
                'HogQL query definition as a JSON object with a "query" key containing the SQL string. Example: {"query": "SELECT * FROM events LIMIT 100"}'
            ),
    })
    .describe(
        'Shared methods for DataWarehouseSavedQuery serializers.\n\nThis mixin is intended to be used with serializers.ModelSerializer subclasses.'
    )

export const warehouseSavedQueriesAncestorsCreateResponseNameMax = 128

export const WarehouseSavedQueriesAncestorsCreateResponse = zod
    .object({
        id: zod.string(),
        name: zod
            .string()
            .max(warehouseSavedQueriesAncestorsCreateResponseNameMax)
            .describe('Unique name for the view. Used as the table name in HogQL queries.'),
        query: zod
            .unknown()
            .nullish()
            .describe(
                'HogQL query definition as a JSON object with a "query" key containing the SQL string. Example: {"query": "SELECT * FROM events LIMIT 100"}'
            ),
        sync_frequency: zod.string(),
    })
    .describe(
        'Shared methods for DataWarehouseSavedQuery serializers.\n\nThis mixin is intended to be used with serializers.ModelSerializer subclasses.'
    )

/**
 * Cancel a running saved query workflow.
 */
export const WarehouseSavedQueriesCancelCreateParams = zod.object({
    id: zod.string().describe('A UUID string identifying this data warehouse saved query.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const warehouseSavedQueriesCancelCreateBodyNameMax = 128

export const WarehouseSavedQueriesCancelCreateBody = zod
    .object({
        name: zod
            .string()
            .max(warehouseSavedQueriesCancelCreateBodyNameMax)
            .describe('Unique name for the view. Used as the table name in HogQL queries.'),
        query: zod
            .unknown()
            .nullish()
            .describe(
                'HogQL query definition as a JSON object with a "query" key containing the SQL string. Example: {"query": "SELECT * FROM events LIMIT 100"}'
            ),
    })
    .describe(
        'Shared methods for DataWarehouseSavedQuery serializers.\n\nThis mixin is intended to be used with serializers.ModelSerializer subclasses.'
    )

export const warehouseSavedQueriesCancelCreateResponseNameMax = 128

export const WarehouseSavedQueriesCancelCreateResponse = zod
    .object({
        id: zod.string(),
        name: zod
            .string()
            .max(warehouseSavedQueriesCancelCreateResponseNameMax)
            .describe('Unique name for the view. Used as the table name in HogQL queries.'),
        query: zod
            .unknown()
            .nullish()
            .describe(
                'HogQL query definition as a JSON object with a "query" key containing the SQL string. Example: {"query": "SELECT * FROM events LIMIT 100"}'
            ),
        sync_frequency: zod.string(),
    })
    .describe(
        'Shared methods for DataWarehouseSavedQuery serializers.\n\nThis mixin is intended to be used with serializers.ModelSerializer subclasses.'
    )

/**
 * Return the count of immediate upstream and downstream dependencies for this saved query.
 */
export const WarehouseSavedQueriesDependenciesRetrieveParams = zod.object({
    id: zod.string().describe('A UUID string identifying this data warehouse saved query.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const warehouseSavedQueriesDependenciesRetrieveResponseNameMax = 128

export const WarehouseSavedQueriesDependenciesRetrieveResponse = zod
    .object({
        id: zod.string(),
        name: zod
            .string()
            .max(warehouseSavedQueriesDependenciesRetrieveResponseNameMax)
            .describe('Unique name for the view. Used as the table name in HogQL queries.'),
        query: zod
            .unknown()
            .nullish()
            .describe(
                'HogQL query definition as a JSON object with a "query" key containing the SQL string. Example: {"query": "SELECT * FROM events LIMIT 100"}'
            ),
        sync_frequency: zod.string(),
    })
    .describe(
        'Shared methods for DataWarehouseSavedQuery serializers.\n\nThis mixin is intended to be used with serializers.ModelSerializer subclasses.'
    )

/**
 * Return the descendants of this saved query.

By default, we return the immediate children. The `level` parameter can be used to
look further ahead into the descendants tree. If `level` overshoots (i.e. points to only
descendants further than a leaf), we return an empty list.
 */
export const WarehouseSavedQueriesDescendantsCreateParams = zod.object({
    id: zod.string().describe('A UUID string identifying this data warehouse saved query.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const warehouseSavedQueriesDescendantsCreateBodyNameMax = 128

export const WarehouseSavedQueriesDescendantsCreateBody = zod
    .object({
        name: zod
            .string()
            .max(warehouseSavedQueriesDescendantsCreateBodyNameMax)
            .describe('Unique name for the view. Used as the table name in HogQL queries.'),
        query: zod
            .unknown()
            .nullish()
            .describe(
                'HogQL query definition as a JSON object with a "query" key containing the SQL string. Example: {"query": "SELECT * FROM events LIMIT 100"}'
            ),
    })
    .describe(
        'Shared methods for DataWarehouseSavedQuery serializers.\n\nThis mixin is intended to be used with serializers.ModelSerializer subclasses.'
    )

export const warehouseSavedQueriesDescendantsCreateResponseNameMax = 128

export const WarehouseSavedQueriesDescendantsCreateResponse = zod
    .object({
        id: zod.string(),
        name: zod
            .string()
            .max(warehouseSavedQueriesDescendantsCreateResponseNameMax)
            .describe('Unique name for the view. Used as the table name in HogQL queries.'),
        query: zod
            .unknown()
            .nullish()
            .describe(
                'HogQL query definition as a JSON object with a "query" key containing the SQL string. Example: {"query": "SELECT * FROM events LIMIT 100"}'
            ),
        sync_frequency: zod.string(),
    })
    .describe(
        'Shared methods for DataWarehouseSavedQuery serializers.\n\nThis mixin is intended to be used with serializers.ModelSerializer subclasses.'
    )

/**
 * Enable materialization for this saved query with a 24-hour sync frequency.
 */
export const WarehouseSavedQueriesMaterializeCreateParams = zod.object({
    id: zod.string().describe('A UUID string identifying this data warehouse saved query.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const warehouseSavedQueriesMaterializeCreateBodyNameMax = 128

export const WarehouseSavedQueriesMaterializeCreateBody = zod
    .object({
        name: zod
            .string()
            .max(warehouseSavedQueriesMaterializeCreateBodyNameMax)
            .describe('Unique name for the view. Used as the table name in HogQL queries.'),
        query: zod
            .unknown()
            .nullish()
            .describe(
                'HogQL query definition as a JSON object with a "query" key containing the SQL string. Example: {"query": "SELECT * FROM events LIMIT 100"}'
            ),
    })
    .describe(
        'Shared methods for DataWarehouseSavedQuery serializers.\n\nThis mixin is intended to be used with serializers.ModelSerializer subclasses.'
    )

export const warehouseSavedQueriesMaterializeCreateResponseNameMax = 128

export const WarehouseSavedQueriesMaterializeCreateResponse = zod
    .object({
        id: zod.string(),
        name: zod
            .string()
            .max(warehouseSavedQueriesMaterializeCreateResponseNameMax)
            .describe('Unique name for the view. Used as the table name in HogQL queries.'),
        query: zod
            .unknown()
            .nullish()
            .describe(
                'HogQL query definition as a JSON object with a "query" key containing the SQL string. Example: {"query": "SELECT * FROM events LIMIT 100"}'
            ),
        sync_frequency: zod.string(),
    })
    .describe(
        'Shared methods for DataWarehouseSavedQuery serializers.\n\nThis mixin is intended to be used with serializers.ModelSerializer subclasses.'
    )

/**
 * Undo materialization, revert back to the original view.
(i.e. delete the materialized table and the schedule)
 */
export const WarehouseSavedQueriesRevertMaterializationCreateParams = zod.object({
    id: zod.string().describe('A UUID string identifying this data warehouse saved query.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const warehouseSavedQueriesRevertMaterializationCreateBodyNameMax = 128

export const WarehouseSavedQueriesRevertMaterializationCreateBody = zod
    .object({
        name: zod
            .string()
            .max(warehouseSavedQueriesRevertMaterializationCreateBodyNameMax)
            .describe('Unique name for the view. Used as the table name in HogQL queries.'),
        query: zod
            .unknown()
            .nullish()
            .describe(
                'HogQL query definition as a JSON object with a "query" key containing the SQL string. Example: {"query": "SELECT * FROM events LIMIT 100"}'
            ),
    })
    .describe(
        'Shared methods for DataWarehouseSavedQuery serializers.\n\nThis mixin is intended to be used with serializers.ModelSerializer subclasses.'
    )

export const warehouseSavedQueriesRevertMaterializationCreateResponseNameMax = 128

export const WarehouseSavedQueriesRevertMaterializationCreateResponse = zod
    .object({
        id: zod.string(),
        name: zod
            .string()
            .max(warehouseSavedQueriesRevertMaterializationCreateResponseNameMax)
            .describe('Unique name for the view. Used as the table name in HogQL queries.'),
        query: zod
            .unknown()
            .nullish()
            .describe(
                'HogQL query definition as a JSON object with a "query" key containing the SQL string. Example: {"query": "SELECT * FROM events LIMIT 100"}'
            ),
        sync_frequency: zod.string(),
    })
    .describe(
        'Shared methods for DataWarehouseSavedQuery serializers.\n\nThis mixin is intended to be used with serializers.ModelSerializer subclasses.'
    )

/**
 * Run this saved query.
 */
export const WarehouseSavedQueriesRunCreateParams = zod.object({
    id: zod.string().describe('A UUID string identifying this data warehouse saved query.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const warehouseSavedQueriesRunCreateBodyNameMax = 128

export const WarehouseSavedQueriesRunCreateBody = zod
    .object({
        name: zod
            .string()
            .max(warehouseSavedQueriesRunCreateBodyNameMax)
            .describe('Unique name for the view. Used as the table name in HogQL queries.'),
        query: zod
            .unknown()
            .nullish()
            .describe(
                'HogQL query definition as a JSON object with a "query" key containing the SQL string. Example: {"query": "SELECT * FROM events LIMIT 100"}'
            ),
    })
    .describe(
        'Shared methods for DataWarehouseSavedQuery serializers.\n\nThis mixin is intended to be used with serializers.ModelSerializer subclasses.'
    )

export const warehouseSavedQueriesRunCreateResponseNameMax = 128

export const WarehouseSavedQueriesRunCreateResponse = zod
    .object({
        id: zod.string(),
        name: zod
            .string()
            .max(warehouseSavedQueriesRunCreateResponseNameMax)
            .describe('Unique name for the view. Used as the table name in HogQL queries.'),
        query: zod
            .unknown()
            .nullish()
            .describe(
                'HogQL query definition as a JSON object with a "query" key containing the SQL string. Example: {"query": "SELECT * FROM events LIMIT 100"}'
            ),
        sync_frequency: zod.string(),
    })
    .describe(
        'Shared methods for DataWarehouseSavedQuery serializers.\n\nThis mixin is intended to be used with serializers.ModelSerializer subclasses.'
    )

/**
 * Return the recent run history (up to 5 most recent) for this materialized view.
 */
export const WarehouseSavedQueriesRunHistoryRetrieveParams = zod.object({
    id: zod.string().describe('A UUID string identifying this data warehouse saved query.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const warehouseSavedQueriesRunHistoryRetrieveResponseNameMax = 128

export const WarehouseSavedQueriesRunHistoryRetrieveResponse = zod
    .object({
        id: zod.string(),
        name: zod
            .string()
            .max(warehouseSavedQueriesRunHistoryRetrieveResponseNameMax)
            .describe('Unique name for the view. Used as the table name in HogQL queries.'),
        query: zod
            .unknown()
            .nullish()
            .describe(
                'HogQL query definition as a JSON object with a "query" key containing the SQL string. Example: {"query": "SELECT * FROM events LIMIT 100"}'
            ),
        sync_frequency: zod.string(),
    })
    .describe(
        'Shared methods for DataWarehouseSavedQuery serializers.\n\nThis mixin is intended to be used with serializers.ModelSerializer subclasses.'
    )

/**
 * Resume paused materialization schedules for multiple matviews.

Accepts a list of view IDs in the request body: {"view_ids": ["id1", "id2", ...]}
This endpoint is idempotent - calling it on already running or non-existent schedules is safe.
 */
export const WarehouseSavedQueriesResumeSchedulesCreateParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const warehouseSavedQueriesResumeSchedulesCreateBodyNameMax = 128

export const WarehouseSavedQueriesResumeSchedulesCreateBody = zod
    .object({
        name: zod
            .string()
            .max(warehouseSavedQueriesResumeSchedulesCreateBodyNameMax)
            .describe('Unique name for the view. Used as the table name in HogQL queries.'),
        query: zod
            .unknown()
            .nullish()
            .describe(
                'HogQL query definition as a JSON object with a "query" key containing the SQL string. Example: {"query": "SELECT * FROM events LIMIT 100"}'
            ),
    })
    .describe(
        'Shared methods for DataWarehouseSavedQuery serializers.\n\nThis mixin is intended to be used with serializers.ModelSerializer subclasses.'
    )

export const warehouseSavedQueriesResumeSchedulesCreateResponseNameMax = 128

export const WarehouseSavedQueriesResumeSchedulesCreateResponse = zod
    .object({
        id: zod.string(),
        name: zod
            .string()
            .max(warehouseSavedQueriesResumeSchedulesCreateResponseNameMax)
            .describe('Unique name for the view. Used as the table name in HogQL queries.'),
        query: zod
            .unknown()
            .nullish()
            .describe(
                'HogQL query definition as a JSON object with a "query" key containing the SQL string. Example: {"query": "SELECT * FROM events LIMIT 100"}'
            ),
        sync_frequency: zod.string(),
    })
    .describe(
        'Shared methods for DataWarehouseSavedQuery serializers.\n\nThis mixin is intended to be used with serializers.ModelSerializer subclasses.'
    )

/**
 * Create, Read, Update and Delete Warehouse Tables.
 */
export const WarehouseTablesListParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const WarehouseTablesListQueryParams = zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
    search: zod.string().optional().describe('A search term.'),
})

export const warehouseTablesListResponseResultsItemNameMax = 128

export const warehouseTablesListResponseResultsItemCreatedByOneDistinctIdMax = 200

export const warehouseTablesListResponseResultsItemCreatedByOneFirstNameMax = 150

export const warehouseTablesListResponseResultsItemCreatedByOneLastNameMax = 150

export const warehouseTablesListResponseResultsItemCreatedByOneEmailMax = 254

export const warehouseTablesListResponseResultsItemUrlPatternMax = 500

export const warehouseTablesListResponseResultsItemCredentialCreatedByOneDistinctIdMax = 200

export const warehouseTablesListResponseResultsItemCredentialCreatedByOneFirstNameMax = 150

export const warehouseTablesListResponseResultsItemCredentialCreatedByOneLastNameMax = 150

export const warehouseTablesListResponseResultsItemCredentialCreatedByOneEmailMax = 254

export const warehouseTablesListResponseResultsItemCredentialAccessKeyMax = 500

export const warehouseTablesListResponseResultsItemCredentialAccessSecretMax = 500

export const WarehouseTablesListResponse = zod.object({
    count: zod.number(),
    next: zod.string().url().nullish(),
    previous: zod.string().url().nullish(),
    results: zod.array(
        zod.object({
            id: zod.string(),
            deleted: zod.boolean().nullish(),
            name: zod.string().max(warehouseTablesListResponseResultsItemNameMax),
            format: zod
                .enum(['CSV', 'CSVWithNames', 'Parquet', 'JSONEachRow', 'Delta', 'DeltaS3Wrapper'])
                .describe(
                    '* `CSV` - CSV\n* `CSVWithNames` - CSVWithNames\n* `Parquet` - Parquet\n* `JSONEachRow` - JSON\n* `Delta` - Delta\n* `DeltaS3Wrapper` - DeltaS3Wrapper'
                ),
            created_by: zod.object({
                id: zod.number(),
                uuid: zod.string(),
                distinct_id: zod
                    .string()
                    .max(warehouseTablesListResponseResultsItemCreatedByOneDistinctIdMax)
                    .nullish(),
                first_name: zod.string().max(warehouseTablesListResponseResultsItemCreatedByOneFirstNameMax).optional(),
                last_name: zod.string().max(warehouseTablesListResponseResultsItemCreatedByOneLastNameMax).optional(),
                email: zod.string().email().max(warehouseTablesListResponseResultsItemCreatedByOneEmailMax),
                is_email_verified: zod.boolean().nullish(),
                hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
                role_at_organization: zod
                    .union([
                        zod
                            .enum([
                                'engineering',
                                'data',
                                'product',
                                'founder',
                                'leadership',
                                'marketing',
                                'sales',
                                'other',
                            ])
                            .describe(
                                '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                            ),
                        zod.enum(['']),
                        zod.literal(null),
                    ])
                    .nullish(),
            }),
            created_at: zod.string().datetime({}),
            url_pattern: zod.string().max(warehouseTablesListResponseResultsItemUrlPatternMax),
            credential: zod.object({
                id: zod.string(),
                created_by: zod.object({
                    id: zod.number(),
                    uuid: zod.string(),
                    distinct_id: zod
                        .string()
                        .max(warehouseTablesListResponseResultsItemCredentialCreatedByOneDistinctIdMax)
                        .nullish(),
                    first_name: zod
                        .string()
                        .max(warehouseTablesListResponseResultsItemCredentialCreatedByOneFirstNameMax)
                        .optional(),
                    last_name: zod
                        .string()
                        .max(warehouseTablesListResponseResultsItemCredentialCreatedByOneLastNameMax)
                        .optional(),
                    email: zod
                        .string()
                        .email()
                        .max(warehouseTablesListResponseResultsItemCredentialCreatedByOneEmailMax),
                    is_email_verified: zod.boolean().nullish(),
                    hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
                    role_at_organization: zod
                        .union([
                            zod
                                .enum([
                                    'engineering',
                                    'data',
                                    'product',
                                    'founder',
                                    'leadership',
                                    'marketing',
                                    'sales',
                                    'other',
                                ])
                                .describe(
                                    '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                                ),
                            zod.enum(['']),
                            zod.literal(null),
                        ])
                        .nullish(),
                }),
                created_at: zod.string().datetime({}),
                access_key: zod.string().max(warehouseTablesListResponseResultsItemCredentialAccessKeyMax),
                access_secret: zod.string().max(warehouseTablesListResponseResultsItemCredentialAccessSecretMax),
            }),
            columns: zod.string(),
            external_data_source: zod.object({
                id: zod.string(),
                created_at: zod.string().datetime({}),
                created_by: zod.number().nullable(),
                status: zod.string(),
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
                    ])
                    .describe(
                        '* `Ashby` - Ashby\n* `Supabase` - Supabase\n* `CustomerIO` - CustomerIO\n* `Github` - Github\n* `Stripe` - Stripe\n* `Hubspot` - Hubspot\n* `Postgres` - Postgres\n* `Zendesk` - Zendesk\n* `Snowflake` - Snowflake\n* `Salesforce` - Salesforce\n* `MySQL` - MySQL\n* `MongoDB` - MongoDB\n* `MSSQL` - MSSQL\n* `Vitally` - Vitally\n* `BigQuery` - BigQuery\n* `Chargebee` - Chargebee\n* `Clerk` - Clerk\n* `GoogleAds` - GoogleAds\n* `TemporalIO` - TemporalIO\n* `DoIt` - DoIt\n* `GoogleSheets` - GoogleSheets\n* `MetaAds` - MetaAds\n* `Klaviyo` - Klaviyo\n* `Mailchimp` - Mailchimp\n* `Braze` - Braze\n* `Mailjet` - Mailjet\n* `Redshift` - Redshift\n* `Polar` - Polar\n* `RevenueCat` - RevenueCat\n* `LinkedinAds` - LinkedinAds\n* `RedditAds` - RedditAds\n* `TikTokAds` - TikTokAds\n* `BingAds` - BingAds\n* `Shopify` - Shopify\n* `Attio` - Attio\n* `SnapchatAds` - SnapchatAds\n* `Linear` - Linear\n* `Intercom` - Intercom\n* `Amplitude` - Amplitude\n* `Mixpanel` - Mixpanel\n* `Jira` - Jira\n* `ActiveCampaign` - ActiveCampaign\n* `Marketo` - Marketo\n* `Adjust` - Adjust\n* `AppsFlyer` - AppsFlyer\n* `Freshdesk` - Freshdesk\n* `GoogleAnalytics` - GoogleAnalytics\n* `Pipedrive` - Pipedrive\n* `SendGrid` - SendGrid\n* `Slack` - Slack\n* `PagerDuty` - PagerDuty\n* `Asana` - Asana\n* `Notion` - Notion\n* `Airtable` - Airtable\n* `Greenhouse` - Greenhouse\n* `BambooHR` - BambooHR\n* `Lever` - Lever\n* `GitLab` - GitLab\n* `Datadog` - Datadog\n* `Sentry` - Sentry\n* `Pendo` - Pendo\n* `FullStory` - FullStory\n* `AmazonAds` - AmazonAds\n* `PinterestAds` - PinterestAds\n* `AppleSearchAds` - AppleSearchAds\n* `QuickBooks` - QuickBooks\n* `Xero` - Xero\n* `NetSuite` - NetSuite\n* `WooCommerce` - WooCommerce\n* `BigCommerce` - BigCommerce\n* `PayPal` - PayPal\n* `Square` - Square\n* `Zoom` - Zoom\n* `Trello` - Trello\n* `Monday` - Monday\n* `ClickUp` - ClickUp\n* `Confluence` - Confluence\n* `Recurly` - Recurly\n* `SalesLoft` - SalesLoft\n* `Outreach` - Outreach\n* `Gong` - Gong\n* `Calendly` - Calendly\n* `Typeform` - Typeform\n* `Iterable` - Iterable\n* `ZohoCRM` - ZohoCRM\n* `Close` - Close\n* `Oracle` - Oracle\n* `DynamoDB` - DynamoDB\n* `Elasticsearch` - Elasticsearch\n* `Kafka` - Kafka\n* `LaunchDarkly` - LaunchDarkly\n* `Braintree` - Braintree\n* `Recharge` - Recharge\n* `HelpScout` - HelpScout\n* `Gorgias` - Gorgias\n* `Instagram` - Instagram\n* `YouTubeAnalytics` - YouTubeAnalytics\n* `FacebookPages` - FacebookPages\n* `TwitterAds` - TwitterAds\n* `Workday` - Workday\n* `ServiceNow` - ServiceNow\n* `Pardot` - Pardot\n* `Copper` - Copper\n* `Front` - Front\n* `ChartMogul` - ChartMogul\n* `Zuora` - Zuora\n* `Paddle` - Paddle\n* `CircleCI` - CircleCI\n* `CockroachDB` - CockroachDB\n* `Firebase` - Firebase\n* `AzureBlob` - AzureBlob\n* `GoogleDrive` - GoogleDrive\n* `OneDrive` - OneDrive\n* `SharePoint` - SharePoint\n* `Box` - Box\n* `SFTP` - SFTP\n* `MicrosoftTeams` - MicrosoftTeams\n* `Aircall` - Aircall\n* `Webflow` - Webflow\n* `Okta` - Okta\n* `Auth0` - Auth0\n* `Productboard` - Productboard\n* `Smartsheet` - Smartsheet\n* `Wrike` - Wrike\n* `Plaid` - Plaid\n* `SurveyMonkey` - SurveyMonkey\n* `Eventbrite` - Eventbrite\n* `RingCentral` - RingCentral\n* `Twilio` - Twilio\n* `Freshsales` - Freshsales\n* `Shortcut` - Shortcut\n* `ConvertKit` - ConvertKit\n* `Drip` - Drip\n* `CampaignMonitor` - CampaignMonitor\n* `MailerLite` - MailerLite\n* `Omnisend` - Omnisend\n* `Brevo` - Brevo\n* `Postmark` - Postmark\n* `Granola` - Granola\n* `BuildBetter` - BuildBetter'
                    ),
            }),
            external_schema: zod.string(),
            options: zod.record(zod.string(), zod.unknown()).optional(),
        })
    ),
})

/**
 * Create, Read, Update and Delete Warehouse Tables.
 */
export const WarehouseTablesCreateParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const warehouseTablesCreateBodyNameMax = 128

export const warehouseTablesCreateBodyUrlPatternMax = 500

export const warehouseTablesCreateBodyCredentialCreatedByOneDistinctIdMax = 200

export const warehouseTablesCreateBodyCredentialCreatedByOneFirstNameMax = 150

export const warehouseTablesCreateBodyCredentialCreatedByOneLastNameMax = 150

export const warehouseTablesCreateBodyCredentialCreatedByOneEmailMax = 254

export const warehouseTablesCreateBodyCredentialAccessKeyMax = 500

export const warehouseTablesCreateBodyCredentialAccessSecretMax = 500

export const WarehouseTablesCreateBody = zod.object({
    deleted: zod.boolean().nullish(),
    name: zod.string().max(warehouseTablesCreateBodyNameMax),
    format: zod
        .enum(['CSV', 'CSVWithNames', 'Parquet', 'JSONEachRow', 'Delta', 'DeltaS3Wrapper'])
        .describe(
            '* `CSV` - CSV\n* `CSVWithNames` - CSVWithNames\n* `Parquet` - Parquet\n* `JSONEachRow` - JSON\n* `Delta` - Delta\n* `DeltaS3Wrapper` - DeltaS3Wrapper'
        ),
    url_pattern: zod.string().max(warehouseTablesCreateBodyUrlPatternMax),
    credential: zod.object({
        id: zod.string(),
        created_by: zod.object({
            id: zod.number(),
            uuid: zod.string(),
            distinct_id: zod.string().max(warehouseTablesCreateBodyCredentialCreatedByOneDistinctIdMax).nullish(),
            first_name: zod.string().max(warehouseTablesCreateBodyCredentialCreatedByOneFirstNameMax).optional(),
            last_name: zod.string().max(warehouseTablesCreateBodyCredentialCreatedByOneLastNameMax).optional(),
            email: zod.string().email().max(warehouseTablesCreateBodyCredentialCreatedByOneEmailMax),
            is_email_verified: zod.boolean().nullish(),
            hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
            role_at_organization: zod
                .union([
                    zod
                        .enum([
                            'engineering',
                            'data',
                            'product',
                            'founder',
                            'leadership',
                            'marketing',
                            'sales',
                            'other',
                        ])
                        .describe(
                            '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                        ),
                    zod.enum(['']),
                    zod.literal(null),
                ])
                .nullish(),
        }),
        created_at: zod.string().datetime({}),
        access_key: zod.string().max(warehouseTablesCreateBodyCredentialAccessKeyMax),
        access_secret: zod.string().max(warehouseTablesCreateBodyCredentialAccessSecretMax),
    }),
    options: zod.record(zod.string(), zod.unknown()).optional(),
})

/**
 * Create, Read, Update and Delete Warehouse Tables.
 */
export const WarehouseTablesFileCreateParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const warehouseTablesFileCreateBodyNameMax = 128

export const warehouseTablesFileCreateBodyUrlPatternMax = 500

export const warehouseTablesFileCreateBodyCredentialCreatedByOneDistinctIdMax = 200

export const warehouseTablesFileCreateBodyCredentialCreatedByOneFirstNameMax = 150

export const warehouseTablesFileCreateBodyCredentialCreatedByOneLastNameMax = 150

export const warehouseTablesFileCreateBodyCredentialCreatedByOneEmailMax = 254

export const warehouseTablesFileCreateBodyCredentialAccessKeyMax = 500

export const warehouseTablesFileCreateBodyCredentialAccessSecretMax = 500

export const WarehouseTablesFileCreateBody = zod.object({
    deleted: zod.boolean().nullish(),
    name: zod.string().max(warehouseTablesFileCreateBodyNameMax),
    format: zod
        .enum(['CSV', 'CSVWithNames', 'Parquet', 'JSONEachRow', 'Delta', 'DeltaS3Wrapper'])
        .describe(
            '* `CSV` - CSV\n* `CSVWithNames` - CSVWithNames\n* `Parquet` - Parquet\n* `JSONEachRow` - JSON\n* `Delta` - Delta\n* `DeltaS3Wrapper` - DeltaS3Wrapper'
        ),
    url_pattern: zod.string().max(warehouseTablesFileCreateBodyUrlPatternMax),
    credential: zod.object({
        id: zod.string(),
        created_by: zod.object({
            id: zod.number(),
            uuid: zod.string(),
            distinct_id: zod.string().max(warehouseTablesFileCreateBodyCredentialCreatedByOneDistinctIdMax).nullish(),
            first_name: zod.string().max(warehouseTablesFileCreateBodyCredentialCreatedByOneFirstNameMax).optional(),
            last_name: zod.string().max(warehouseTablesFileCreateBodyCredentialCreatedByOneLastNameMax).optional(),
            email: zod.string().email().max(warehouseTablesFileCreateBodyCredentialCreatedByOneEmailMax),
            is_email_verified: zod.boolean().nullish(),
            hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
            role_at_organization: zod
                .union([
                    zod
                        .enum([
                            'engineering',
                            'data',
                            'product',
                            'founder',
                            'leadership',
                            'marketing',
                            'sales',
                            'other',
                        ])
                        .describe(
                            '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                        ),
                    zod.enum(['']),
                    zod.literal(null),
                ])
                .nullish(),
        }),
        created_at: zod.string().datetime({}),
        access_key: zod.string().max(warehouseTablesFileCreateBodyCredentialAccessKeyMax),
        access_secret: zod.string().max(warehouseTablesFileCreateBodyCredentialAccessSecretMax),
    }),
    options: zod.record(zod.string(), zod.unknown()).optional(),
})

/**
 * Create, Read, Update and Delete View Columns.
 */
export const WarehouseViewLinkListParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const WarehouseViewLinkListQueryParams = zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
    search: zod.string().optional().describe('A search term.'),
})

export const warehouseViewLinkListResponseResultsItemCreatedByOneDistinctIdMax = 200

export const warehouseViewLinkListResponseResultsItemCreatedByOneFirstNameMax = 150

export const warehouseViewLinkListResponseResultsItemCreatedByOneLastNameMax = 150

export const warehouseViewLinkListResponseResultsItemCreatedByOneEmailMax = 254

export const warehouseViewLinkListResponseResultsItemSourceTableNameMax = 400

export const warehouseViewLinkListResponseResultsItemSourceTableKeyMax = 400

export const warehouseViewLinkListResponseResultsItemJoiningTableNameMax = 400

export const warehouseViewLinkListResponseResultsItemJoiningTableKeyMax = 400

export const warehouseViewLinkListResponseResultsItemFieldNameMax = 400

export const WarehouseViewLinkListResponse = zod.object({
    count: zod.number(),
    next: zod.string().url().nullish(),
    previous: zod.string().url().nullish(),
    results: zod.array(
        zod.object({
            id: zod.string(),
            deleted: zod.boolean().nullish(),
            created_by: zod.object({
                id: zod.number(),
                uuid: zod.string(),
                distinct_id: zod
                    .string()
                    .max(warehouseViewLinkListResponseResultsItemCreatedByOneDistinctIdMax)
                    .nullish(),
                first_name: zod
                    .string()
                    .max(warehouseViewLinkListResponseResultsItemCreatedByOneFirstNameMax)
                    .optional(),
                last_name: zod.string().max(warehouseViewLinkListResponseResultsItemCreatedByOneLastNameMax).optional(),
                email: zod.string().email().max(warehouseViewLinkListResponseResultsItemCreatedByOneEmailMax),
                is_email_verified: zod.boolean().nullish(),
                hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
                role_at_organization: zod
                    .union([
                        zod
                            .enum([
                                'engineering',
                                'data',
                                'product',
                                'founder',
                                'leadership',
                                'marketing',
                                'sales',
                                'other',
                            ])
                            .describe(
                                '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                            ),
                        zod.enum(['']),
                        zod.literal(null),
                    ])
                    .nullish(),
            }),
            created_at: zod.string().datetime({}),
            source_table_name: zod.string().max(warehouseViewLinkListResponseResultsItemSourceTableNameMax),
            source_table_key: zod.string().max(warehouseViewLinkListResponseResultsItemSourceTableKeyMax),
            joining_table_name: zod.string().max(warehouseViewLinkListResponseResultsItemJoiningTableNameMax),
            joining_table_key: zod.string().max(warehouseViewLinkListResponseResultsItemJoiningTableKeyMax),
            field_name: zod.string().max(warehouseViewLinkListResponseResultsItemFieldNameMax),
            configuration: zod.unknown().nullish(),
        })
    ),
})

/**
 * Create, Read, Update and Delete View Columns.
 */
export const WarehouseViewLinkCreateParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const warehouseViewLinkCreateBodySourceTableNameMax = 400

export const warehouseViewLinkCreateBodySourceTableKeyMax = 400

export const warehouseViewLinkCreateBodyJoiningTableNameMax = 400

export const warehouseViewLinkCreateBodyJoiningTableKeyMax = 400

export const warehouseViewLinkCreateBodyFieldNameMax = 400

export const WarehouseViewLinkCreateBody = zod.object({
    deleted: zod.boolean().nullish(),
    source_table_name: zod.string().max(warehouseViewLinkCreateBodySourceTableNameMax),
    source_table_key: zod.string().max(warehouseViewLinkCreateBodySourceTableKeyMax),
    joining_table_name: zod.string().max(warehouseViewLinkCreateBodyJoiningTableNameMax),
    joining_table_key: zod.string().max(warehouseViewLinkCreateBodyJoiningTableKeyMax),
    field_name: zod.string().max(warehouseViewLinkCreateBodyFieldNameMax),
    configuration: zod.unknown().nullish(),
})

/**
 * Create, Read, Update and Delete View Columns.
 */
export const WarehouseViewLinkValidateCreateParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const warehouseViewLinkValidateCreateBodyJoiningTableNameMax = 255

export const warehouseViewLinkValidateCreateBodyJoiningTableKeyMax = 255

export const warehouseViewLinkValidateCreateBodySourceTableNameMax = 255

export const warehouseViewLinkValidateCreateBodySourceTableKeyMax = 255

export const WarehouseViewLinkValidateCreateBody = zod.object({
    joining_table_name: zod.string().max(warehouseViewLinkValidateCreateBodyJoiningTableNameMax),
    joining_table_key: zod.string().max(warehouseViewLinkValidateCreateBodyJoiningTableKeyMax),
    source_table_name: zod.string().max(warehouseViewLinkValidateCreateBodySourceTableNameMax),
    source_table_key: zod.string().max(warehouseViewLinkValidateCreateBodySourceTableKeyMax),
})

/**
 * Create, Read, Update and Delete View Columns.
 */
export const WarehouseViewLinksListParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const WarehouseViewLinksListQueryParams = zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
    search: zod.string().optional().describe('A search term.'),
})

export const warehouseViewLinksListResponseResultsItemCreatedByOneDistinctIdMax = 200

export const warehouseViewLinksListResponseResultsItemCreatedByOneFirstNameMax = 150

export const warehouseViewLinksListResponseResultsItemCreatedByOneLastNameMax = 150

export const warehouseViewLinksListResponseResultsItemCreatedByOneEmailMax = 254

export const warehouseViewLinksListResponseResultsItemSourceTableNameMax = 400

export const warehouseViewLinksListResponseResultsItemSourceTableKeyMax = 400

export const warehouseViewLinksListResponseResultsItemJoiningTableNameMax = 400

export const warehouseViewLinksListResponseResultsItemJoiningTableKeyMax = 400

export const warehouseViewLinksListResponseResultsItemFieldNameMax = 400

export const WarehouseViewLinksListResponse = zod.object({
    count: zod.number(),
    next: zod.string().url().nullish(),
    previous: zod.string().url().nullish(),
    results: zod.array(
        zod.object({
            id: zod.string(),
            deleted: zod.boolean().nullish(),
            created_by: zod.object({
                id: zod.number(),
                uuid: zod.string(),
                distinct_id: zod
                    .string()
                    .max(warehouseViewLinksListResponseResultsItemCreatedByOneDistinctIdMax)
                    .nullish(),
                first_name: zod
                    .string()
                    .max(warehouseViewLinksListResponseResultsItemCreatedByOneFirstNameMax)
                    .optional(),
                last_name: zod
                    .string()
                    .max(warehouseViewLinksListResponseResultsItemCreatedByOneLastNameMax)
                    .optional(),
                email: zod.string().email().max(warehouseViewLinksListResponseResultsItemCreatedByOneEmailMax),
                is_email_verified: zod.boolean().nullish(),
                hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
                role_at_organization: zod
                    .union([
                        zod
                            .enum([
                                'engineering',
                                'data',
                                'product',
                                'founder',
                                'leadership',
                                'marketing',
                                'sales',
                                'other',
                            ])
                            .describe(
                                '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                            ),
                        zod.enum(['']),
                        zod.literal(null),
                    ])
                    .nullish(),
            }),
            created_at: zod.string().datetime({}),
            source_table_name: zod.string().max(warehouseViewLinksListResponseResultsItemSourceTableNameMax),
            source_table_key: zod.string().max(warehouseViewLinksListResponseResultsItemSourceTableKeyMax),
            joining_table_name: zod.string().max(warehouseViewLinksListResponseResultsItemJoiningTableNameMax),
            joining_table_key: zod.string().max(warehouseViewLinksListResponseResultsItemJoiningTableKeyMax),
            field_name: zod.string().max(warehouseViewLinksListResponseResultsItemFieldNameMax),
            configuration: zod.unknown().nullish(),
        })
    ),
})

/**
 * Create, Read, Update and Delete View Columns.
 */
export const WarehouseViewLinksCreateParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const warehouseViewLinksCreateBodySourceTableNameMax = 400

export const warehouseViewLinksCreateBodySourceTableKeyMax = 400

export const warehouseViewLinksCreateBodyJoiningTableNameMax = 400

export const warehouseViewLinksCreateBodyJoiningTableKeyMax = 400

export const warehouseViewLinksCreateBodyFieldNameMax = 400

export const WarehouseViewLinksCreateBody = zod.object({
    deleted: zod.boolean().nullish(),
    source_table_name: zod.string().max(warehouseViewLinksCreateBodySourceTableNameMax),
    source_table_key: zod.string().max(warehouseViewLinksCreateBodySourceTableKeyMax),
    joining_table_name: zod.string().max(warehouseViewLinksCreateBodyJoiningTableNameMax),
    joining_table_key: zod.string().max(warehouseViewLinksCreateBodyJoiningTableKeyMax),
    field_name: zod.string().max(warehouseViewLinksCreateBodyFieldNameMax),
    configuration: zod.unknown().nullish(),
})

/**
 * Create, Read, Update and Delete View Columns.
 */
export const WarehouseViewLinksValidateCreateParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const warehouseViewLinksValidateCreateBodyJoiningTableNameMax = 255

export const warehouseViewLinksValidateCreateBodyJoiningTableKeyMax = 255

export const warehouseViewLinksValidateCreateBodySourceTableNameMax = 255

export const warehouseViewLinksValidateCreateBodySourceTableKeyMax = 255

export const WarehouseViewLinksValidateCreateBody = zod.object({
    joining_table_name: zod.string().max(warehouseViewLinksValidateCreateBodyJoiningTableNameMax),
    joining_table_key: zod.string().max(warehouseViewLinksValidateCreateBodyJoiningTableKeyMax),
    source_table_name: zod.string().max(warehouseViewLinksValidateCreateBodySourceTableNameMax),
    source_table_key: zod.string().max(warehouseViewLinksValidateCreateBodySourceTableKeyMax),
})
