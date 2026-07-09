/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
/**
 * * `full_refresh` - full_refresh
 * * `incremental` - incremental
 * * `append` - append
 * * `webhook` - webhook
 * * `cdc` - cdc
 * * `xmin` - xmin
 */
export type SyncTypeEnumApi = (typeof SyncTypeEnumApi)[keyof typeof SyncTypeEnumApi]

export const SyncTypeEnumApi = {
    FullRefresh: 'full_refresh',
    Incremental: 'incremental',
    Append: 'append',
    Webhook: 'webhook',
    Cdc: 'cdc',
    Xmin: 'xmin',
} as const

/**
 * * `integer` - integer
 * * `numeric` - numeric
 * * `datetime` - datetime
 * * `date` - date
 * * `timestamp` - timestamp
 * * `objectid` - objectid
 * * `xid` - xid
 */
export type IncrementalFieldTypeEnumApi = (typeof IncrementalFieldTypeEnumApi)[keyof typeof IncrementalFieldTypeEnumApi]

export const IncrementalFieldTypeEnumApi = {
    Integer: 'integer',
    Numeric: 'numeric',
    Datetime: 'datetime',
    Date: 'date',
    Timestamp: 'timestamp',
    Objectid: 'objectid',
    Xid: 'xid',
} as const

/**
 * * `never` - never
 * * `1min` - 1min
 * * `5min` - 5min
 * * `15min` - 15min
 * * `30min` - 30min
 * * `1hour` - 1hour
 * * `6hour` - 6hour
 * * `12hour` - 12hour
 * * `24hour` - 24hour
 * * `7day` - 7day
 * * `30day` - 30day
 */
export type SyncFrequencyEnumApi = (typeof SyncFrequencyEnumApi)[keyof typeof SyncFrequencyEnumApi]

export const SyncFrequencyEnumApi = {
    Never: 'never',
    '1min': '1min',
    '5min': '5min',
    '15min': '15min',
    '30min': '30min',
    '1hour': '1hour',
    '6hour': '6hour',
    '12hour': '12hour',
    '24hour': '24hour',
    '7day': '7day',
    '30day': '30day',
} as const

/**
 * * `consolidated` - consolidated
 * * `cdc_only` - cdc_only
 * * `both` - both
 */
export type CdcTableModeEnumApi = (typeof CdcTableModeEnumApi)[keyof typeof CdcTableModeEnumApi]

export const CdcTableModeEnumApi = {
    Consolidated: 'consolidated',
    CdcOnly: 'cdc_only',
    Both: 'both',
} as const

/**
 * @nullable
 */
export type ExternalDataSchemaApiTable = { [key: string]: unknown } | null

export type ExternalDataSchemaApiRowFiltersItem = {
    column: string
    /** One of: > >= < <= = != IN "NOT IN". */
    operator: string
    /** Comparison value; must match the column's type. For `IN` / `NOT IN`, a comma-separated list (e.g. `1, 2, 3` or `'a','b'`). */
    value: unknown
}

export type ExternalDataSchemaApiAvailableColumnsItem = {
    name: string
    data_type?: string
    is_nullable?: boolean
}

/**
 * Lightweight parent-source summary (id, source_type, column-selection support, the requesting user's access level). Only populated on the single-schema retrieve endpoint — `null` elsewhere — so read-only views can render without fetching the full source and all its schemas.
 * @nullable
 */
export type ExternalDataSchemaApiSource = {
    readonly id?: string
    readonly source_type?: string
    readonly supports_column_selection?: boolean
    readonly supports_row_filters?: boolean
    /** @nullable */
    readonly user_access_level?: string | null
} | null

export interface ExternalDataSchemaApi {
    readonly id: string
    readonly name: string
    /** @nullable */
    readonly label: string | null
    /** @nullable */
    readonly table: ExternalDataSchemaApiTable
    should_sync?: boolean
    /** @nullable */
    readonly last_synced_at: string | null
    /**
     * The latest error that occurred when syncing this schema.
     * @nullable
     */
    readonly latest_error: string | null
    readonly incremental: boolean
    /** @nullable */
    readonly status: string | null
    /** Sync strategy: incremental, full_refresh, append, cdc, or xmin.
     *
     * * `full_refresh` - full_refresh
     * * `incremental` - incremental
     * * `append` - append
     * * `webhook` - webhook
     * * `cdc` - cdc
     * * `xmin` - xmin */
    sync_type?: SyncTypeEnumApi | null
    /**
     * Column name used to track sync progress.
     * @nullable
     */
    incremental_field?: string | null
    /** Data type of the incremental field.
     *
     * * `integer` - integer
     * * `numeric` - numeric
     * * `datetime` - datetime
     * * `date` - date
     * * `timestamp` - timestamp
     * * `objectid` - objectid
     * * `xid` - xid */
    incremental_field_type?: IncrementalFieldTypeEnumApi | null
    /**
     * Seconds to subtract from the stored incremental watermark at sync time, so each incremental run re-reads a rolling overlap window and catches late or backdated rows. Applies to timestamp/date incremental fields only. The stored watermark is unchanged. Maximum 5184000 (60 days).
     * @minimum 0
     * @maximum 5184000
     * @nullable
     */
    incremental_field_lookback_seconds?: number | null
    /** How often to sync.
     *
     * * `never` - never
     * * `1min` - 1min
     * * `5min` - 5min
     * * `15min` - 15min
     * * `30min` - 30min
     * * `1hour` - 1hour
     * * `6hour` - 6hour
     * * `12hour` - 12hour
     * * `24hour` - 24hour
     * * `7day` - 7day
     * * `30day` - 30day */
    sync_frequency?: SyncFrequencyEnumApi | null
    /**
     * UTC time of day to run the sync (HH:MM:SS).
     * @nullable
     */
    sync_time_of_day?: string | null
    /** @nullable */
    readonly description: string | null
    /**
     * Column names for primary key deduplication.
     * @nullable
     */
    primary_key_columns?: string[] | null
    /** For CDC syncs: consolidated, cdc_only, or both.
     *
     * * `consolidated` - consolidated
     * * `cdc_only` - cdc_only
     * * `both` - both */
    cdc_table_mode?: CdcTableModeEnumApi | null
    /**
     * Names of source columns to sync. `null` (default) syncs all columns. Primary-key columns and the active incremental field are always retained, even if not listed here.
     * @nullable
     */
    enabled_columns?: string[] | null
    /**
     * Predicates ANDed onto the source query so only matching rows sync. Each is `{column, operator, value}`; `null`/empty (default) syncs all rows. The operator must be one of `> >= < <= = != IN "NOT IN"` and the value must match the column's type (for `IN`/`NOT IN`, a comma-separated list like `1, 2, 3` or `'a','b'`). Applied on the next sync — not retroactive to already-synced rows.
     * @nullable
     */
    row_filters?: ExternalDataSchemaApiRowFiltersItem[] | null
    /** Column metadata (name, data type, nullable) for this schema. For SQL sources this is the source-side schema discovered via `refresh_schemas`; for other sources (and once synced) it falls back to the synced table's columns. Empty only before the first successful sync/refresh. */
    readonly available_columns: readonly ExternalDataSchemaApiAvailableColumnsItem[]
    /**
     * Lightweight parent-source summary (id, source_type, column-selection support, the requesting user's access level). Only populated on the single-schema retrieve endpoint — `null` elsewhere — so read-only views can render without fetching the full source and all its schemas.
     * @nullable
     */
    readonly source: ExternalDataSchemaApiSource
}

export interface PaginatedExternalDataSchemaListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: ExternalDataSchemaApi[]
}

/**
 * @nullable
 */
export type PatchedExternalDataSchemaApiTable = { [key: string]: unknown } | null

export type PatchedExternalDataSchemaApiRowFiltersItem = {
    column: string
    /** One of: > >= < <= = != IN "NOT IN". */
    operator: string
    /** Comparison value; must match the column's type. For `IN` / `NOT IN`, a comma-separated list (e.g. `1, 2, 3` or `'a','b'`). */
    value: unknown
}

export type PatchedExternalDataSchemaApiAvailableColumnsItem = {
    name: string
    data_type?: string
    is_nullable?: boolean
}

/**
 * Lightweight parent-source summary (id, source_type, column-selection support, the requesting user's access level). Only populated on the single-schema retrieve endpoint — `null` elsewhere — so read-only views can render without fetching the full source and all its schemas.
 * @nullable
 */
export type PatchedExternalDataSchemaApiSource = {
    readonly id?: string
    readonly source_type?: string
    readonly supports_column_selection?: boolean
    readonly supports_row_filters?: boolean
    /** @nullable */
    readonly user_access_level?: string | null
} | null

export interface PatchedExternalDataSchemaApi {
    readonly id?: string
    readonly name?: string
    /** @nullable */
    readonly label?: string | null
    /** @nullable */
    readonly table?: PatchedExternalDataSchemaApiTable
    should_sync?: boolean
    /** @nullable */
    readonly last_synced_at?: string | null
    /**
     * The latest error that occurred when syncing this schema.
     * @nullable
     */
    readonly latest_error?: string | null
    readonly incremental?: boolean
    /** @nullable */
    readonly status?: string | null
    /** Sync strategy: incremental, full_refresh, append, cdc, or xmin.
     *
     * * `full_refresh` - full_refresh
     * * `incremental` - incremental
     * * `append` - append
     * * `webhook` - webhook
     * * `cdc` - cdc
     * * `xmin` - xmin */
    sync_type?: SyncTypeEnumApi | null
    /**
     * Column name used to track sync progress.
     * @nullable
     */
    incremental_field?: string | null
    /** Data type of the incremental field.
     *
     * * `integer` - integer
     * * `numeric` - numeric
     * * `datetime` - datetime
     * * `date` - date
     * * `timestamp` - timestamp
     * * `objectid` - objectid
     * * `xid` - xid */
    incremental_field_type?: IncrementalFieldTypeEnumApi | null
    /**
     * Seconds to subtract from the stored incremental watermark at sync time, so each incremental run re-reads a rolling overlap window and catches late or backdated rows. Applies to timestamp/date incremental fields only. The stored watermark is unchanged. Maximum 5184000 (60 days).
     * @minimum 0
     * @maximum 5184000
     * @nullable
     */
    incremental_field_lookback_seconds?: number | null
    /** How often to sync.
     *
     * * `never` - never
     * * `1min` - 1min
     * * `5min` - 5min
     * * `15min` - 15min
     * * `30min` - 30min
     * * `1hour` - 1hour
     * * `6hour` - 6hour
     * * `12hour` - 12hour
     * * `24hour` - 24hour
     * * `7day` - 7day
     * * `30day` - 30day */
    sync_frequency?: SyncFrequencyEnumApi | null
    /**
     * UTC time of day to run the sync (HH:MM:SS).
     * @nullable
     */
    sync_time_of_day?: string | null
    /** @nullable */
    readonly description?: string | null
    /**
     * Column names for primary key deduplication.
     * @nullable
     */
    primary_key_columns?: string[] | null
    /** For CDC syncs: consolidated, cdc_only, or both.
     *
     * * `consolidated` - consolidated
     * * `cdc_only` - cdc_only
     * * `both` - both */
    cdc_table_mode?: CdcTableModeEnumApi | null
    /**
     * Names of source columns to sync. `null` (default) syncs all columns. Primary-key columns and the active incremental field are always retained, even if not listed here.
     * @nullable
     */
    enabled_columns?: string[] | null
    /**
     * Predicates ANDed onto the source query so only matching rows sync. Each is `{column, operator, value}`; `null`/empty (default) syncs all rows. The operator must be one of `> >= < <= = != IN "NOT IN"` and the value must match the column's type (for `IN`/`NOT IN`, a comma-separated list like `1, 2, 3` or `'a','b'`). Applied on the next sync — not retroactive to already-synced rows.
     * @nullable
     */
    row_filters?: PatchedExternalDataSchemaApiRowFiltersItem[] | null
    /** Column metadata (name, data type, nullable) for this schema. For SQL sources this is the source-side schema discovered via `refresh_schemas`; for other sources (and once synced) it falls back to the synced table's columns. Empty only before the first successful sync/refresh. */
    readonly available_columns?: readonly PatchedExternalDataSchemaApiAvailableColumnsItem[]
    /**
     * Lightweight parent-source summary (id, source_type, column-selection support, the requesting user's access level). Only populated on the single-schema retrieve endpoint — `null` elsewhere — so read-only views can render without fetching the full source and all its schemas.
     * @nullable
     */
    readonly source?: PatchedExternalDataSchemaApiSource
}

/**
 * * `web` - web
 * * `api` - api
 * * `mcp` - mcp
 */
export type CreatedViaEnumApi = (typeof CreatedViaEnumApi)[keyof typeof CreatedViaEnumApi]

export const CreatedViaEnumApi = {
    Web: 'web',
    Api: 'api',
    Mcp: 'mcp',
} as const

/**
 * * `Ashby` - Ashby
 * * `Supabase` - Supabase
 * * `CustomerIO` - CustomerIO
 * * `Github` - Github
 * * `Stripe` - Stripe
 * * `Hubspot` - Hubspot
 * * `Postgres` - Postgres
 * * `Zendesk` - Zendesk
 * * `Snowflake` - Snowflake
 * * `Salesforce` - Salesforce
 * * `MySQL` - MySQL
 * * `MongoDB` - MongoDB
 * * `MSSQL` - MSSQL
 * * `Vitally` - Vitally
 * * `BigQuery` - BigQuery
 * * `Chargebee` - Chargebee
 * * `Clerk` - Clerk
 * * `GoogleAds` - GoogleAds
 * * `GoogleSearchConsole` - GoogleSearchConsole
 * * `TemporalIO` - TemporalIO
 * * `DoIt` - DoIt
 * * `GoogleSheets` - GoogleSheets
 * * `MetaAds` - MetaAds
 * * `Klaviyo` - Klaviyo
 * * `Mailchimp` - Mailchimp
 * * `Braze` - Braze
 * * `Mailjet` - Mailjet
 * * `Redshift` - Redshift
 * * `Polar` - Polar
 * * `RevenueCat` - RevenueCat
 * * `LinkedinAds` - LinkedinAds
 * * `RedditAds` - RedditAds
 * * `TikTokAds` - TikTokAds
 * * `BingAds` - BingAds
 * * `Shopify` - Shopify
 * * `Attio` - Attio
 * * `SnapchatAds` - SnapchatAds
 * * `Linear` - Linear
 * * `Intercom` - Intercom
 * * `Amplitude` - Amplitude
 * * `Mixpanel` - Mixpanel
 * * `Jira` - Jira
 * * `ActiveCampaign` - ActiveCampaign
 * * `Marketo` - Marketo
 * * `Adjust` - Adjust
 * * `AppsFlyer` - AppsFlyer
 * * `Freshdesk` - Freshdesk
 * * `GoogleAnalytics` - GoogleAnalytics
 * * `Pipedrive` - Pipedrive
 * * `SendGrid` - SendGrid
 * * `Slack` - Slack
 * * `PagerDuty` - PagerDuty
 * * `Asana` - Asana
 * * `Notion` - Notion
 * * `Airtable` - Airtable
 * * `Greenhouse` - Greenhouse
 * * `BambooHR` - BambooHR
 * * `Lever` - Lever
 * * `GitLab` - GitLab
 * * `Datadog` - Datadog
 * * `Sentry` - Sentry
 * * `Pendo` - Pendo
 * * `FullStory` - FullStory
 * * `AmazonAds` - AmazonAds
 * * `PinterestAds` - PinterestAds
 * * `AppleSearchAds` - AppleSearchAds
 * * `QuickBooks` - QuickBooks
 * * `Xero` - Xero
 * * `NetSuite` - NetSuite
 * * `WooCommerce` - WooCommerce
 * * `BigCommerce` - BigCommerce
 * * `PayPal` - PayPal
 * * `Square` - Square
 * * `Zoom` - Zoom
 * * `Trello` - Trello
 * * `Monday` - Monday
 * * `ClickUp` - ClickUp
 * * `Confluence` - Confluence
 * * `Recurly` - Recurly
 * * `SalesLoft` - SalesLoft
 * * `Outreach` - Outreach
 * * `Gong` - Gong
 * * `Calendly` - Calendly
 * * `Typeform` - Typeform
 * * `Iterable` - Iterable
 * * `ZohoCRM` - ZohoCRM
 * * `Close` - Close
 * * `Oracle` - Oracle
 * * `DynamoDB` - DynamoDB
 * * `Elasticsearch` - Elasticsearch
 * * `Kafka` - Kafka
 * * `LaunchDarkly` - LaunchDarkly
 * * `Braintree` - Braintree
 * * `Recharge` - Recharge
 * * `HelpScout` - HelpScout
 * * `Gorgias` - Gorgias
 * * `Instagram` - Instagram
 * * `YouTubeAnalytics` - YouTubeAnalytics
 * * `FacebookPages` - FacebookPages
 * * `TwitterAds` - TwitterAds
 * * `Workday` - Workday
 * * `ServiceNow` - ServiceNow
 * * `Pardot` - Pardot
 * * `Copper` - Copper
 * * `Front` - Front
 * * `ChartMogul` - ChartMogul
 * * `Zuora` - Zuora
 * * `Paddle` - Paddle
 * * `CircleCI` - CircleCI
 * * `CockroachDB` - CockroachDB
 * * `Firebase` - Firebase
 * * `AzureBlob` - AzureBlob
 * * `GoogleDrive` - GoogleDrive
 * * `OneDrive` - OneDrive
 * * `SharePoint` - SharePoint
 * * `Box` - Box
 * * `SFTP` - SFTP
 * * `MicrosoftTeams` - MicrosoftTeams
 * * `Aircall` - Aircall
 * * `Webflow` - Webflow
 * * `Okta` - Okta
 * * `Auth0` - Auth0
 * * `Productboard` - Productboard
 * * `Smartsheet` - Smartsheet
 * * `Wrike` - Wrike
 * * `Plaid` - Plaid
 * * `SurveyMonkey` - SurveyMonkey
 * * `Eventbrite` - Eventbrite
 * * `RingCentral` - RingCentral
 * * `Twilio` - Twilio
 * * `Freshsales` - Freshsales
 * * `Shortcut` - Shortcut
 * * `ConvertKit` - ConvertKit
 * * `Drip` - Drip
 * * `CampaignMonitor` - CampaignMonitor
 * * `MailerLite` - MailerLite
 * * `Omnisend` - Omnisend
 * * `Brevo` - Brevo
 * * `Postmark` - Postmark
 * * `Granola` - Granola
 * * `BuildBetter` - BuildBetter
 * * `Convex` - Convex
 * * `ClickHouse` - ClickHouse
 * * `Plain` - Plain
 * * `Resend` - Resend
 * * `PgAnalyze` - PgAnalyze
 * * `WorkOS` - WorkOS
 * * `AmazonS3` - AmazonS3
 * * `GoogleCloudStorage` - GoogleCloudStorage
 * * `Databricks` - Databricks
 * * `Dynamics365` - Dynamics365
 * * `SalesforceMarketingCloud` - SalesforceMarketingCloud
 * * `Db2` - Db2
 * * `Heap` - Heap
 * * `AdobeAnalytics` - AdobeAnalytics
 * * `Matomo` - Matomo
 * * `Optimizely` - Optimizely
 * * `Adyen` - Adyen
 * * `GoCardless` - GoCardless
 * * `Mollie` - Mollie
 * * `CheckoutCom` - CheckoutCom
 * * `Branch` - Branch
 * * `Criteo` - Criteo
 * * `Outbrain` - Outbrain
 * * `Taboola` - Taboola
 * * `AdRoll` - AdRoll
 * * `DisplayVideo360` - DisplayVideo360
 * * `GoogleAdManager` - GoogleAdManager
 * * `CampaignManager360` - CampaignManager360
 * * `SearchAds360` - SearchAds360
 * * `AdobeCommerce` - AdobeCommerce
 * * `AmazonSellingPartner` - AmazonSellingPartner
 * * `Ebay` - Ebay
 * * `Commercetools` - Commercetools
 * * `LightspeedRetail` - LightspeedRetail
 * * `ShipStation` - ShipStation
 * * `ConstantContact` - ConstantContact
 * * `Mailgun` - Mailgun
 * * `Eloqua` - Eloqua
 * * `Sailthru` - Sailthru
 * * `Ortto` - Ortto
 * * `Attentive` - Attentive
 * * `Kustomer` - Kustomer
 * * `Dixa` - Dixa
 * * `Gladly` - Gladly
 * * `Qualtrics` - Qualtrics
 * * `Delighted` - Delighted
 * * `AzureDevOps` - AzureDevOps
 * * `Rollbar` - Rollbar
 * * `Opsgenie` - Opsgenie
 * * `IncidentIo` - IncidentIo
 * * `Pingdom` - Pingdom
 * * `Cloudflare` - Cloudflare
 * * `CosmosDB` - CosmosDB
 * * `PlanetScale` - PlanetScale
 * * `SapHana` - SapHana
 * * `Rippling` - Rippling
 * * `HiBob` - HiBob
 * * `Personio` - Personio
 * * `Deel` - Deel
 * * `AdpWorkforceNow` - AdpWorkforceNow
 * * `Paylocity` - Paylocity
 * * `Gusto` - Gusto
 * * `CultureAmp` - CultureAmp
 * * `Lattice` - Lattice
 * * `SageIntacct` - SageIntacct
 * * `FreshBooks` - FreshBooks
 * * `Expensify` - Expensify
 * * `Ramp` - Ramp
 * * `Brex` - Brex
 * * `Coupa` - Coupa
 * * `SapConcur` - SapConcur
 * * `Apollo` - Apollo
 * * `Crunchbase` - Crunchbase
 * * `ZoomInfo` - ZoomInfo
 * * `Clari` - Clari
 * * `Chorus` - Chorus
 * * `Coda` - Coda
 * * `Guru` - Guru
 * * `Dropbox` - Dropbox
 * * `Docusign` - Docusign
 * * `PandaDoc` - PandaDoc
 * * `SapErp` - SapErp
 * * `SapSuccessFactors` - SapSuccessFactors
 * * `OracleEbs` - OracleEbs
 * * `OracleFusion` - OracleFusion
 * * `AmazonSNS` - AmazonSNS
 * * `AmazonEventBridge` - AmazonEventBridge
 * * `AmazonSQS` - AmazonSQS
 * * `AmazonKinesis` - AmazonKinesis
 * * `AmazonCloudWatch` - AmazonCloudWatch
 * * `OpenAIAds` - OpenAIAds
 * * `OneHundredMs` - OneHundredMs
 * * `SevenShifts` - SevenShifts
 * * `AcuityScheduling` - AcuityScheduling
 * * `AgileCRM` - AgileCRM
 * * `Aha` - Aha
 * * `Airbyte` - Airbyte
 * * `Akeneo` - Akeneo
 * * `Algolia` - Algolia
 * * `AlpacaBrokerAPI` - AlpacaBrokerAPI
 * * `ApifyDataset` - ApifyDataset
 * * `Appcues` - Appcues
 * * `Appfigures` - Appfigures
 * * `Appfollow` - Appfollow
 * * `Apptivo` - Apptivo
 * * `AssemblyAI` - AssemblyAI
 * * `Awin` - Awin
 * * `AwsCloudTrail` - AwsCloudTrail
 * * `AzureTableStorage` - AzureTableStorage
 * * `Babelforce` - Babelforce
 * * `Basecamp` - Basecamp
 * * `Beamer` - Beamer
 * * `BigMailer` - BigMailer
 * * `Bluetally` - Bluetally
 * * `BoldSign` - BoldSign
 * * `BreezyHR` - BreezyHR
 * * `Bugsnag` - Bugsnag
 * * `Buildkite` - Buildkite
 * * `Bunny` - Bunny
 * * `Buzzsprout` - Buzzsprout
 * * `CalCom` - CalCom
 * * `CallRail` - CallRail
 * * `Campayn` - Campayn
 * * `Canny` - Canny
 * * `CapsuleCRM` - CapsuleCRM
 * * `CaptainData` - CaptainData
 * * `CartCom` - CartCom
 * * `CastorEDC` - CastorEDC
 * * `Chameleon` - Chameleon
 * * `Chargedesk` - Chargedesk
 * * `Chargify` - Chargify
 * * `Chift` - Chift
 * * `Churnkey` - Churnkey
 * * `Cin7` - Cin7
 * * `CiscoMeraki` - CiscoMeraki
 * * `Clazar` - Clazar
 * * `Clockify` - Clockify
 * * `Clockodo` - Clockodo
 * * `Cloudbeds` - Cloudbeds
 * * `Coassemble` - Coassemble
 * * `Codefresh` - Codefresh
 * * `Concord` - Concord
 * * `ConfigCat` - ConfigCat
 * * `Couchbase` - Couchbase
 * * `Curve` - Curve
 * * `Customerly` - Customerly
 * * `Datascope` - Datascope
 * * `Dbt` - Dbt
 * * `Deputy` - Deputy
 * * `DevinAI` - DevinAI
 * * `Docuseal` - Docuseal
 * * `Dolibarr` - Dolibarr
 * * `Dremio` - Dremio
 * * `DropboxSign` - DropboxSign
 * * `Dwolla` - Dwolla
 * * `EConomic` - EConomic
 * * `Easypost` - Easypost
 * * `Easypromos` - Easypromos
 * * `Elasticemail` - Elasticemail
 * * `EmailOctopus` - EmailOctopus
 * * `EmploymentHero` - EmploymentHero
 * * `Encharge` - Encharge
 * * `Eventee` - Eventee
 * * `Eventzilla` - Eventzilla
 * * `Everhour` - Everhour
 * * `EZOfficeInventory` - EZOfficeInventory
 * * `Factorial` - Factorial
 * * `Fastbill` - Fastbill
 * * `Fastly` - Fastly
 * * `Fauna` - Fauna
 * * `Feishu` - Feishu
 * * `Fillout` - Fillout
 * * `Finage` - Finage
 * * `Firebolt` - Firebolt
 * * `FireHydrant` - FireHydrant
 * * `Fleetio` - Fleetio
 * * `Flexmail` - Flexmail
 * * `Flexport` - Flexport
 * * `FloatApp` - FloatApp
 * * `Flowlu` - Flowlu
 * * `Formbricks` - Formbricks
 * * `FreeAgent` - FreeAgent
 * * `Freightview` - Freightview
 * * `Freshcaller` - Freshcaller
 * * `Freshchat` - Freshchat
 * * `Freshservice` - Freshservice
 * * `Fulcrum` - Fulcrum
 * * `GainsightPx` - GainsightPx
 * * `GitBook` - GitBook
 * * `Glassfrog` - Glassfrog
 * * `Goldcast` - Goldcast
 * * `GoLogin` - GoLogin
 * * `Grafana` - Grafana
 * * `GreytHr` - GreytHr
 * * `Gridly` - Gridly
 * * `Harness` - Harness
 * * `Height` - Height
 * * `Hellobaton` - Hellobaton
 * * `HighLevel` - HighLevel
 * * `HoorayHR` - HoorayHR
 * * `Hubplanner` - Hubplanner
 * * `Humanitix` - Humanitix
 * * `Huntr` - Huntr
 * * `Inflowinventory` - Inflowinventory
 * * `InforNexus` - InforNexus
 * * `Insightful` - Insightful
 * * `Insightly` - Insightly
 * * `Instantly` - Instantly
 * * `Instatus` - Instatus
 * * `Intruder` - Intruder
 * * `Invoiced` - Invoiced
 * * `Invoiceninja` - Invoiceninja
 * * `JamfPro` - JamfPro
 * * `JobNimbus` - JobNimbus
 * * `Jotform` - Jotform
 * * `JudgeMeReviews` - JudgeMeReviews
 * * `JustCall` - JustCall
 * * `JustSift` - JustSift
 * * `K6Cloud` - K6Cloud
 * * `Katana` - Katana
 * * `Keka` - Keka
 * * `Kisi` - Kisi
 * * `Kissmetrics` - Kissmetrics
 * * `Klarna` - Klarna
 * * `Klaus` - Klaus
 * * `Lago` - Lago
 * * `Leadfeeder` - Leadfeeder
 * * `Lemlist` - Lemlist
 * * `LessAnnoyingCRM` - LessAnnoyingCRM
 * * `LinkedinPages` - LinkedinPages
 * * `Linkrunner` - Linkrunner
 * * `Linnworks` - Linnworks
 * * `Lob` - Lob
 * * `Lokalise` - Lokalise
 * * `Looker` - Looker
 * * `Luma` - Luma
 * * `MailerSend` - MailerSend
 * * `Mailosaur` - Mailosaur
 * * `Mailtrap` - Mailtrap
 * * `Mantle` - Mantle
 * * `Mention` - Mention
 * * `MercadoAds` - MercadoAds
 * * `Merge` - Merge
 * * `Metabase` - Metabase
 * * `Metricool` - Metricool
 * * `MicrosoftDataverse` - MicrosoftDataverse
 * * `MicrosoftEntraId` - MicrosoftEntraId
 * * `MicrosoftLists` - MicrosoftLists
 * * `Miro` - Miro
 * * `Missive` - Missive
 * * `MixMax` - MixMax
 * * `Mode` - Mode
 * * `Mux` - Mux
 * * `MyHours` - MyHours
 * * `N8n` - N8n
 * * `Navan` - Navan
 * * `NebiusAI` - NebiusAI
 * * `Nexiopay` - Nexiopay
 * * `NinjaOneRMM` - NinjaOneRMM
 * * `NoCRM` - NoCRM
 * * `NorthpassLMS` - NorthpassLMS
 * * `Nutshell` - Nutshell
 * * `Nylas` - Nylas
 * * `Oncehub` - Oncehub
 * * `Onepagecrm` - Onepagecrm
 * * `OneSignal` - OneSignal
 * * `Onfleet` - Onfleet
 * * `OpinionStage` - OpinionStage
 * * `OPUSWatch` - OPUSWatch
 * * `Orb` - Orb
 * * `Orbit` - Orbit
 * * `Oura` - Oura
 * * `Oveit` - Oveit
 * * `PabblySubscriptionsBilling` - PabblySubscriptionsBilling
 * * `Paperform` - Paperform
 * * `Papersign` - Papersign
 * * `Partnerize` - Partnerize
 * * `PartnerStack` - PartnerStack
 * * `PayFit` - PayFit
 * * `Paystack` - Paystack
 * * `Pennylane` - Pennylane
 * * `Perk` - Perk
 * * `PersistIq` - PersistIq
 * * `Persona` - Persona
 * * `Phyllo` - Phyllo
 * * `Picqer` - Picqer
 * * `Pipeliner` - Pipeliner
 * * `PivotalTracker` - PivotalTracker
 * * `Piwik` - Piwik
 * * `Planhat` - Planhat
 * * `Plausible` - Plausible
 * * `Poplar` - Poplar
 * * `PrestaShop` - PrestaShop
 * * `Pretix` - Pretix
 * * `Primetric` - Primetric
 * * `Printify` - Printify
 * * `Productive` - Productive
 * * `Pylon` - Pylon
 * * `Qonto` - Qonto
 * * `Qualaroo` - Qualaroo
 * * `Railz` - Railz
 * * `RDStationMarketing` - RDStationMarketing
 * * `Recruitee` - Recruitee
 * * `Reddit` - Reddit
 * * `ReferralHero` - ReferralHero
 * * `RentCast` - RentCast
 * * `Repairshopr` - Repairshopr
 * * `ReplyIo` - ReplyIo
 * * `RetailExpress` - RetailExpress
 * * `Retently` - Retently
 * * `RevolutMerchant` - RevolutMerchant
 * * `RocketChat` - RocketChat
 * * `Rocketlane` - Rocketlane
 * * `Rootly` - Rootly
 * * `Ruddr` - Ruddr
 * * `SafetyCulture` - SafetyCulture
 * * `SageHR` - SageHR
 * * `Salesflare` - Salesflare
 * * `SAPFieldglass` - SAPFieldglass
 * * `SavvyCal` - SavvyCal
 * * `Secoda` - Secoda
 * * `Segment` - Segment
 * * `Sendowl` - Sendowl
 * * `SendPulse` - SendPulse
 * * `Senseforce` - Senseforce
 * * `Serpstat` - Serpstat
 * * `Sharetribe` - Sharetribe
 * * `Shippo` - Shippo
 * * `ShopWired` - ShopWired
 * * `Shortio` - Shortio
 * * `Shutterstock` - Shutterstock
 * * `SigmaComputing` - SigmaComputing
 * * `SignNow` - SignNow
 * * `SimpleCast` - SimpleCast
 * * `Simplesat` - Simplesat
 * * `Smaily` - Smaily
 * * `SmartEngage` - SmartEngage
 * * `Smartreach` - Smartreach
 * * `Smartwaiver` - Smartwaiver
 * * `SolarwindsServiceDesk` - SolarwindsServiceDesk
 * * `SonarCloud` - SonarCloud
 * * `SparkPost` - SparkPost
 * * `SplitIo` - SplitIo
 * * `SpotifyAds` - SpotifyAds
 * * `SpotlerCRM` - SpotlerCRM
 * * `Squarespace` - Squarespace
 * * `Statsig` - Statsig
 * * `Statuspage` - Statuspage
 * * `Stigg` - Stigg
 * * `Strava` - Strava
 * * `SurveySparrow` - SurveySparrow
 * * `Survicate` - Survicate
 * * `Svix` - Svix
 * * `Systeme` - Systeme
 * * `Tavus` - Tavus
 * * `Teamtailor` - Teamtailor
 * * `Teamwork` - Teamwork
 * * `Tempo` - Tempo
 * * `Testrail` - Testrail
 * * `Thinkific` - Thinkific
 * * `ThinkificCourses` - ThinkificCourses
 * * `ThriveLearning` - ThriveLearning
 * * `Ticketmaster` - Ticketmaster
 * * `TicketTailor` - TicketTailor
 * * `TickTick` - TickTick
 * * `Timely` - Timely
 * * `Tinyemail` - Tinyemail
 * * `Todoist` - Todoist
 * * `Toggl` - Toggl
 * * `TrackPMS` - TrackPMS
 * * `Tremendous` - Tremendous
 * * `TrustPilot` - TrustPilot
 * * `Twitter` - Twitter
 * * `TyntecSMS` - TyntecSMS
 * * `Unleash` - Unleash
 * * `UpPromote` - UpPromote
 * * `Uptick` - Uptick
 * * `Uservoice` - Uservoice
 * * `Vantage` - Vantage
 * * `Veeqo` - Veeqo
 * * `Vercel` - Vercel
 * * `VismaEconomic` - VismaEconomic
 * * `VWO` - VWO
 * * `Waiteraid` - Waiteraid
 * * `Wasabi` - Wasabi
 * * `WhenIWork` - WhenIWork
 * * `Wordpress` - Wordpress
 * * `Workable` - Workable
 * * `Workflowmax` - Workflowmax
 * * `Workramp` - Workramp
 * * `Wufoo` - Wufoo
 * * `Xsolla` - Xsolla
 * * `YandexMetrica` - YandexMetrica
 * * `Yotpo` - Yotpo
 * * `Ynab` - Ynab
 * * `Younium` - Younium
 * * `YouSign` - YouSign
 * * `YoutubeData` - YoutubeData
 * * `ZapierSupportedStorage` - ZapierSupportedStorage
 * * `ZapSign` - ZapSign
 * * `ZendeskSell` - ZendeskSell
 * * `ZendeskSunshine` - ZendeskSunshine
 * * `Zenefits` - Zenefits
 * * `Zenloop` - Zenloop
 * * `ZohoAnalytics` - ZohoAnalytics
 * * `ZohoBigin` - ZohoBigin
 * * `ZohoBilling` - ZohoBilling
 * * `ZohoBooks` - ZohoBooks
 * * `ZohoCampaign` - ZohoCampaign
 * * `ZohoDesk` - ZohoDesk
 * * `ZohoExpense` - ZohoExpense
 * * `ZohoInventory` - ZohoInventory
 * * `ZohoInvoice` - ZohoInvoice
 * * `ZonkaFeedback` - ZonkaFeedback
 * * `AlphaVantage` - AlphaVantage
 * * `Aviationstack` - Aviationstack
 * * `Bitly` - Bitly
 * * `Blogger` - Blogger
 * * `Breezometer` - Breezometer
 * * `CareQualityCommission` - CareQualityCommission
 * * `Cimis` - Cimis
 * * `CoinApi` - CoinApi
 * * `CoinGecko` - CoinGecko
 * * `CoinMarketCap` - CoinMarketCap
 * * `DingConnect` - DingConnect
 * * `Dockerhub` - Dockerhub
 * * `ExchangeRatesApi` - ExchangeRatesApi
 * * `FinancialModelling` - FinancialModelling
 * * `Finnhub` - Finnhub
 * * `Finnworlds` - Finnworlds
 * * `Giphy` - Giphy
 * * `Gmail` - Gmail
 * * `GNews` - GNews
 * * `GoogleCalendar` - GoogleCalendar
 * * `GoogleClassroom` - GoogleClassroom
 * * `GoogleDirectory` - GoogleDirectory
 * * `GoogleForms` - GoogleForms
 * * `GooglePageSpeedInsights` - GooglePageSpeedInsights
 * * `GoogleTasks` - GoogleTasks
 * * `GoogleWebfonts` - GoogleWebfonts
 * * `GoogleWorkspaceAdminReports` - GoogleWorkspaceAdminReports
 * * `HuggingFace` - HuggingFace
 * * `IlluminaBasespace` - IlluminaBasespace
 * * `Imagga` - Imagga
 * * `Interzoid` - Interzoid
 * * `IP2Whois` - IP2Whois
 * * `KYVE` - KYVE
 * * `Marketstack` - Marketstack
 * * `Mendeley` - Mendeley
 * * `Nasa` - Nasa
 * * `NewYorkTimes` - NewYorkTimes
 * * `NewsApi` - NewsApi
 * * `NewsData` - NewsData
 * * `OpenDataDc` - OpenDataDc
 * * `OpenExchangeRates` - OpenExchangeRates
 * * `OpenAQ` - OpenAQ
 * * `OpenFDA` - OpenFDA
 * * `OpenWeather` - OpenWeather
 * * `Outlook` - Outlook
 * * `Perigon` - Perigon
 * * `Pexels` - Pexels
 * * `Pocket` - Pocket
 * * `Polygon` - Polygon
 * * `PyPI` - PyPI
 * * `Recreation` - Recreation
 * * `RKICovid` - RKICovid
 * * `Rss` - Rss
 * * `SimFin` - SimFin
 * * `StockData` - StockData
 * * `Guardian` - Guardian
 * * `TMDb` - TMDb
 * * `TVMaze` - TVMaze
 * * `TwelveData` - TwelveData
 * * `Ubidots` - Ubidots
 * * `USCensus` - USCensus
 * * `Watchmode` - Watchmode
 * * `WikipediaPageviews` - WikipediaPageviews
 * * `YahooFinance` - YahooFinance
 * * `Clarifai` - Clarifai
 * * `Adapty` - Adapty
 * * `Braintrust` - Braintrust
 * * `StreamElements` - StreamElements
 * * `Streamlabs` - Streamlabs
 * * `Datorama` - Datorama
 * * `Ahrefs` - Ahrefs
 * * `Lightfield` - Lightfield
 * * `Appstack` - Appstack
 * * `Razorpay` - Razorpay
 * * `Neon` - Neon
 * * `NewRelic` - NewRelic
 * * `Custom` - Custom
 * * `Tile38` - Tile38
 * * `Chatwoot` - Chatwoot
 * * `Sanity` - Sanity
 * * `Metronome` - Metronome
 * * `Jobber` - Jobber
 * * `Knock` - Knock
 * * `Leexi` - Leexi
 * * `RB2B` - RB2B
 * * `Superwall` - Superwall
 * * `Liana` - Liana
 * * `TawkTo` - TawkTo
 * * `Hightouch` - Hightouch
 * * `LemonSqueezy` - LemonSqueezy
 * * `Ikas` - Ikas
 * * `Talkwalker` - Talkwalker
 * * `NextdoorAds` - NextdoorAds
 * * `AppLovin` - AppLovin
 * * `Baserow` - Baserow
 * * `Plunk` - Plunk
 * * `Dub` - Dub
 * * `AirOps` - AirOps
 * * `Podium` - Podium
 * * `Loops` - Loops
 * * `Redis` - Redis
 * * `Mercury` - Mercury
 * * `Gojiberry` - Gojiberry
 * * `Teachable` - Teachable
 * * `PeecAI` - PeecAI
 * * `Healthchecks` - Healthchecks
 * * `Impact` - Impact
 * * `AikidoSecurity` - AikidoSecurity
 * * `Alguna` - Alguna
 * * `Anthropic` - Anthropic
 * * `Appwrite` - Appwrite
 * * `BlandAI` - BlandAI
 * * `BrowseAI` - BrowseAI
 * * `BrowserUse` - BrowserUse
 * * `ChartHop` - ChartHop
 * * `Cody` - Cody
 * * `Cursor` - Cursor
 * * `Decagon` - Decagon
 * * `Deepgram` - Deepgram
 * * `ElevenLabs` - ElevenLabs
 * * `Harvey` - Harvey
 * * `Hyperspell` - Hyperspell
 * * `Langfuse` - Langfuse
 * * `LingoDev` - LingoDev
 * * `M3ter` - M3ter
 * * `Maxio` - Maxio
 * * `Metorial` - Metorial
 * * `OpenRouter` - OpenRouter
 * * `TogetherAI` - TogetherAI
 * * `Vapi` - Vapi
 * * `Vespa` - Vespa
 * * `Writesonic` - Writesonic
 */
export type ExternalDataSourceTypeEnumApi =
    (typeof ExternalDataSourceTypeEnumApi)[keyof typeof ExternalDataSourceTypeEnumApi]

export const ExternalDataSourceTypeEnumApi = {
    Ashby: 'Ashby',
    Supabase: 'Supabase',
    CustomerIO: 'CustomerIO',
    Github: 'Github',
    Stripe: 'Stripe',
    Hubspot: 'Hubspot',
    Postgres: 'Postgres',
    Zendesk: 'Zendesk',
    Snowflake: 'Snowflake',
    Salesforce: 'Salesforce',
    MySQL: 'MySQL',
    MongoDB: 'MongoDB',
    Mssql: 'MSSQL',
    Vitally: 'Vitally',
    BigQuery: 'BigQuery',
    Chargebee: 'Chargebee',
    Clerk: 'Clerk',
    GoogleAds: 'GoogleAds',
    GoogleSearchConsole: 'GoogleSearchConsole',
    TemporalIO: 'TemporalIO',
    DoIt: 'DoIt',
    GoogleSheets: 'GoogleSheets',
    MetaAds: 'MetaAds',
    Klaviyo: 'Klaviyo',
    Mailchimp: 'Mailchimp',
    Braze: 'Braze',
    Mailjet: 'Mailjet',
    Redshift: 'Redshift',
    Polar: 'Polar',
    RevenueCat: 'RevenueCat',
    LinkedinAds: 'LinkedinAds',
    RedditAds: 'RedditAds',
    TikTokAds: 'TikTokAds',
    BingAds: 'BingAds',
    Shopify: 'Shopify',
    Attio: 'Attio',
    SnapchatAds: 'SnapchatAds',
    Linear: 'Linear',
    Intercom: 'Intercom',
    Amplitude: 'Amplitude',
    Mixpanel: 'Mixpanel',
    Jira: 'Jira',
    ActiveCampaign: 'ActiveCampaign',
    Marketo: 'Marketo',
    Adjust: 'Adjust',
    AppsFlyer: 'AppsFlyer',
    Freshdesk: 'Freshdesk',
    GoogleAnalytics: 'GoogleAnalytics',
    Pipedrive: 'Pipedrive',
    SendGrid: 'SendGrid',
    Slack: 'Slack',
    PagerDuty: 'PagerDuty',
    Asana: 'Asana',
    Notion: 'Notion',
    Airtable: 'Airtable',
    Greenhouse: 'Greenhouse',
    BambooHR: 'BambooHR',
    Lever: 'Lever',
    GitLab: 'GitLab',
    Datadog: 'Datadog',
    Sentry: 'Sentry',
    Pendo: 'Pendo',
    FullStory: 'FullStory',
    AmazonAds: 'AmazonAds',
    PinterestAds: 'PinterestAds',
    AppleSearchAds: 'AppleSearchAds',
    QuickBooks: 'QuickBooks',
    Xero: 'Xero',
    NetSuite: 'NetSuite',
    WooCommerce: 'WooCommerce',
    BigCommerce: 'BigCommerce',
    PayPal: 'PayPal',
    Square: 'Square',
    Zoom: 'Zoom',
    Trello: 'Trello',
    Monday: 'Monday',
    ClickUp: 'ClickUp',
    Confluence: 'Confluence',
    Recurly: 'Recurly',
    SalesLoft: 'SalesLoft',
    Outreach: 'Outreach',
    Gong: 'Gong',
    Calendly: 'Calendly',
    Typeform: 'Typeform',
    Iterable: 'Iterable',
    ZohoCRM: 'ZohoCRM',
    Close: 'Close',
    Oracle: 'Oracle',
    DynamoDB: 'DynamoDB',
    Elasticsearch: 'Elasticsearch',
    Kafka: 'Kafka',
    LaunchDarkly: 'LaunchDarkly',
    Braintree: 'Braintree',
    Recharge: 'Recharge',
    HelpScout: 'HelpScout',
    Gorgias: 'Gorgias',
    Instagram: 'Instagram',
    YouTubeAnalytics: 'YouTubeAnalytics',
    FacebookPages: 'FacebookPages',
    TwitterAds: 'TwitterAds',
    Workday: 'Workday',
    ServiceNow: 'ServiceNow',
    Pardot: 'Pardot',
    Copper: 'Copper',
    Front: 'Front',
    ChartMogul: 'ChartMogul',
    Zuora: 'Zuora',
    Paddle: 'Paddle',
    CircleCI: 'CircleCI',
    CockroachDB: 'CockroachDB',
    Firebase: 'Firebase',
    AzureBlob: 'AzureBlob',
    GoogleDrive: 'GoogleDrive',
    OneDrive: 'OneDrive',
    SharePoint: 'SharePoint',
    Box: 'Box',
    Sftp: 'SFTP',
    MicrosoftTeams: 'MicrosoftTeams',
    Aircall: 'Aircall',
    Webflow: 'Webflow',
    Okta: 'Okta',
    Auth0: 'Auth0',
    Productboard: 'Productboard',
    Smartsheet: 'Smartsheet',
    Wrike: 'Wrike',
    Plaid: 'Plaid',
    SurveyMonkey: 'SurveyMonkey',
    Eventbrite: 'Eventbrite',
    RingCentral: 'RingCentral',
    Twilio: 'Twilio',
    Freshsales: 'Freshsales',
    Shortcut: 'Shortcut',
    ConvertKit: 'ConvertKit',
    Drip: 'Drip',
    CampaignMonitor: 'CampaignMonitor',
    MailerLite: 'MailerLite',
    Omnisend: 'Omnisend',
    Brevo: 'Brevo',
    Postmark: 'Postmark',
    Granola: 'Granola',
    BuildBetter: 'BuildBetter',
    Convex: 'Convex',
    ClickHouse: 'ClickHouse',
    Plain: 'Plain',
    Resend: 'Resend',
    PgAnalyze: 'PgAnalyze',
    WorkOS: 'WorkOS',
    AmazonS3: 'AmazonS3',
    GoogleCloudStorage: 'GoogleCloudStorage',
    Databricks: 'Databricks',
    Dynamics365: 'Dynamics365',
    SalesforceMarketingCloud: 'SalesforceMarketingCloud',
    Db2: 'Db2',
    Heap: 'Heap',
    AdobeAnalytics: 'AdobeAnalytics',
    Matomo: 'Matomo',
    Optimizely: 'Optimizely',
    Adyen: 'Adyen',
    GoCardless: 'GoCardless',
    Mollie: 'Mollie',
    CheckoutCom: 'CheckoutCom',
    Branch: 'Branch',
    Criteo: 'Criteo',
    Outbrain: 'Outbrain',
    Taboola: 'Taboola',
    AdRoll: 'AdRoll',
    DisplayVideo360: 'DisplayVideo360',
    GoogleAdManager: 'GoogleAdManager',
    CampaignManager360: 'CampaignManager360',
    SearchAds360: 'SearchAds360',
    AdobeCommerce: 'AdobeCommerce',
    AmazonSellingPartner: 'AmazonSellingPartner',
    Ebay: 'Ebay',
    Commercetools: 'Commercetools',
    LightspeedRetail: 'LightspeedRetail',
    ShipStation: 'ShipStation',
    ConstantContact: 'ConstantContact',
    Mailgun: 'Mailgun',
    Eloqua: 'Eloqua',
    Sailthru: 'Sailthru',
    Ortto: 'Ortto',
    Attentive: 'Attentive',
    Kustomer: 'Kustomer',
    Dixa: 'Dixa',
    Gladly: 'Gladly',
    Qualtrics: 'Qualtrics',
    Delighted: 'Delighted',
    AzureDevOps: 'AzureDevOps',
    Rollbar: 'Rollbar',
    Opsgenie: 'Opsgenie',
    IncidentIo: 'IncidentIo',
    Pingdom: 'Pingdom',
    Cloudflare: 'Cloudflare',
    CosmosDB: 'CosmosDB',
    PlanetScale: 'PlanetScale',
    SapHana: 'SapHana',
    Rippling: 'Rippling',
    HiBob: 'HiBob',
    Personio: 'Personio',
    Deel: 'Deel',
    AdpWorkforceNow: 'AdpWorkforceNow',
    Paylocity: 'Paylocity',
    Gusto: 'Gusto',
    CultureAmp: 'CultureAmp',
    Lattice: 'Lattice',
    SageIntacct: 'SageIntacct',
    FreshBooks: 'FreshBooks',
    Expensify: 'Expensify',
    Ramp: 'Ramp',
    Brex: 'Brex',
    Coupa: 'Coupa',
    SapConcur: 'SapConcur',
    Apollo: 'Apollo',
    Crunchbase: 'Crunchbase',
    ZoomInfo: 'ZoomInfo',
    Clari: 'Clari',
    Chorus: 'Chorus',
    Coda: 'Coda',
    Guru: 'Guru',
    Dropbox: 'Dropbox',
    Docusign: 'Docusign',
    PandaDoc: 'PandaDoc',
    SapErp: 'SapErp',
    SapSuccessFactors: 'SapSuccessFactors',
    OracleEbs: 'OracleEbs',
    OracleFusion: 'OracleFusion',
    AmazonSNS: 'AmazonSNS',
    AmazonEventBridge: 'AmazonEventBridge',
    AmazonSQS: 'AmazonSQS',
    AmazonKinesis: 'AmazonKinesis',
    AmazonCloudWatch: 'AmazonCloudWatch',
    OpenAIAds: 'OpenAIAds',
    OneHundredMs: 'OneHundredMs',
    SevenShifts: 'SevenShifts',
    AcuityScheduling: 'AcuityScheduling',
    AgileCRM: 'AgileCRM',
    Aha: 'Aha',
    Airbyte: 'Airbyte',
    Akeneo: 'Akeneo',
    Algolia: 'Algolia',
    AlpacaBrokerAPI: 'AlpacaBrokerAPI',
    ApifyDataset: 'ApifyDataset',
    Appcues: 'Appcues',
    Appfigures: 'Appfigures',
    Appfollow: 'Appfollow',
    Apptivo: 'Apptivo',
    AssemblyAI: 'AssemblyAI',
    Awin: 'Awin',
    AwsCloudTrail: 'AwsCloudTrail',
    AzureTableStorage: 'AzureTableStorage',
    Babelforce: 'Babelforce',
    Basecamp: 'Basecamp',
    Beamer: 'Beamer',
    BigMailer: 'BigMailer',
    Bluetally: 'Bluetally',
    BoldSign: 'BoldSign',
    BreezyHR: 'BreezyHR',
    Bugsnag: 'Bugsnag',
    Buildkite: 'Buildkite',
    Bunny: 'Bunny',
    Buzzsprout: 'Buzzsprout',
    CalCom: 'CalCom',
    CallRail: 'CallRail',
    Campayn: 'Campayn',
    Canny: 'Canny',
    CapsuleCRM: 'CapsuleCRM',
    CaptainData: 'CaptainData',
    CartCom: 'CartCom',
    CastorEDC: 'CastorEDC',
    Chameleon: 'Chameleon',
    Chargedesk: 'Chargedesk',
    Chargify: 'Chargify',
    Chift: 'Chift',
    Churnkey: 'Churnkey',
    Cin7: 'Cin7',
    CiscoMeraki: 'CiscoMeraki',
    Clazar: 'Clazar',
    Clockify: 'Clockify',
    Clockodo: 'Clockodo',
    Cloudbeds: 'Cloudbeds',
    Coassemble: 'Coassemble',
    Codefresh: 'Codefresh',
    Concord: 'Concord',
    ConfigCat: 'ConfigCat',
    Couchbase: 'Couchbase',
    Curve: 'Curve',
    Customerly: 'Customerly',
    Datascope: 'Datascope',
    Dbt: 'Dbt',
    Deputy: 'Deputy',
    DevinAI: 'DevinAI',
    Docuseal: 'Docuseal',
    Dolibarr: 'Dolibarr',
    Dremio: 'Dremio',
    DropboxSign: 'DropboxSign',
    Dwolla: 'Dwolla',
    EConomic: 'EConomic',
    Easypost: 'Easypost',
    Easypromos: 'Easypromos',
    Elasticemail: 'Elasticemail',
    EmailOctopus: 'EmailOctopus',
    EmploymentHero: 'EmploymentHero',
    Encharge: 'Encharge',
    Eventee: 'Eventee',
    Eventzilla: 'Eventzilla',
    Everhour: 'Everhour',
    EZOfficeInventory: 'EZOfficeInventory',
    Factorial: 'Factorial',
    Fastbill: 'Fastbill',
    Fastly: 'Fastly',
    Fauna: 'Fauna',
    Feishu: 'Feishu',
    Fillout: 'Fillout',
    Finage: 'Finage',
    Firebolt: 'Firebolt',
    FireHydrant: 'FireHydrant',
    Fleetio: 'Fleetio',
    Flexmail: 'Flexmail',
    Flexport: 'Flexport',
    FloatApp: 'FloatApp',
    Flowlu: 'Flowlu',
    Formbricks: 'Formbricks',
    FreeAgent: 'FreeAgent',
    Freightview: 'Freightview',
    Freshcaller: 'Freshcaller',
    Freshchat: 'Freshchat',
    Freshservice: 'Freshservice',
    Fulcrum: 'Fulcrum',
    GainsightPx: 'GainsightPx',
    GitBook: 'GitBook',
    Glassfrog: 'Glassfrog',
    Goldcast: 'Goldcast',
    GoLogin: 'GoLogin',
    Grafana: 'Grafana',
    GreytHr: 'GreytHr',
    Gridly: 'Gridly',
    Harness: 'Harness',
    Height: 'Height',
    Hellobaton: 'Hellobaton',
    HighLevel: 'HighLevel',
    HoorayHR: 'HoorayHR',
    Hubplanner: 'Hubplanner',
    Humanitix: 'Humanitix',
    Huntr: 'Huntr',
    Inflowinventory: 'Inflowinventory',
    InforNexus: 'InforNexus',
    Insightful: 'Insightful',
    Insightly: 'Insightly',
    Instantly: 'Instantly',
    Instatus: 'Instatus',
    Intruder: 'Intruder',
    Invoiced: 'Invoiced',
    Invoiceninja: 'Invoiceninja',
    JamfPro: 'JamfPro',
    JobNimbus: 'JobNimbus',
    Jotform: 'Jotform',
    JudgeMeReviews: 'JudgeMeReviews',
    JustCall: 'JustCall',
    JustSift: 'JustSift',
    K6Cloud: 'K6Cloud',
    Katana: 'Katana',
    Keka: 'Keka',
    Kisi: 'Kisi',
    Kissmetrics: 'Kissmetrics',
    Klarna: 'Klarna',
    Klaus: 'Klaus',
    Lago: 'Lago',
    Leadfeeder: 'Leadfeeder',
    Lemlist: 'Lemlist',
    LessAnnoyingCRM: 'LessAnnoyingCRM',
    LinkedinPages: 'LinkedinPages',
    Linkrunner: 'Linkrunner',
    Linnworks: 'Linnworks',
    Lob: 'Lob',
    Lokalise: 'Lokalise',
    Looker: 'Looker',
    Luma: 'Luma',
    MailerSend: 'MailerSend',
    Mailosaur: 'Mailosaur',
    Mailtrap: 'Mailtrap',
    Mantle: 'Mantle',
    Mention: 'Mention',
    MercadoAds: 'MercadoAds',
    Merge: 'Merge',
    Metabase: 'Metabase',
    Metricool: 'Metricool',
    MicrosoftDataverse: 'MicrosoftDataverse',
    MicrosoftEntraId: 'MicrosoftEntraId',
    MicrosoftLists: 'MicrosoftLists',
    Miro: 'Miro',
    Missive: 'Missive',
    MixMax: 'MixMax',
    Mode: 'Mode',
    Mux: 'Mux',
    MyHours: 'MyHours',
    N8n: 'N8n',
    Navan: 'Navan',
    NebiusAI: 'NebiusAI',
    Nexiopay: 'Nexiopay',
    NinjaOneRMM: 'NinjaOneRMM',
    NoCRM: 'NoCRM',
    NorthpassLMS: 'NorthpassLMS',
    Nutshell: 'Nutshell',
    Nylas: 'Nylas',
    Oncehub: 'Oncehub',
    Onepagecrm: 'Onepagecrm',
    OneSignal: 'OneSignal',
    Onfleet: 'Onfleet',
    OpinionStage: 'OpinionStage',
    OPUSWatch: 'OPUSWatch',
    Orb: 'Orb',
    Orbit: 'Orbit',
    Oura: 'Oura',
    Oveit: 'Oveit',
    PabblySubscriptionsBilling: 'PabblySubscriptionsBilling',
    Paperform: 'Paperform',
    Papersign: 'Papersign',
    Partnerize: 'Partnerize',
    PartnerStack: 'PartnerStack',
    PayFit: 'PayFit',
    Paystack: 'Paystack',
    Pennylane: 'Pennylane',
    Perk: 'Perk',
    PersistIq: 'PersistIq',
    Persona: 'Persona',
    Phyllo: 'Phyllo',
    Picqer: 'Picqer',
    Pipeliner: 'Pipeliner',
    PivotalTracker: 'PivotalTracker',
    Piwik: 'Piwik',
    Planhat: 'Planhat',
    Plausible: 'Plausible',
    Poplar: 'Poplar',
    PrestaShop: 'PrestaShop',
    Pretix: 'Pretix',
    Primetric: 'Primetric',
    Printify: 'Printify',
    Productive: 'Productive',
    Pylon: 'Pylon',
    Qonto: 'Qonto',
    Qualaroo: 'Qualaroo',
    Railz: 'Railz',
    RDStationMarketing: 'RDStationMarketing',
    Recruitee: 'Recruitee',
    Reddit: 'Reddit',
    ReferralHero: 'ReferralHero',
    RentCast: 'RentCast',
    Repairshopr: 'Repairshopr',
    ReplyIo: 'ReplyIo',
    RetailExpress: 'RetailExpress',
    Retently: 'Retently',
    RevolutMerchant: 'RevolutMerchant',
    RocketChat: 'RocketChat',
    Rocketlane: 'Rocketlane',
    Rootly: 'Rootly',
    Ruddr: 'Ruddr',
    SafetyCulture: 'SafetyCulture',
    SageHR: 'SageHR',
    Salesflare: 'Salesflare',
    SAPFieldglass: 'SAPFieldglass',
    SavvyCal: 'SavvyCal',
    Secoda: 'Secoda',
    Segment: 'Segment',
    Sendowl: 'Sendowl',
    SendPulse: 'SendPulse',
    Senseforce: 'Senseforce',
    Serpstat: 'Serpstat',
    Sharetribe: 'Sharetribe',
    Shippo: 'Shippo',
    ShopWired: 'ShopWired',
    Shortio: 'Shortio',
    Shutterstock: 'Shutterstock',
    SigmaComputing: 'SigmaComputing',
    SignNow: 'SignNow',
    SimpleCast: 'SimpleCast',
    Simplesat: 'Simplesat',
    Smaily: 'Smaily',
    SmartEngage: 'SmartEngage',
    Smartreach: 'Smartreach',
    Smartwaiver: 'Smartwaiver',
    SolarwindsServiceDesk: 'SolarwindsServiceDesk',
    SonarCloud: 'SonarCloud',
    SparkPost: 'SparkPost',
    SplitIo: 'SplitIo',
    SpotifyAds: 'SpotifyAds',
    SpotlerCRM: 'SpotlerCRM',
    Squarespace: 'Squarespace',
    Statsig: 'Statsig',
    Statuspage: 'Statuspage',
    Stigg: 'Stigg',
    Strava: 'Strava',
    SurveySparrow: 'SurveySparrow',
    Survicate: 'Survicate',
    Svix: 'Svix',
    Systeme: 'Systeme',
    Tavus: 'Tavus',
    Teamtailor: 'Teamtailor',
    Teamwork: 'Teamwork',
    Tempo: 'Tempo',
    Testrail: 'Testrail',
    Thinkific: 'Thinkific',
    ThinkificCourses: 'ThinkificCourses',
    ThriveLearning: 'ThriveLearning',
    Ticketmaster: 'Ticketmaster',
    TicketTailor: 'TicketTailor',
    TickTick: 'TickTick',
    Timely: 'Timely',
    Tinyemail: 'Tinyemail',
    Todoist: 'Todoist',
    Toggl: 'Toggl',
    TrackPMS: 'TrackPMS',
    Tremendous: 'Tremendous',
    TrustPilot: 'TrustPilot',
    Twitter: 'Twitter',
    TyntecSMS: 'TyntecSMS',
    Unleash: 'Unleash',
    UpPromote: 'UpPromote',
    Uptick: 'Uptick',
    Uservoice: 'Uservoice',
    Vantage: 'Vantage',
    Veeqo: 'Veeqo',
    Vercel: 'Vercel',
    VismaEconomic: 'VismaEconomic',
    Vwo: 'VWO',
    Waiteraid: 'Waiteraid',
    Wasabi: 'Wasabi',
    WhenIWork: 'WhenIWork',
    Wordpress: 'Wordpress',
    Workable: 'Workable',
    Workflowmax: 'Workflowmax',
    Workramp: 'Workramp',
    Wufoo: 'Wufoo',
    Xsolla: 'Xsolla',
    YandexMetrica: 'YandexMetrica',
    Yotpo: 'Yotpo',
    Ynab: 'Ynab',
    Younium: 'Younium',
    YouSign: 'YouSign',
    YoutubeData: 'YoutubeData',
    ZapierSupportedStorage: 'ZapierSupportedStorage',
    ZapSign: 'ZapSign',
    ZendeskSell: 'ZendeskSell',
    ZendeskSunshine: 'ZendeskSunshine',
    Zenefits: 'Zenefits',
    Zenloop: 'Zenloop',
    ZohoAnalytics: 'ZohoAnalytics',
    ZohoBigin: 'ZohoBigin',
    ZohoBilling: 'ZohoBilling',
    ZohoBooks: 'ZohoBooks',
    ZohoCampaign: 'ZohoCampaign',
    ZohoDesk: 'ZohoDesk',
    ZohoExpense: 'ZohoExpense',
    ZohoInventory: 'ZohoInventory',
    ZohoInvoice: 'ZohoInvoice',
    ZonkaFeedback: 'ZonkaFeedback',
    AlphaVantage: 'AlphaVantage',
    Aviationstack: 'Aviationstack',
    Bitly: 'Bitly',
    Blogger: 'Blogger',
    Breezometer: 'Breezometer',
    CareQualityCommission: 'CareQualityCommission',
    Cimis: 'Cimis',
    CoinApi: 'CoinApi',
    CoinGecko: 'CoinGecko',
    CoinMarketCap: 'CoinMarketCap',
    DingConnect: 'DingConnect',
    Dockerhub: 'Dockerhub',
    ExchangeRatesApi: 'ExchangeRatesApi',
    FinancialModelling: 'FinancialModelling',
    Finnhub: 'Finnhub',
    Finnworlds: 'Finnworlds',
    Giphy: 'Giphy',
    Gmail: 'Gmail',
    GNews: 'GNews',
    GoogleCalendar: 'GoogleCalendar',
    GoogleClassroom: 'GoogleClassroom',
    GoogleDirectory: 'GoogleDirectory',
    GoogleForms: 'GoogleForms',
    GooglePageSpeedInsights: 'GooglePageSpeedInsights',
    GoogleTasks: 'GoogleTasks',
    GoogleWebfonts: 'GoogleWebfonts',
    GoogleWorkspaceAdminReports: 'GoogleWorkspaceAdminReports',
    HuggingFace: 'HuggingFace',
    IlluminaBasespace: 'IlluminaBasespace',
    Imagga: 'Imagga',
    Interzoid: 'Interzoid',
    IP2Whois: 'IP2Whois',
    Kyve: 'KYVE',
    Marketstack: 'Marketstack',
    Mendeley: 'Mendeley',
    Nasa: 'Nasa',
    NewYorkTimes: 'NewYorkTimes',
    NewsApi: 'NewsApi',
    NewsData: 'NewsData',
    OpenDataDc: 'OpenDataDc',
    OpenExchangeRates: 'OpenExchangeRates',
    OpenAQ: 'OpenAQ',
    OpenFDA: 'OpenFDA',
    OpenWeather: 'OpenWeather',
    Outlook: 'Outlook',
    Perigon: 'Perigon',
    Pexels: 'Pexels',
    Pocket: 'Pocket',
    Polygon: 'Polygon',
    PyPI: 'PyPI',
    Recreation: 'Recreation',
    RKICovid: 'RKICovid',
    Rss: 'Rss',
    SimFin: 'SimFin',
    StockData: 'StockData',
    Guardian: 'Guardian',
    TMDb: 'TMDb',
    TVMaze: 'TVMaze',
    TwelveData: 'TwelveData',
    Ubidots: 'Ubidots',
    USCensus: 'USCensus',
    Watchmode: 'Watchmode',
    WikipediaPageviews: 'WikipediaPageviews',
    YahooFinance: 'YahooFinance',
    Clarifai: 'Clarifai',
    Adapty: 'Adapty',
    Braintrust: 'Braintrust',
    StreamElements: 'StreamElements',
    Streamlabs: 'Streamlabs',
    Datorama: 'Datorama',
    Ahrefs: 'Ahrefs',
    Lightfield: 'Lightfield',
    Appstack: 'Appstack',
    Razorpay: 'Razorpay',
    Neon: 'Neon',
    NewRelic: 'NewRelic',
    Custom: 'Custom',
    Tile38: 'Tile38',
    Chatwoot: 'Chatwoot',
    Sanity: 'Sanity',
    Metronome: 'Metronome',
    Jobber: 'Jobber',
    Knock: 'Knock',
    Leexi: 'Leexi',
    Rb2b: 'RB2B',
    Superwall: 'Superwall',
    Liana: 'Liana',
    TawkTo: 'TawkTo',
    Hightouch: 'Hightouch',
    LemonSqueezy: 'LemonSqueezy',
    Ikas: 'Ikas',
    Talkwalker: 'Talkwalker',
    NextdoorAds: 'NextdoorAds',
    AppLovin: 'AppLovin',
    Baserow: 'Baserow',
    Plunk: 'Plunk',
    Dub: 'Dub',
    AirOps: 'AirOps',
    Podium: 'Podium',
    Loops: 'Loops',
    Redis: 'Redis',
    Mercury: 'Mercury',
    Gojiberry: 'Gojiberry',
    Teachable: 'Teachable',
    PeecAI: 'PeecAI',
    Healthchecks: 'Healthchecks',
    Impact: 'Impact',
    AikidoSecurity: 'AikidoSecurity',
    Alguna: 'Alguna',
    Anthropic: 'Anthropic',
    Appwrite: 'Appwrite',
    BlandAI: 'BlandAI',
    BrowseAI: 'BrowseAI',
    BrowserUse: 'BrowserUse',
    ChartHop: 'ChartHop',
    Cody: 'Cody',
    Cursor: 'Cursor',
    Decagon: 'Decagon',
    Deepgram: 'Deepgram',
    ElevenLabs: 'ElevenLabs',
    Harvey: 'Harvey',
    Hyperspell: 'Hyperspell',
    Langfuse: 'Langfuse',
    LingoDev: 'LingoDev',
    M3ter: 'M3ter',
    Maxio: 'Maxio',
    Metorial: 'Metorial',
    OpenRouter: 'OpenRouter',
    TogetherAI: 'TogetherAI',
    Vapi: 'Vapi',
    Vespa: 'Vespa',
    Writesonic: 'Writesonic',
} as const

/**
 * * `warehouse` - warehouse
 * * `direct` - direct
 */
export type AccessMethodEnumApi = (typeof AccessMethodEnumApi)[keyof typeof AccessMethodEnumApi]

export const AccessMethodEnumApi = {
    Warehouse: 'warehouse',
    Direct: 'direct',
} as const

/**
 * * `duckdb` - duckdb
 * * `postgres` - postgres
 * * `mysql` - mysql
 * * `snowflake` - snowflake
 */
export type EngineEnumApi = (typeof EngineEnumApi)[keyof typeof EngineEnumApi]

export const EngineEnumApi = {
    Duckdb: 'duckdb',
    Postgres: 'postgres',
    Mysql: 'mysql',
    Snowflake: 'snowflake',
} as const

export interface ExternalDataSourceRevenueAnalyticsConfigApi {
    enabled?: boolean
    include_invoiceless_charges?: boolean
}

export type ExternalDataSourceSerializersApiSchemasItem = { [key: string]: unknown }

/**
 * Mixin for serializers to add user access control fields
 */
export interface ExternalDataSourceSerializersApi {
    readonly id: string
    readonly created_at: string
    /** @nullable */
    readonly created_by: string | null
    /** How this source was created. Defaults to `api` on create when omitted. `web` for the in-app UI, `api` for direct API callers, `mcp` for agent/MCP tool calls. Ignored on update.
     *
     * * `web` - web
     * * `api` - api
     * * `mcp` - mcp */
    created_via?: CreatedViaEnumApi | null
    readonly status: string
    client_secret: string
    account_id: string
    readonly source_type: ExternalDataSourceTypeEnumApi
    /** @nullable */
    readonly latest_error: string | null
    /**
     * @maxLength 100
     * @nullable
     */
    prefix?: string | null
    /**
     * @maxLength 400
     * @nullable
     */
    description?: string | null
    readonly access_method: AccessMethodEnumApi
    /** Whether this synced source is also live-queryable via direct connection. Defaults to true for new sources; ignored for pure direct-query sources. */
    direct_query_enabled?: boolean
    /** Backend engine detected for the direct connection.
     *
     * * `duckdb` - duckdb
     * * `postgres` - postgres
     * * `mysql` - mysql
     * * `snowflake` - snowflake */
    readonly engine: EngineEnumApi | null
    /** @nullable */
    readonly last_run_at: string | null
    readonly schemas: readonly ExternalDataSourceSerializersApiSchemasItem[]
    job_inputs?: unknown
    readonly revenue_analytics_config: ExternalDataSourceRevenueAnalyticsConfigApi
    /**
     * The effective access level the user has for this object
     * @nullable
     */
    readonly user_access_level: string | null
    readonly supports_webhooks: boolean
    /** Whether this source supports per-column sync selection via `enabled_columns`. */
    readonly supports_column_selection: boolean
}

export interface PaginatedExternalDataSourceSerializersListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: ExternalDataSourceSerializersApi[]
}

/**
 * Connection credentials and a 'schemas' array. Keys depend on source_type.
 */
export type ExternalDataSourceCreateApiPayload = { [key: string]: unknown }

export interface ExternalDataSourceCreateApi {
    /** The source type (e.g. 'Postgres', 'Stripe').
     *
     * * `Ashby` - Ashby
     * * `Supabase` - Supabase
     * * `CustomerIO` - CustomerIO
     * * `Github` - Github
     * * `Stripe` - Stripe
     * * `Hubspot` - Hubspot
     * * `Postgres` - Postgres
     * * `Zendesk` - Zendesk
     * * `Snowflake` - Snowflake
     * * `Salesforce` - Salesforce
     * * `MySQL` - MySQL
     * * `MongoDB` - MongoDB
     * * `MSSQL` - MSSQL
     * * `Vitally` - Vitally
     * * `BigQuery` - BigQuery
     * * `Chargebee` - Chargebee
     * * `Clerk` - Clerk
     * * `GoogleAds` - GoogleAds
     * * `GoogleSearchConsole` - GoogleSearchConsole
     * * `TemporalIO` - TemporalIO
     * * `DoIt` - DoIt
     * * `GoogleSheets` - GoogleSheets
     * * `MetaAds` - MetaAds
     * * `Klaviyo` - Klaviyo
     * * `Mailchimp` - Mailchimp
     * * `Braze` - Braze
     * * `Mailjet` - Mailjet
     * * `Redshift` - Redshift
     * * `Polar` - Polar
     * * `RevenueCat` - RevenueCat
     * * `LinkedinAds` - LinkedinAds
     * * `RedditAds` - RedditAds
     * * `TikTokAds` - TikTokAds
     * * `BingAds` - BingAds
     * * `Shopify` - Shopify
     * * `Attio` - Attio
     * * `SnapchatAds` - SnapchatAds
     * * `Linear` - Linear
     * * `Intercom` - Intercom
     * * `Amplitude` - Amplitude
     * * `Mixpanel` - Mixpanel
     * * `Jira` - Jira
     * * `ActiveCampaign` - ActiveCampaign
     * * `Marketo` - Marketo
     * * `Adjust` - Adjust
     * * `AppsFlyer` - AppsFlyer
     * * `Freshdesk` - Freshdesk
     * * `GoogleAnalytics` - GoogleAnalytics
     * * `Pipedrive` - Pipedrive
     * * `SendGrid` - SendGrid
     * * `Slack` - Slack
     * * `PagerDuty` - PagerDuty
     * * `Asana` - Asana
     * * `Notion` - Notion
     * * `Airtable` - Airtable
     * * `Greenhouse` - Greenhouse
     * * `BambooHR` - BambooHR
     * * `Lever` - Lever
     * * `GitLab` - GitLab
     * * `Datadog` - Datadog
     * * `Sentry` - Sentry
     * * `Pendo` - Pendo
     * * `FullStory` - FullStory
     * * `AmazonAds` - AmazonAds
     * * `PinterestAds` - PinterestAds
     * * `AppleSearchAds` - AppleSearchAds
     * * `QuickBooks` - QuickBooks
     * * `Xero` - Xero
     * * `NetSuite` - NetSuite
     * * `WooCommerce` - WooCommerce
     * * `BigCommerce` - BigCommerce
     * * `PayPal` - PayPal
     * * `Square` - Square
     * * `Zoom` - Zoom
     * * `Trello` - Trello
     * * `Monday` - Monday
     * * `ClickUp` - ClickUp
     * * `Confluence` - Confluence
     * * `Recurly` - Recurly
     * * `SalesLoft` - SalesLoft
     * * `Outreach` - Outreach
     * * `Gong` - Gong
     * * `Calendly` - Calendly
     * * `Typeform` - Typeform
     * * `Iterable` - Iterable
     * * `ZohoCRM` - ZohoCRM
     * * `Close` - Close
     * * `Oracle` - Oracle
     * * `DynamoDB` - DynamoDB
     * * `Elasticsearch` - Elasticsearch
     * * `Kafka` - Kafka
     * * `LaunchDarkly` - LaunchDarkly
     * * `Braintree` - Braintree
     * * `Recharge` - Recharge
     * * `HelpScout` - HelpScout
     * * `Gorgias` - Gorgias
     * * `Instagram` - Instagram
     * * `YouTubeAnalytics` - YouTubeAnalytics
     * * `FacebookPages` - FacebookPages
     * * `TwitterAds` - TwitterAds
     * * `Workday` - Workday
     * * `ServiceNow` - ServiceNow
     * * `Pardot` - Pardot
     * * `Copper` - Copper
     * * `Front` - Front
     * * `ChartMogul` - ChartMogul
     * * `Zuora` - Zuora
     * * `Paddle` - Paddle
     * * `CircleCI` - CircleCI
     * * `CockroachDB` - CockroachDB
     * * `Firebase` - Firebase
     * * `AzureBlob` - AzureBlob
     * * `GoogleDrive` - GoogleDrive
     * * `OneDrive` - OneDrive
     * * `SharePoint` - SharePoint
     * * `Box` - Box
     * * `SFTP` - SFTP
     * * `MicrosoftTeams` - MicrosoftTeams
     * * `Aircall` - Aircall
     * * `Webflow` - Webflow
     * * `Okta` - Okta
     * * `Auth0` - Auth0
     * * `Productboard` - Productboard
     * * `Smartsheet` - Smartsheet
     * * `Wrike` - Wrike
     * * `Plaid` - Plaid
     * * `SurveyMonkey` - SurveyMonkey
     * * `Eventbrite` - Eventbrite
     * * `RingCentral` - RingCentral
     * * `Twilio` - Twilio
     * * `Freshsales` - Freshsales
     * * `Shortcut` - Shortcut
     * * `ConvertKit` - ConvertKit
     * * `Drip` - Drip
     * * `CampaignMonitor` - CampaignMonitor
     * * `MailerLite` - MailerLite
     * * `Omnisend` - Omnisend
     * * `Brevo` - Brevo
     * * `Postmark` - Postmark
     * * `Granola` - Granola
     * * `BuildBetter` - BuildBetter
     * * `Convex` - Convex
     * * `ClickHouse` - ClickHouse
     * * `Plain` - Plain
     * * `Resend` - Resend
     * * `PgAnalyze` - PgAnalyze
     * * `WorkOS` - WorkOS
     * * `AmazonS3` - AmazonS3
     * * `GoogleCloudStorage` - GoogleCloudStorage
     * * `Databricks` - Databricks
     * * `Dynamics365` - Dynamics365
     * * `SalesforceMarketingCloud` - SalesforceMarketingCloud
     * * `Db2` - Db2
     * * `Heap` - Heap
     * * `AdobeAnalytics` - AdobeAnalytics
     * * `Matomo` - Matomo
     * * `Optimizely` - Optimizely
     * * `Adyen` - Adyen
     * * `GoCardless` - GoCardless
     * * `Mollie` - Mollie
     * * `CheckoutCom` - CheckoutCom
     * * `Branch` - Branch
     * * `Criteo` - Criteo
     * * `Outbrain` - Outbrain
     * * `Taboola` - Taboola
     * * `AdRoll` - AdRoll
     * * `DisplayVideo360` - DisplayVideo360
     * * `GoogleAdManager` - GoogleAdManager
     * * `CampaignManager360` - CampaignManager360
     * * `SearchAds360` - SearchAds360
     * * `AdobeCommerce` - AdobeCommerce
     * * `AmazonSellingPartner` - AmazonSellingPartner
     * * `Ebay` - Ebay
     * * `Commercetools` - Commercetools
     * * `LightspeedRetail` - LightspeedRetail
     * * `ShipStation` - ShipStation
     * * `ConstantContact` - ConstantContact
     * * `Mailgun` - Mailgun
     * * `Eloqua` - Eloqua
     * * `Sailthru` - Sailthru
     * * `Ortto` - Ortto
     * * `Attentive` - Attentive
     * * `Kustomer` - Kustomer
     * * `Dixa` - Dixa
     * * `Gladly` - Gladly
     * * `Qualtrics` - Qualtrics
     * * `Delighted` - Delighted
     * * `AzureDevOps` - AzureDevOps
     * * `Rollbar` - Rollbar
     * * `Opsgenie` - Opsgenie
     * * `IncidentIo` - IncidentIo
     * * `Pingdom` - Pingdom
     * * `Cloudflare` - Cloudflare
     * * `CosmosDB` - CosmosDB
     * * `PlanetScale` - PlanetScale
     * * `SapHana` - SapHana
     * * `Rippling` - Rippling
     * * `HiBob` - HiBob
     * * `Personio` - Personio
     * * `Deel` - Deel
     * * `AdpWorkforceNow` - AdpWorkforceNow
     * * `Paylocity` - Paylocity
     * * `Gusto` - Gusto
     * * `CultureAmp` - CultureAmp
     * * `Lattice` - Lattice
     * * `SageIntacct` - SageIntacct
     * * `FreshBooks` - FreshBooks
     * * `Expensify` - Expensify
     * * `Ramp` - Ramp
     * * `Brex` - Brex
     * * `Coupa` - Coupa
     * * `SapConcur` - SapConcur
     * * `Apollo` - Apollo
     * * `Crunchbase` - Crunchbase
     * * `ZoomInfo` - ZoomInfo
     * * `Clari` - Clari
     * * `Chorus` - Chorus
     * * `Coda` - Coda
     * * `Guru` - Guru
     * * `Dropbox` - Dropbox
     * * `Docusign` - Docusign
     * * `PandaDoc` - PandaDoc
     * * `SapErp` - SapErp
     * * `SapSuccessFactors` - SapSuccessFactors
     * * `OracleEbs` - OracleEbs
     * * `OracleFusion` - OracleFusion
     * * `AmazonSNS` - AmazonSNS
     * * `AmazonEventBridge` - AmazonEventBridge
     * * `AmazonSQS` - AmazonSQS
     * * `AmazonKinesis` - AmazonKinesis
     * * `AmazonCloudWatch` - AmazonCloudWatch
     * * `OpenAIAds` - OpenAIAds
     * * `OneHundredMs` - OneHundredMs
     * * `SevenShifts` - SevenShifts
     * * `AcuityScheduling` - AcuityScheduling
     * * `AgileCRM` - AgileCRM
     * * `Aha` - Aha
     * * `Airbyte` - Airbyte
     * * `Akeneo` - Akeneo
     * * `Algolia` - Algolia
     * * `AlpacaBrokerAPI` - AlpacaBrokerAPI
     * * `ApifyDataset` - ApifyDataset
     * * `Appcues` - Appcues
     * * `Appfigures` - Appfigures
     * * `Appfollow` - Appfollow
     * * `Apptivo` - Apptivo
     * * `AssemblyAI` - AssemblyAI
     * * `Awin` - Awin
     * * `AwsCloudTrail` - AwsCloudTrail
     * * `AzureTableStorage` - AzureTableStorage
     * * `Babelforce` - Babelforce
     * * `Basecamp` - Basecamp
     * * `Beamer` - Beamer
     * * `BigMailer` - BigMailer
     * * `Bluetally` - Bluetally
     * * `BoldSign` - BoldSign
     * * `BreezyHR` - BreezyHR
     * * `Bugsnag` - Bugsnag
     * * `Buildkite` - Buildkite
     * * `Bunny` - Bunny
     * * `Buzzsprout` - Buzzsprout
     * * `CalCom` - CalCom
     * * `CallRail` - CallRail
     * * `Campayn` - Campayn
     * * `Canny` - Canny
     * * `CapsuleCRM` - CapsuleCRM
     * * `CaptainData` - CaptainData
     * * `CartCom` - CartCom
     * * `CastorEDC` - CastorEDC
     * * `Chameleon` - Chameleon
     * * `Chargedesk` - Chargedesk
     * * `Chargify` - Chargify
     * * `Chift` - Chift
     * * `Churnkey` - Churnkey
     * * `Cin7` - Cin7
     * * `CiscoMeraki` - CiscoMeraki
     * * `Clazar` - Clazar
     * * `Clockify` - Clockify
     * * `Clockodo` - Clockodo
     * * `Cloudbeds` - Cloudbeds
     * * `Coassemble` - Coassemble
     * * `Codefresh` - Codefresh
     * * `Concord` - Concord
     * * `ConfigCat` - ConfigCat
     * * `Couchbase` - Couchbase
     * * `Curve` - Curve
     * * `Customerly` - Customerly
     * * `Datascope` - Datascope
     * * `Dbt` - Dbt
     * * `Deputy` - Deputy
     * * `DevinAI` - DevinAI
     * * `Docuseal` - Docuseal
     * * `Dolibarr` - Dolibarr
     * * `Dremio` - Dremio
     * * `DropboxSign` - DropboxSign
     * * `Dwolla` - Dwolla
     * * `EConomic` - EConomic
     * * `Easypost` - Easypost
     * * `Easypromos` - Easypromos
     * * `Elasticemail` - Elasticemail
     * * `EmailOctopus` - EmailOctopus
     * * `EmploymentHero` - EmploymentHero
     * * `Encharge` - Encharge
     * * `Eventee` - Eventee
     * * `Eventzilla` - Eventzilla
     * * `Everhour` - Everhour
     * * `EZOfficeInventory` - EZOfficeInventory
     * * `Factorial` - Factorial
     * * `Fastbill` - Fastbill
     * * `Fastly` - Fastly
     * * `Fauna` - Fauna
     * * `Feishu` - Feishu
     * * `Fillout` - Fillout
     * * `Finage` - Finage
     * * `Firebolt` - Firebolt
     * * `FireHydrant` - FireHydrant
     * * `Fleetio` - Fleetio
     * * `Flexmail` - Flexmail
     * * `Flexport` - Flexport
     * * `FloatApp` - FloatApp
     * * `Flowlu` - Flowlu
     * * `Formbricks` - Formbricks
     * * `FreeAgent` - FreeAgent
     * * `Freightview` - Freightview
     * * `Freshcaller` - Freshcaller
     * * `Freshchat` - Freshchat
     * * `Freshservice` - Freshservice
     * * `Fulcrum` - Fulcrum
     * * `GainsightPx` - GainsightPx
     * * `GitBook` - GitBook
     * * `Glassfrog` - Glassfrog
     * * `Goldcast` - Goldcast
     * * `GoLogin` - GoLogin
     * * `Grafana` - Grafana
     * * `GreytHr` - GreytHr
     * * `Gridly` - Gridly
     * * `Harness` - Harness
     * * `Height` - Height
     * * `Hellobaton` - Hellobaton
     * * `HighLevel` - HighLevel
     * * `HoorayHR` - HoorayHR
     * * `Hubplanner` - Hubplanner
     * * `Humanitix` - Humanitix
     * * `Huntr` - Huntr
     * * `Inflowinventory` - Inflowinventory
     * * `InforNexus` - InforNexus
     * * `Insightful` - Insightful
     * * `Insightly` - Insightly
     * * `Instantly` - Instantly
     * * `Instatus` - Instatus
     * * `Intruder` - Intruder
     * * `Invoiced` - Invoiced
     * * `Invoiceninja` - Invoiceninja
     * * `JamfPro` - JamfPro
     * * `JobNimbus` - JobNimbus
     * * `Jotform` - Jotform
     * * `JudgeMeReviews` - JudgeMeReviews
     * * `JustCall` - JustCall
     * * `JustSift` - JustSift
     * * `K6Cloud` - K6Cloud
     * * `Katana` - Katana
     * * `Keka` - Keka
     * * `Kisi` - Kisi
     * * `Kissmetrics` - Kissmetrics
     * * `Klarna` - Klarna
     * * `Klaus` - Klaus
     * * `Lago` - Lago
     * * `Leadfeeder` - Leadfeeder
     * * `Lemlist` - Lemlist
     * * `LessAnnoyingCRM` - LessAnnoyingCRM
     * * `LinkedinPages` - LinkedinPages
     * * `Linkrunner` - Linkrunner
     * * `Linnworks` - Linnworks
     * * `Lob` - Lob
     * * `Lokalise` - Lokalise
     * * `Looker` - Looker
     * * `Luma` - Luma
     * * `MailerSend` - MailerSend
     * * `Mailosaur` - Mailosaur
     * * `Mailtrap` - Mailtrap
     * * `Mantle` - Mantle
     * * `Mention` - Mention
     * * `MercadoAds` - MercadoAds
     * * `Merge` - Merge
     * * `Metabase` - Metabase
     * * `Metricool` - Metricool
     * * `MicrosoftDataverse` - MicrosoftDataverse
     * * `MicrosoftEntraId` - MicrosoftEntraId
     * * `MicrosoftLists` - MicrosoftLists
     * * `Miro` - Miro
     * * `Missive` - Missive
     * * `MixMax` - MixMax
     * * `Mode` - Mode
     * * `Mux` - Mux
     * * `MyHours` - MyHours
     * * `N8n` - N8n
     * * `Navan` - Navan
     * * `NebiusAI` - NebiusAI
     * * `Nexiopay` - Nexiopay
     * * `NinjaOneRMM` - NinjaOneRMM
     * * `NoCRM` - NoCRM
     * * `NorthpassLMS` - NorthpassLMS
     * * `Nutshell` - Nutshell
     * * `Nylas` - Nylas
     * * `Oncehub` - Oncehub
     * * `Onepagecrm` - Onepagecrm
     * * `OneSignal` - OneSignal
     * * `Onfleet` - Onfleet
     * * `OpinionStage` - OpinionStage
     * * `OPUSWatch` - OPUSWatch
     * * `Orb` - Orb
     * * `Orbit` - Orbit
     * * `Oura` - Oura
     * * `Oveit` - Oveit
     * * `PabblySubscriptionsBilling` - PabblySubscriptionsBilling
     * * `Paperform` - Paperform
     * * `Papersign` - Papersign
     * * `Partnerize` - Partnerize
     * * `PartnerStack` - PartnerStack
     * * `PayFit` - PayFit
     * * `Paystack` - Paystack
     * * `Pennylane` - Pennylane
     * * `Perk` - Perk
     * * `PersistIq` - PersistIq
     * * `Persona` - Persona
     * * `Phyllo` - Phyllo
     * * `Picqer` - Picqer
     * * `Pipeliner` - Pipeliner
     * * `PivotalTracker` - PivotalTracker
     * * `Piwik` - Piwik
     * * `Planhat` - Planhat
     * * `Plausible` - Plausible
     * * `Poplar` - Poplar
     * * `PrestaShop` - PrestaShop
     * * `Pretix` - Pretix
     * * `Primetric` - Primetric
     * * `Printify` - Printify
     * * `Productive` - Productive
     * * `Pylon` - Pylon
     * * `Qonto` - Qonto
     * * `Qualaroo` - Qualaroo
     * * `Railz` - Railz
     * * `RDStationMarketing` - RDStationMarketing
     * * `Recruitee` - Recruitee
     * * `Reddit` - Reddit
     * * `ReferralHero` - ReferralHero
     * * `RentCast` - RentCast
     * * `Repairshopr` - Repairshopr
     * * `ReplyIo` - ReplyIo
     * * `RetailExpress` - RetailExpress
     * * `Retently` - Retently
     * * `RevolutMerchant` - RevolutMerchant
     * * `RocketChat` - RocketChat
     * * `Rocketlane` - Rocketlane
     * * `Rootly` - Rootly
     * * `Ruddr` - Ruddr
     * * `SafetyCulture` - SafetyCulture
     * * `SageHR` - SageHR
     * * `Salesflare` - Salesflare
     * * `SAPFieldglass` - SAPFieldglass
     * * `SavvyCal` - SavvyCal
     * * `Secoda` - Secoda
     * * `Segment` - Segment
     * * `Sendowl` - Sendowl
     * * `SendPulse` - SendPulse
     * * `Senseforce` - Senseforce
     * * `Serpstat` - Serpstat
     * * `Sharetribe` - Sharetribe
     * * `Shippo` - Shippo
     * * `ShopWired` - ShopWired
     * * `Shortio` - Shortio
     * * `Shutterstock` - Shutterstock
     * * `SigmaComputing` - SigmaComputing
     * * `SignNow` - SignNow
     * * `SimpleCast` - SimpleCast
     * * `Simplesat` - Simplesat
     * * `Smaily` - Smaily
     * * `SmartEngage` - SmartEngage
     * * `Smartreach` - Smartreach
     * * `Smartwaiver` - Smartwaiver
     * * `SolarwindsServiceDesk` - SolarwindsServiceDesk
     * * `SonarCloud` - SonarCloud
     * * `SparkPost` - SparkPost
     * * `SplitIo` - SplitIo
     * * `SpotifyAds` - SpotifyAds
     * * `SpotlerCRM` - SpotlerCRM
     * * `Squarespace` - Squarespace
     * * `Statsig` - Statsig
     * * `Statuspage` - Statuspage
     * * `Stigg` - Stigg
     * * `Strava` - Strava
     * * `SurveySparrow` - SurveySparrow
     * * `Survicate` - Survicate
     * * `Svix` - Svix
     * * `Systeme` - Systeme
     * * `Tavus` - Tavus
     * * `Teamtailor` - Teamtailor
     * * `Teamwork` - Teamwork
     * * `Tempo` - Tempo
     * * `Testrail` - Testrail
     * * `Thinkific` - Thinkific
     * * `ThinkificCourses` - ThinkificCourses
     * * `ThriveLearning` - ThriveLearning
     * * `Ticketmaster` - Ticketmaster
     * * `TicketTailor` - TicketTailor
     * * `TickTick` - TickTick
     * * `Timely` - Timely
     * * `Tinyemail` - Tinyemail
     * * `Todoist` - Todoist
     * * `Toggl` - Toggl
     * * `TrackPMS` - TrackPMS
     * * `Tremendous` - Tremendous
     * * `TrustPilot` - TrustPilot
     * * `Twitter` - Twitter
     * * `TyntecSMS` - TyntecSMS
     * * `Unleash` - Unleash
     * * `UpPromote` - UpPromote
     * * `Uptick` - Uptick
     * * `Uservoice` - Uservoice
     * * `Vantage` - Vantage
     * * `Veeqo` - Veeqo
     * * `Vercel` - Vercel
     * * `VismaEconomic` - VismaEconomic
     * * `VWO` - VWO
     * * `Waiteraid` - Waiteraid
     * * `Wasabi` - Wasabi
     * * `WhenIWork` - WhenIWork
     * * `Wordpress` - Wordpress
     * * `Workable` - Workable
     * * `Workflowmax` - Workflowmax
     * * `Workramp` - Workramp
     * * `Wufoo` - Wufoo
     * * `Xsolla` - Xsolla
     * * `YandexMetrica` - YandexMetrica
     * * `Yotpo` - Yotpo
     * * `Ynab` - Ynab
     * * `Younium` - Younium
     * * `YouSign` - YouSign
     * * `YoutubeData` - YoutubeData
     * * `ZapierSupportedStorage` - ZapierSupportedStorage
     * * `ZapSign` - ZapSign
     * * `ZendeskSell` - ZendeskSell
     * * `ZendeskSunshine` - ZendeskSunshine
     * * `Zenefits` - Zenefits
     * * `Zenloop` - Zenloop
     * * `ZohoAnalytics` - ZohoAnalytics
     * * `ZohoBigin` - ZohoBigin
     * * `ZohoBilling` - ZohoBilling
     * * `ZohoBooks` - ZohoBooks
     * * `ZohoCampaign` - ZohoCampaign
     * * `ZohoDesk` - ZohoDesk
     * * `ZohoExpense` - ZohoExpense
     * * `ZohoInventory` - ZohoInventory
     * * `ZohoInvoice` - ZohoInvoice
     * * `ZonkaFeedback` - ZonkaFeedback
     * * `AlphaVantage` - AlphaVantage
     * * `Aviationstack` - Aviationstack
     * * `Bitly` - Bitly
     * * `Blogger` - Blogger
     * * `Breezometer` - Breezometer
     * * `CareQualityCommission` - CareQualityCommission
     * * `Cimis` - Cimis
     * * `CoinApi` - CoinApi
     * * `CoinGecko` - CoinGecko
     * * `CoinMarketCap` - CoinMarketCap
     * * `DingConnect` - DingConnect
     * * `Dockerhub` - Dockerhub
     * * `ExchangeRatesApi` - ExchangeRatesApi
     * * `FinancialModelling` - FinancialModelling
     * * `Finnhub` - Finnhub
     * * `Finnworlds` - Finnworlds
     * * `Giphy` - Giphy
     * * `Gmail` - Gmail
     * * `GNews` - GNews
     * * `GoogleCalendar` - GoogleCalendar
     * * `GoogleClassroom` - GoogleClassroom
     * * `GoogleDirectory` - GoogleDirectory
     * * `GoogleForms` - GoogleForms
     * * `GooglePageSpeedInsights` - GooglePageSpeedInsights
     * * `GoogleTasks` - GoogleTasks
     * * `GoogleWebfonts` - GoogleWebfonts
     * * `GoogleWorkspaceAdminReports` - GoogleWorkspaceAdminReports
     * * `HuggingFace` - HuggingFace
     * * `IlluminaBasespace` - IlluminaBasespace
     * * `Imagga` - Imagga
     * * `Interzoid` - Interzoid
     * * `IP2Whois` - IP2Whois
     * * `KYVE` - KYVE
     * * `Marketstack` - Marketstack
     * * `Mendeley` - Mendeley
     * * `Nasa` - Nasa
     * * `NewYorkTimes` - NewYorkTimes
     * * `NewsApi` - NewsApi
     * * `NewsData` - NewsData
     * * `OpenDataDc` - OpenDataDc
     * * `OpenExchangeRates` - OpenExchangeRates
     * * `OpenAQ` - OpenAQ
     * * `OpenFDA` - OpenFDA
     * * `OpenWeather` - OpenWeather
     * * `Outlook` - Outlook
     * * `Perigon` - Perigon
     * * `Pexels` - Pexels
     * * `Pocket` - Pocket
     * * `Polygon` - Polygon
     * * `PyPI` - PyPI
     * * `Recreation` - Recreation
     * * `RKICovid` - RKICovid
     * * `Rss` - Rss
     * * `SimFin` - SimFin
     * * `StockData` - StockData
     * * `Guardian` - Guardian
     * * `TMDb` - TMDb
     * * `TVMaze` - TVMaze
     * * `TwelveData` - TwelveData
     * * `Ubidots` - Ubidots
     * * `USCensus` - USCensus
     * * `Watchmode` - Watchmode
     * * `WikipediaPageviews` - WikipediaPageviews
     * * `YahooFinance` - YahooFinance
     * * `Clarifai` - Clarifai
     * * `Adapty` - Adapty
     * * `Braintrust` - Braintrust
     * * `StreamElements` - StreamElements
     * * `Streamlabs` - Streamlabs
     * * `Datorama` - Datorama
     * * `Ahrefs` - Ahrefs
     * * `Lightfield` - Lightfield
     * * `Appstack` - Appstack
     * * `Razorpay` - Razorpay
     * * `Neon` - Neon
     * * `NewRelic` - NewRelic
     * * `Custom` - Custom
     * * `Tile38` - Tile38
     * * `Chatwoot` - Chatwoot
     * * `Sanity` - Sanity
     * * `Metronome` - Metronome
     * * `Jobber` - Jobber
     * * `Knock` - Knock
     * * `Leexi` - Leexi
     * * `RB2B` - RB2B
     * * `Superwall` - Superwall
     * * `Liana` - Liana
     * * `TawkTo` - TawkTo
     * * `Hightouch` - Hightouch
     * * `LemonSqueezy` - LemonSqueezy
     * * `Ikas` - Ikas
     * * `Talkwalker` - Talkwalker
     * * `NextdoorAds` - NextdoorAds
     * * `AppLovin` - AppLovin
     * * `Baserow` - Baserow
     * * `Plunk` - Plunk
     * * `Dub` - Dub
     * * `AirOps` - AirOps
     * * `Podium` - Podium
     * * `Loops` - Loops
     * * `Redis` - Redis
     * * `Mercury` - Mercury
     * * `Gojiberry` - Gojiberry
     * * `Teachable` - Teachable
     * * `PeecAI` - PeecAI
     * * `Healthchecks` - Healthchecks
     * * `Impact` - Impact
     * * `AikidoSecurity` - AikidoSecurity
     * * `Alguna` - Alguna
     * * `Anthropic` - Anthropic
     * * `Appwrite` - Appwrite
     * * `BlandAI` - BlandAI
     * * `BrowseAI` - BrowseAI
     * * `BrowserUse` - BrowserUse
     * * `ChartHop` - ChartHop
     * * `Cody` - Cody
     * * `Cursor` - Cursor
     * * `Decagon` - Decagon
     * * `Deepgram` - Deepgram
     * * `ElevenLabs` - ElevenLabs
     * * `Harvey` - Harvey
     * * `Hyperspell` - Hyperspell
     * * `Langfuse` - Langfuse
     * * `LingoDev` - LingoDev
     * * `M3ter` - M3ter
     * * `Maxio` - Maxio
     * * `Metorial` - Metorial
     * * `OpenRouter` - OpenRouter
     * * `TogetherAI` - TogetherAI
     * * `Vapi` - Vapi
     * * `Vespa` - Vespa
     * * `Writesonic` - Writesonic */
    source_type: ExternalDataSourceTypeEnumApi
    /** Connection credentials and a 'schemas' array. Keys depend on source_type. */
    payload: ExternalDataSourceCreateApiPayload
    /**
     * Table name prefix in HogQL.
     * @maxLength 100
     * @nullable
     */
    prefix?: string | null
    /**
     * Human-readable description.
     * @maxLength 400
     * @nullable
     */
    description?: string | null
    /** Connection mode: 'warehouse' (import) or 'direct' (live query).
     *
     * * `warehouse` - warehouse
     * * `direct` - direct */
    access_method?: AccessMethodEnumApi
    /** Where the request came from
     *
     * * `web` - web
     * * `api` - api
     * * `mcp` - mcp */
    created_via?: CreatedViaEnumApi
    /** Whether a synced source should also be live-queryable via direct connection. Defaults to true; ignored for pure direct-query sources. */
    direct_query_enabled?: boolean
}

export type PatchedExternalDataSourceSerializersApiSchemasItem = { [key: string]: unknown }

/**
 * Mixin for serializers to add user access control fields
 */
export interface PatchedExternalDataSourceSerializersApi {
    readonly id?: string
    readonly created_at?: string
    /** @nullable */
    readonly created_by?: string | null
    /** How this source was created. Defaults to `api` on create when omitted. `web` for the in-app UI, `api` for direct API callers, `mcp` for agent/MCP tool calls. Ignored on update.
     *
     * * `web` - web
     * * `api` - api
     * * `mcp` - mcp */
    created_via?: CreatedViaEnumApi | null
    readonly status?: string
    client_secret?: string
    account_id?: string
    readonly source_type?: ExternalDataSourceTypeEnumApi
    /** @nullable */
    readonly latest_error?: string | null
    /**
     * @maxLength 100
     * @nullable
     */
    prefix?: string | null
    /**
     * @maxLength 400
     * @nullable
     */
    description?: string | null
    readonly access_method?: AccessMethodEnumApi
    /** Whether this synced source is also live-queryable via direct connection. Defaults to true for new sources; ignored for pure direct-query sources. */
    direct_query_enabled?: boolean
    /** Backend engine detected for the direct connection.
     *
     * * `duckdb` - duckdb
     * * `postgres` - postgres
     * * `mysql` - mysql
     * * `snowflake` - snowflake */
    readonly engine?: EngineEnumApi | null
    /** @nullable */
    readonly last_run_at?: string | null
    readonly schemas?: readonly PatchedExternalDataSourceSerializersApiSchemasItem[]
    job_inputs?: unknown
    readonly revenue_analytics_config?: ExternalDataSourceRevenueAnalyticsConfigApi
    /**
     * The effective access level the user has for this object
     * @nullable
     */
    readonly user_access_level?: string | null
    readonly supports_webhooks?: boolean
    /** Whether this source supports per-column sync selection via `enabled_columns`. */
    readonly supports_column_selection?: boolean
}

export type ExternalDataSourceBulkUpdateSchemaApiRowFiltersItem = {
    column: string
    /** One of: > >= < <= = != IN "NOT IN". */
    operator: string
    /** Comparison value; must match the column's type. For `IN` / `NOT IN`, a comma-separated list (e.g. `1, 2, 3` or `'a','b'`). */
    value: unknown
}

export interface ExternalDataSourceBulkUpdateSchemaApi {
    /** Schema identifier to update. */
    id: string
    /** Whether the schema should be queryable/synced. */
    should_sync?: boolean
    /** Requested sync mode for the schema (incremental, full_refresh, append, cdc, or xmin).
     *
     * * `full_refresh` - full_refresh
     * * `incremental` - incremental
     * * `append` - append
     * * `webhook` - webhook
     * * `cdc` - cdc
     * * `xmin` - xmin */
    sync_type?: SyncTypeEnumApi | null
    /**
     * Incremental cursor field for incremental or append syncs.
     * @nullable
     */
    incremental_field?: string | null
    /**
     * Type of the incremental cursor field.
     * @nullable
     */
    incremental_field_type?: string | null
    /**
     * Human-readable sync frequency value.
     * @nullable
     */
    sync_frequency?: string | null
    /**
     * UTC anchor time for scheduled syncs.
     * @nullable
     */
    sync_time_of_day?: string | null
    /** How CDC-backed tables should be exposed.
     *
     * * `consolidated` - consolidated
     * * `cdc_only` - cdc_only
     * * `both` - both */
    cdc_table_mode?: CdcTableModeEnumApi | null
    /**
     * Columns to sync. Null means sync all columns.
     * @nullable
     */
    enabled_columns?: string[] | null
    /**
     * Row-filter predicates ANDed onto the source query. Null/empty means sync all rows.
     * @nullable
     */
    row_filters?: ExternalDataSourceBulkUpdateSchemaApiRowFiltersItem[] | null
}

export interface PatchedExternalDataSourceBulkUpdateSchemasApi {
    /** Schema updates to apply in a single batch. */
    schemas?: ExternalDataSourceBulkUpdateSchemaApi[]
}

/**
 * * `oauth` - oauth
 * * `credentials` - credentials
 */
export type AuthMethodEnumApi = (typeof AuthMethodEnumApi)[keyof typeof AuthMethodEnumApi]

export const AuthMethodEnumApi = {
    Oauth: 'oauth',
    Credentials: 'credentials',
} as const

export interface SourceConnectLinkApi {
    /** The source type the link is for. */
    source_type: string
    /** What the user will do on the connect page: 'oauth' = authorize an account in their browser; 'credentials' = enter connection details (or pick OAuth where the source offers both). Either way secrets never pass through the agent, and the result is always a stored credential id.
     *
     * * `oauth` - oauth
     * * `credentials` - credentials */
    auth_method: AuthMethodEnumApi
    /** Full URL to share with the user. It opens the source's connection form in PostHog — credentials never pass through the agent or the chat. */
    connect_url: string
    /** Next steps for the agent to relay to the user. */
    instructions: string
}

export interface ExternalDataSourceConnectionOptionApi {
    readonly id: string
    /** @nullable */
    readonly prefix: string | null
    /** Backend engine detected for the direct connection.
     *
     * * `duckdb` - duckdb
     * * `postgres` - postgres
     * * `mysql` - mysql
     * * `snowflake` - snowflake */
    readonly engine: EngineEnumApi | null
}

export interface PaginatedExternalDataSourceConnectionOptionListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: ExternalDataSourceConnectionOptionApi[]
}

/**
 * Validate credentials and preview available tables from a remote database.
 *
 * The request body contains source_type plus flat source-specific credential fields
 * (e.g. host, port, database, user, password, schema for Postgres). The credential
 * fields vary per source_type and are validated dynamically by the source registry.
 *
 * For source_type "Custom" (a user-defined REST API) the body carries `manifest_json`
 * (a stringified RESTAPIConfig describing client.base_url, auth, and resources) plus the
 * credential for the manifest's declared auth type — `auth_token` (bearer), `auth_api_key`
 * (api_key), or `auth_password` (http_basic); keep secrets in these auth_* keys, never
 * inline in manifest_json. The returned tables mirror the manifest's resources, with
 * detected primary keys and incremental cursors.
 */
export interface DatabaseSchemaRequestApi {
    /** The source type to validate against.
     *
     * * `Ashby` - Ashby
     * * `Supabase` - Supabase
     * * `CustomerIO` - CustomerIO
     * * `Github` - Github
     * * `Stripe` - Stripe
     * * `Hubspot` - Hubspot
     * * `Postgres` - Postgres
     * * `Zendesk` - Zendesk
     * * `Snowflake` - Snowflake
     * * `Salesforce` - Salesforce
     * * `MySQL` - MySQL
     * * `MongoDB` - MongoDB
     * * `MSSQL` - MSSQL
     * * `Vitally` - Vitally
     * * `BigQuery` - BigQuery
     * * `Chargebee` - Chargebee
     * * `Clerk` - Clerk
     * * `GoogleAds` - GoogleAds
     * * `GoogleSearchConsole` - GoogleSearchConsole
     * * `TemporalIO` - TemporalIO
     * * `DoIt` - DoIt
     * * `GoogleSheets` - GoogleSheets
     * * `MetaAds` - MetaAds
     * * `Klaviyo` - Klaviyo
     * * `Mailchimp` - Mailchimp
     * * `Braze` - Braze
     * * `Mailjet` - Mailjet
     * * `Redshift` - Redshift
     * * `Polar` - Polar
     * * `RevenueCat` - RevenueCat
     * * `LinkedinAds` - LinkedinAds
     * * `RedditAds` - RedditAds
     * * `TikTokAds` - TikTokAds
     * * `BingAds` - BingAds
     * * `Shopify` - Shopify
     * * `Attio` - Attio
     * * `SnapchatAds` - SnapchatAds
     * * `Linear` - Linear
     * * `Intercom` - Intercom
     * * `Amplitude` - Amplitude
     * * `Mixpanel` - Mixpanel
     * * `Jira` - Jira
     * * `ActiveCampaign` - ActiveCampaign
     * * `Marketo` - Marketo
     * * `Adjust` - Adjust
     * * `AppsFlyer` - AppsFlyer
     * * `Freshdesk` - Freshdesk
     * * `GoogleAnalytics` - GoogleAnalytics
     * * `Pipedrive` - Pipedrive
     * * `SendGrid` - SendGrid
     * * `Slack` - Slack
     * * `PagerDuty` - PagerDuty
     * * `Asana` - Asana
     * * `Notion` - Notion
     * * `Airtable` - Airtable
     * * `Greenhouse` - Greenhouse
     * * `BambooHR` - BambooHR
     * * `Lever` - Lever
     * * `GitLab` - GitLab
     * * `Datadog` - Datadog
     * * `Sentry` - Sentry
     * * `Pendo` - Pendo
     * * `FullStory` - FullStory
     * * `AmazonAds` - AmazonAds
     * * `PinterestAds` - PinterestAds
     * * `AppleSearchAds` - AppleSearchAds
     * * `QuickBooks` - QuickBooks
     * * `Xero` - Xero
     * * `NetSuite` - NetSuite
     * * `WooCommerce` - WooCommerce
     * * `BigCommerce` - BigCommerce
     * * `PayPal` - PayPal
     * * `Square` - Square
     * * `Zoom` - Zoom
     * * `Trello` - Trello
     * * `Monday` - Monday
     * * `ClickUp` - ClickUp
     * * `Confluence` - Confluence
     * * `Recurly` - Recurly
     * * `SalesLoft` - SalesLoft
     * * `Outreach` - Outreach
     * * `Gong` - Gong
     * * `Calendly` - Calendly
     * * `Typeform` - Typeform
     * * `Iterable` - Iterable
     * * `ZohoCRM` - ZohoCRM
     * * `Close` - Close
     * * `Oracle` - Oracle
     * * `DynamoDB` - DynamoDB
     * * `Elasticsearch` - Elasticsearch
     * * `Kafka` - Kafka
     * * `LaunchDarkly` - LaunchDarkly
     * * `Braintree` - Braintree
     * * `Recharge` - Recharge
     * * `HelpScout` - HelpScout
     * * `Gorgias` - Gorgias
     * * `Instagram` - Instagram
     * * `YouTubeAnalytics` - YouTubeAnalytics
     * * `FacebookPages` - FacebookPages
     * * `TwitterAds` - TwitterAds
     * * `Workday` - Workday
     * * `ServiceNow` - ServiceNow
     * * `Pardot` - Pardot
     * * `Copper` - Copper
     * * `Front` - Front
     * * `ChartMogul` - ChartMogul
     * * `Zuora` - Zuora
     * * `Paddle` - Paddle
     * * `CircleCI` - CircleCI
     * * `CockroachDB` - CockroachDB
     * * `Firebase` - Firebase
     * * `AzureBlob` - AzureBlob
     * * `GoogleDrive` - GoogleDrive
     * * `OneDrive` - OneDrive
     * * `SharePoint` - SharePoint
     * * `Box` - Box
     * * `SFTP` - SFTP
     * * `MicrosoftTeams` - MicrosoftTeams
     * * `Aircall` - Aircall
     * * `Webflow` - Webflow
     * * `Okta` - Okta
     * * `Auth0` - Auth0
     * * `Productboard` - Productboard
     * * `Smartsheet` - Smartsheet
     * * `Wrike` - Wrike
     * * `Plaid` - Plaid
     * * `SurveyMonkey` - SurveyMonkey
     * * `Eventbrite` - Eventbrite
     * * `RingCentral` - RingCentral
     * * `Twilio` - Twilio
     * * `Freshsales` - Freshsales
     * * `Shortcut` - Shortcut
     * * `ConvertKit` - ConvertKit
     * * `Drip` - Drip
     * * `CampaignMonitor` - CampaignMonitor
     * * `MailerLite` - MailerLite
     * * `Omnisend` - Omnisend
     * * `Brevo` - Brevo
     * * `Postmark` - Postmark
     * * `Granola` - Granola
     * * `BuildBetter` - BuildBetter
     * * `Convex` - Convex
     * * `ClickHouse` - ClickHouse
     * * `Plain` - Plain
     * * `Resend` - Resend
     * * `PgAnalyze` - PgAnalyze
     * * `WorkOS` - WorkOS
     * * `AmazonS3` - AmazonS3
     * * `GoogleCloudStorage` - GoogleCloudStorage
     * * `Databricks` - Databricks
     * * `Dynamics365` - Dynamics365
     * * `SalesforceMarketingCloud` - SalesforceMarketingCloud
     * * `Db2` - Db2
     * * `Heap` - Heap
     * * `AdobeAnalytics` - AdobeAnalytics
     * * `Matomo` - Matomo
     * * `Optimizely` - Optimizely
     * * `Adyen` - Adyen
     * * `GoCardless` - GoCardless
     * * `Mollie` - Mollie
     * * `CheckoutCom` - CheckoutCom
     * * `Branch` - Branch
     * * `Criteo` - Criteo
     * * `Outbrain` - Outbrain
     * * `Taboola` - Taboola
     * * `AdRoll` - AdRoll
     * * `DisplayVideo360` - DisplayVideo360
     * * `GoogleAdManager` - GoogleAdManager
     * * `CampaignManager360` - CampaignManager360
     * * `SearchAds360` - SearchAds360
     * * `AdobeCommerce` - AdobeCommerce
     * * `AmazonSellingPartner` - AmazonSellingPartner
     * * `Ebay` - Ebay
     * * `Commercetools` - Commercetools
     * * `LightspeedRetail` - LightspeedRetail
     * * `ShipStation` - ShipStation
     * * `ConstantContact` - ConstantContact
     * * `Mailgun` - Mailgun
     * * `Eloqua` - Eloqua
     * * `Sailthru` - Sailthru
     * * `Ortto` - Ortto
     * * `Attentive` - Attentive
     * * `Kustomer` - Kustomer
     * * `Dixa` - Dixa
     * * `Gladly` - Gladly
     * * `Qualtrics` - Qualtrics
     * * `Delighted` - Delighted
     * * `AzureDevOps` - AzureDevOps
     * * `Rollbar` - Rollbar
     * * `Opsgenie` - Opsgenie
     * * `IncidentIo` - IncidentIo
     * * `Pingdom` - Pingdom
     * * `Cloudflare` - Cloudflare
     * * `CosmosDB` - CosmosDB
     * * `PlanetScale` - PlanetScale
     * * `SapHana` - SapHana
     * * `Rippling` - Rippling
     * * `HiBob` - HiBob
     * * `Personio` - Personio
     * * `Deel` - Deel
     * * `AdpWorkforceNow` - AdpWorkforceNow
     * * `Paylocity` - Paylocity
     * * `Gusto` - Gusto
     * * `CultureAmp` - CultureAmp
     * * `Lattice` - Lattice
     * * `SageIntacct` - SageIntacct
     * * `FreshBooks` - FreshBooks
     * * `Expensify` - Expensify
     * * `Ramp` - Ramp
     * * `Brex` - Brex
     * * `Coupa` - Coupa
     * * `SapConcur` - SapConcur
     * * `Apollo` - Apollo
     * * `Crunchbase` - Crunchbase
     * * `ZoomInfo` - ZoomInfo
     * * `Clari` - Clari
     * * `Chorus` - Chorus
     * * `Coda` - Coda
     * * `Guru` - Guru
     * * `Dropbox` - Dropbox
     * * `Docusign` - Docusign
     * * `PandaDoc` - PandaDoc
     * * `SapErp` - SapErp
     * * `SapSuccessFactors` - SapSuccessFactors
     * * `OracleEbs` - OracleEbs
     * * `OracleFusion` - OracleFusion
     * * `AmazonSNS` - AmazonSNS
     * * `AmazonEventBridge` - AmazonEventBridge
     * * `AmazonSQS` - AmazonSQS
     * * `AmazonKinesis` - AmazonKinesis
     * * `AmazonCloudWatch` - AmazonCloudWatch
     * * `OpenAIAds` - OpenAIAds
     * * `OneHundredMs` - OneHundredMs
     * * `SevenShifts` - SevenShifts
     * * `AcuityScheduling` - AcuityScheduling
     * * `AgileCRM` - AgileCRM
     * * `Aha` - Aha
     * * `Airbyte` - Airbyte
     * * `Akeneo` - Akeneo
     * * `Algolia` - Algolia
     * * `AlpacaBrokerAPI` - AlpacaBrokerAPI
     * * `ApifyDataset` - ApifyDataset
     * * `Appcues` - Appcues
     * * `Appfigures` - Appfigures
     * * `Appfollow` - Appfollow
     * * `Apptivo` - Apptivo
     * * `AssemblyAI` - AssemblyAI
     * * `Awin` - Awin
     * * `AwsCloudTrail` - AwsCloudTrail
     * * `AzureTableStorage` - AzureTableStorage
     * * `Babelforce` - Babelforce
     * * `Basecamp` - Basecamp
     * * `Beamer` - Beamer
     * * `BigMailer` - BigMailer
     * * `Bluetally` - Bluetally
     * * `BoldSign` - BoldSign
     * * `BreezyHR` - BreezyHR
     * * `Bugsnag` - Bugsnag
     * * `Buildkite` - Buildkite
     * * `Bunny` - Bunny
     * * `Buzzsprout` - Buzzsprout
     * * `CalCom` - CalCom
     * * `CallRail` - CallRail
     * * `Campayn` - Campayn
     * * `Canny` - Canny
     * * `CapsuleCRM` - CapsuleCRM
     * * `CaptainData` - CaptainData
     * * `CartCom` - CartCom
     * * `CastorEDC` - CastorEDC
     * * `Chameleon` - Chameleon
     * * `Chargedesk` - Chargedesk
     * * `Chargify` - Chargify
     * * `Chift` - Chift
     * * `Churnkey` - Churnkey
     * * `Cin7` - Cin7
     * * `CiscoMeraki` - CiscoMeraki
     * * `Clazar` - Clazar
     * * `Clockify` - Clockify
     * * `Clockodo` - Clockodo
     * * `Cloudbeds` - Cloudbeds
     * * `Coassemble` - Coassemble
     * * `Codefresh` - Codefresh
     * * `Concord` - Concord
     * * `ConfigCat` - ConfigCat
     * * `Couchbase` - Couchbase
     * * `Curve` - Curve
     * * `Customerly` - Customerly
     * * `Datascope` - Datascope
     * * `Dbt` - Dbt
     * * `Deputy` - Deputy
     * * `DevinAI` - DevinAI
     * * `Docuseal` - Docuseal
     * * `Dolibarr` - Dolibarr
     * * `Dremio` - Dremio
     * * `DropboxSign` - DropboxSign
     * * `Dwolla` - Dwolla
     * * `EConomic` - EConomic
     * * `Easypost` - Easypost
     * * `Easypromos` - Easypromos
     * * `Elasticemail` - Elasticemail
     * * `EmailOctopus` - EmailOctopus
     * * `EmploymentHero` - EmploymentHero
     * * `Encharge` - Encharge
     * * `Eventee` - Eventee
     * * `Eventzilla` - Eventzilla
     * * `Everhour` - Everhour
     * * `EZOfficeInventory` - EZOfficeInventory
     * * `Factorial` - Factorial
     * * `Fastbill` - Fastbill
     * * `Fastly` - Fastly
     * * `Fauna` - Fauna
     * * `Feishu` - Feishu
     * * `Fillout` - Fillout
     * * `Finage` - Finage
     * * `Firebolt` - Firebolt
     * * `FireHydrant` - FireHydrant
     * * `Fleetio` - Fleetio
     * * `Flexmail` - Flexmail
     * * `Flexport` - Flexport
     * * `FloatApp` - FloatApp
     * * `Flowlu` - Flowlu
     * * `Formbricks` - Formbricks
     * * `FreeAgent` - FreeAgent
     * * `Freightview` - Freightview
     * * `Freshcaller` - Freshcaller
     * * `Freshchat` - Freshchat
     * * `Freshservice` - Freshservice
     * * `Fulcrum` - Fulcrum
     * * `GainsightPx` - GainsightPx
     * * `GitBook` - GitBook
     * * `Glassfrog` - Glassfrog
     * * `Goldcast` - Goldcast
     * * `GoLogin` - GoLogin
     * * `Grafana` - Grafana
     * * `GreytHr` - GreytHr
     * * `Gridly` - Gridly
     * * `Harness` - Harness
     * * `Height` - Height
     * * `Hellobaton` - Hellobaton
     * * `HighLevel` - HighLevel
     * * `HoorayHR` - HoorayHR
     * * `Hubplanner` - Hubplanner
     * * `Humanitix` - Humanitix
     * * `Huntr` - Huntr
     * * `Inflowinventory` - Inflowinventory
     * * `InforNexus` - InforNexus
     * * `Insightful` - Insightful
     * * `Insightly` - Insightly
     * * `Instantly` - Instantly
     * * `Instatus` - Instatus
     * * `Intruder` - Intruder
     * * `Invoiced` - Invoiced
     * * `Invoiceninja` - Invoiceninja
     * * `JamfPro` - JamfPro
     * * `JobNimbus` - JobNimbus
     * * `Jotform` - Jotform
     * * `JudgeMeReviews` - JudgeMeReviews
     * * `JustCall` - JustCall
     * * `JustSift` - JustSift
     * * `K6Cloud` - K6Cloud
     * * `Katana` - Katana
     * * `Keka` - Keka
     * * `Kisi` - Kisi
     * * `Kissmetrics` - Kissmetrics
     * * `Klarna` - Klarna
     * * `Klaus` - Klaus
     * * `Lago` - Lago
     * * `Leadfeeder` - Leadfeeder
     * * `Lemlist` - Lemlist
     * * `LessAnnoyingCRM` - LessAnnoyingCRM
     * * `LinkedinPages` - LinkedinPages
     * * `Linkrunner` - Linkrunner
     * * `Linnworks` - Linnworks
     * * `Lob` - Lob
     * * `Lokalise` - Lokalise
     * * `Looker` - Looker
     * * `Luma` - Luma
     * * `MailerSend` - MailerSend
     * * `Mailosaur` - Mailosaur
     * * `Mailtrap` - Mailtrap
     * * `Mantle` - Mantle
     * * `Mention` - Mention
     * * `MercadoAds` - MercadoAds
     * * `Merge` - Merge
     * * `Metabase` - Metabase
     * * `Metricool` - Metricool
     * * `MicrosoftDataverse` - MicrosoftDataverse
     * * `MicrosoftEntraId` - MicrosoftEntraId
     * * `MicrosoftLists` - MicrosoftLists
     * * `Miro` - Miro
     * * `Missive` - Missive
     * * `MixMax` - MixMax
     * * `Mode` - Mode
     * * `Mux` - Mux
     * * `MyHours` - MyHours
     * * `N8n` - N8n
     * * `Navan` - Navan
     * * `NebiusAI` - NebiusAI
     * * `Nexiopay` - Nexiopay
     * * `NinjaOneRMM` - NinjaOneRMM
     * * `NoCRM` - NoCRM
     * * `NorthpassLMS` - NorthpassLMS
     * * `Nutshell` - Nutshell
     * * `Nylas` - Nylas
     * * `Oncehub` - Oncehub
     * * `Onepagecrm` - Onepagecrm
     * * `OneSignal` - OneSignal
     * * `Onfleet` - Onfleet
     * * `OpinionStage` - OpinionStage
     * * `OPUSWatch` - OPUSWatch
     * * `Orb` - Orb
     * * `Orbit` - Orbit
     * * `Oura` - Oura
     * * `Oveit` - Oveit
     * * `PabblySubscriptionsBilling` - PabblySubscriptionsBilling
     * * `Paperform` - Paperform
     * * `Papersign` - Papersign
     * * `Partnerize` - Partnerize
     * * `PartnerStack` - PartnerStack
     * * `PayFit` - PayFit
     * * `Paystack` - Paystack
     * * `Pennylane` - Pennylane
     * * `Perk` - Perk
     * * `PersistIq` - PersistIq
     * * `Persona` - Persona
     * * `Phyllo` - Phyllo
     * * `Picqer` - Picqer
     * * `Pipeliner` - Pipeliner
     * * `PivotalTracker` - PivotalTracker
     * * `Piwik` - Piwik
     * * `Planhat` - Planhat
     * * `Plausible` - Plausible
     * * `Poplar` - Poplar
     * * `PrestaShop` - PrestaShop
     * * `Pretix` - Pretix
     * * `Primetric` - Primetric
     * * `Printify` - Printify
     * * `Productive` - Productive
     * * `Pylon` - Pylon
     * * `Qonto` - Qonto
     * * `Qualaroo` - Qualaroo
     * * `Railz` - Railz
     * * `RDStationMarketing` - RDStationMarketing
     * * `Recruitee` - Recruitee
     * * `Reddit` - Reddit
     * * `ReferralHero` - ReferralHero
     * * `RentCast` - RentCast
     * * `Repairshopr` - Repairshopr
     * * `ReplyIo` - ReplyIo
     * * `RetailExpress` - RetailExpress
     * * `Retently` - Retently
     * * `RevolutMerchant` - RevolutMerchant
     * * `RocketChat` - RocketChat
     * * `Rocketlane` - Rocketlane
     * * `Rootly` - Rootly
     * * `Ruddr` - Ruddr
     * * `SafetyCulture` - SafetyCulture
     * * `SageHR` - SageHR
     * * `Salesflare` - Salesflare
     * * `SAPFieldglass` - SAPFieldglass
     * * `SavvyCal` - SavvyCal
     * * `Secoda` - Secoda
     * * `Segment` - Segment
     * * `Sendowl` - Sendowl
     * * `SendPulse` - SendPulse
     * * `Senseforce` - Senseforce
     * * `Serpstat` - Serpstat
     * * `Sharetribe` - Sharetribe
     * * `Shippo` - Shippo
     * * `ShopWired` - ShopWired
     * * `Shortio` - Shortio
     * * `Shutterstock` - Shutterstock
     * * `SigmaComputing` - SigmaComputing
     * * `SignNow` - SignNow
     * * `SimpleCast` - SimpleCast
     * * `Simplesat` - Simplesat
     * * `Smaily` - Smaily
     * * `SmartEngage` - SmartEngage
     * * `Smartreach` - Smartreach
     * * `Smartwaiver` - Smartwaiver
     * * `SolarwindsServiceDesk` - SolarwindsServiceDesk
     * * `SonarCloud` - SonarCloud
     * * `SparkPost` - SparkPost
     * * `SplitIo` - SplitIo
     * * `SpotifyAds` - SpotifyAds
     * * `SpotlerCRM` - SpotlerCRM
     * * `Squarespace` - Squarespace
     * * `Statsig` - Statsig
     * * `Statuspage` - Statuspage
     * * `Stigg` - Stigg
     * * `Strava` - Strava
     * * `SurveySparrow` - SurveySparrow
     * * `Survicate` - Survicate
     * * `Svix` - Svix
     * * `Systeme` - Systeme
     * * `Tavus` - Tavus
     * * `Teamtailor` - Teamtailor
     * * `Teamwork` - Teamwork
     * * `Tempo` - Tempo
     * * `Testrail` - Testrail
     * * `Thinkific` - Thinkific
     * * `ThinkificCourses` - ThinkificCourses
     * * `ThriveLearning` - ThriveLearning
     * * `Ticketmaster` - Ticketmaster
     * * `TicketTailor` - TicketTailor
     * * `TickTick` - TickTick
     * * `Timely` - Timely
     * * `Tinyemail` - Tinyemail
     * * `Todoist` - Todoist
     * * `Toggl` - Toggl
     * * `TrackPMS` - TrackPMS
     * * `Tremendous` - Tremendous
     * * `TrustPilot` - TrustPilot
     * * `Twitter` - Twitter
     * * `TyntecSMS` - TyntecSMS
     * * `Unleash` - Unleash
     * * `UpPromote` - UpPromote
     * * `Uptick` - Uptick
     * * `Uservoice` - Uservoice
     * * `Vantage` - Vantage
     * * `Veeqo` - Veeqo
     * * `Vercel` - Vercel
     * * `VismaEconomic` - VismaEconomic
     * * `VWO` - VWO
     * * `Waiteraid` - Waiteraid
     * * `Wasabi` - Wasabi
     * * `WhenIWork` - WhenIWork
     * * `Wordpress` - Wordpress
     * * `Workable` - Workable
     * * `Workflowmax` - Workflowmax
     * * `Workramp` - Workramp
     * * `Wufoo` - Wufoo
     * * `Xsolla` - Xsolla
     * * `YandexMetrica` - YandexMetrica
     * * `Yotpo` - Yotpo
     * * `Ynab` - Ynab
     * * `Younium` - Younium
     * * `YouSign` - YouSign
     * * `YoutubeData` - YoutubeData
     * * `ZapierSupportedStorage` - ZapierSupportedStorage
     * * `ZapSign` - ZapSign
     * * `ZendeskSell` - ZendeskSell
     * * `ZendeskSunshine` - ZendeskSunshine
     * * `Zenefits` - Zenefits
     * * `Zenloop` - Zenloop
     * * `ZohoAnalytics` - ZohoAnalytics
     * * `ZohoBigin` - ZohoBigin
     * * `ZohoBilling` - ZohoBilling
     * * `ZohoBooks` - ZohoBooks
     * * `ZohoCampaign` - ZohoCampaign
     * * `ZohoDesk` - ZohoDesk
     * * `ZohoExpense` - ZohoExpense
     * * `ZohoInventory` - ZohoInventory
     * * `ZohoInvoice` - ZohoInvoice
     * * `ZonkaFeedback` - ZonkaFeedback
     * * `AlphaVantage` - AlphaVantage
     * * `Aviationstack` - Aviationstack
     * * `Bitly` - Bitly
     * * `Blogger` - Blogger
     * * `Breezometer` - Breezometer
     * * `CareQualityCommission` - CareQualityCommission
     * * `Cimis` - Cimis
     * * `CoinApi` - CoinApi
     * * `CoinGecko` - CoinGecko
     * * `CoinMarketCap` - CoinMarketCap
     * * `DingConnect` - DingConnect
     * * `Dockerhub` - Dockerhub
     * * `ExchangeRatesApi` - ExchangeRatesApi
     * * `FinancialModelling` - FinancialModelling
     * * `Finnhub` - Finnhub
     * * `Finnworlds` - Finnworlds
     * * `Giphy` - Giphy
     * * `Gmail` - Gmail
     * * `GNews` - GNews
     * * `GoogleCalendar` - GoogleCalendar
     * * `GoogleClassroom` - GoogleClassroom
     * * `GoogleDirectory` - GoogleDirectory
     * * `GoogleForms` - GoogleForms
     * * `GooglePageSpeedInsights` - GooglePageSpeedInsights
     * * `GoogleTasks` - GoogleTasks
     * * `GoogleWebfonts` - GoogleWebfonts
     * * `GoogleWorkspaceAdminReports` - GoogleWorkspaceAdminReports
     * * `HuggingFace` - HuggingFace
     * * `IlluminaBasespace` - IlluminaBasespace
     * * `Imagga` - Imagga
     * * `Interzoid` - Interzoid
     * * `IP2Whois` - IP2Whois
     * * `KYVE` - KYVE
     * * `Marketstack` - Marketstack
     * * `Mendeley` - Mendeley
     * * `Nasa` - Nasa
     * * `NewYorkTimes` - NewYorkTimes
     * * `NewsApi` - NewsApi
     * * `NewsData` - NewsData
     * * `OpenDataDc` - OpenDataDc
     * * `OpenExchangeRates` - OpenExchangeRates
     * * `OpenAQ` - OpenAQ
     * * `OpenFDA` - OpenFDA
     * * `OpenWeather` - OpenWeather
     * * `Outlook` - Outlook
     * * `Perigon` - Perigon
     * * `Pexels` - Pexels
     * * `Pocket` - Pocket
     * * `Polygon` - Polygon
     * * `PyPI` - PyPI
     * * `Recreation` - Recreation
     * * `RKICovid` - RKICovid
     * * `Rss` - Rss
     * * `SimFin` - SimFin
     * * `StockData` - StockData
     * * `Guardian` - Guardian
     * * `TMDb` - TMDb
     * * `TVMaze` - TVMaze
     * * `TwelveData` - TwelveData
     * * `Ubidots` - Ubidots
     * * `USCensus` - USCensus
     * * `Watchmode` - Watchmode
     * * `WikipediaPageviews` - WikipediaPageviews
     * * `YahooFinance` - YahooFinance
     * * `Clarifai` - Clarifai
     * * `Adapty` - Adapty
     * * `Braintrust` - Braintrust
     * * `StreamElements` - StreamElements
     * * `Streamlabs` - Streamlabs
     * * `Datorama` - Datorama
     * * `Ahrefs` - Ahrefs
     * * `Lightfield` - Lightfield
     * * `Appstack` - Appstack
     * * `Razorpay` - Razorpay
     * * `Neon` - Neon
     * * `NewRelic` - NewRelic
     * * `Custom` - Custom
     * * `Tile38` - Tile38
     * * `Chatwoot` - Chatwoot
     * * `Sanity` - Sanity
     * * `Metronome` - Metronome
     * * `Jobber` - Jobber
     * * `Knock` - Knock
     * * `Leexi` - Leexi
     * * `RB2B` - RB2B
     * * `Superwall` - Superwall
     * * `Liana` - Liana
     * * `TawkTo` - TawkTo
     * * `Hightouch` - Hightouch
     * * `LemonSqueezy` - LemonSqueezy
     * * `Ikas` - Ikas
     * * `Talkwalker` - Talkwalker
     * * `NextdoorAds` - NextdoorAds
     * * `AppLovin` - AppLovin
     * * `Baserow` - Baserow
     * * `Plunk` - Plunk
     * * `Dub` - Dub
     * * `AirOps` - AirOps
     * * `Podium` - Podium
     * * `Loops` - Loops
     * * `Redis` - Redis
     * * `Mercury` - Mercury
     * * `Gojiberry` - Gojiberry
     * * `Teachable` - Teachable
     * * `PeecAI` - PeecAI
     * * `Healthchecks` - Healthchecks
     * * `Impact` - Impact
     * * `AikidoSecurity` - AikidoSecurity
     * * `Alguna` - Alguna
     * * `Anthropic` - Anthropic
     * * `Appwrite` - Appwrite
     * * `BlandAI` - BlandAI
     * * `BrowseAI` - BrowseAI
     * * `BrowserUse` - BrowserUse
     * * `ChartHop` - ChartHop
     * * `Cody` - Cody
     * * `Cursor` - Cursor
     * * `Decagon` - Decagon
     * * `Deepgram` - Deepgram
     * * `ElevenLabs` - ElevenLabs
     * * `Harvey` - Harvey
     * * `Hyperspell` - Hyperspell
     * * `Langfuse` - Langfuse
     * * `LingoDev` - LingoDev
     * * `M3ter` - M3ter
     * * `Maxio` - Maxio
     * * `Metorial` - Metorial
     * * `OpenRouter` - OpenRouter
     * * `TogetherAI` - TogetherAI
     * * `Vapi` - Vapi
     * * `Vespa` - Vespa
     * * `Writesonic` - Writesonic */
    source_type: ExternalDataSourceTypeEnumApi
}

export interface DraftCustomManifestRequestApi {
    /** Optional human name of the API being connected (e.g. 'Acme CRM'). Used only to orient the model. */
    source_name?: string
    /** URL of the API documentation to read. Provide this or docs_text; fetched server-side via the egress proxy. */
    docs_url?: string
    /** Raw API documentation or an OpenAPI/Swagger spec, pasted directly. Provide this or docs_url. */
    docs_text?: string
}

/**
 * * `ok` - ok
 * * `invalid` - invalid
 * * `model_error` - model_error
 */
export type DraftStatusEnumApi = (typeof DraftStatusEnumApi)[keyof typeof DraftStatusEnumApi]

export const DraftStatusEnumApi = {
    Ok: 'ok',
    Invalid: 'invalid',
    ModelError: 'model_error',
} as const

export interface DraftCustomManifestResponseApi {
    /** 'ok' = a manifest validated; 'invalid' = a manifest was drafted but never validated within the budget (see error; manifest_json holds the last attempt to fix by hand); 'model_error' = the model returned no usable JSON.
     *
     * * `ok` - ok
     * * `invalid` - invalid
     * * `model_error` - model_error */
    draft_status: DraftStatusEnumApi
    /**
     * The drafted RESTAPIConfig manifest as a JSON string (non-secret), or null if none was produced.
     * @nullable
     */
    manifest_json: string | null
    /** Names of the resources (tables) the validated manifest exposes. Empty unless draft_status is 'ok'. */
    resource_names: string[]
    /** How many draft→validate→repair rounds were run. */
    attempts: number
    /**
     * The last validation error when draft_status is not 'ok'; null on success.
     * @nullable
     */
    error: string | null
}

/**
 * Source config as flat keys. For source_type 'Custom': 'manifest_json' (a stringified RESTAPIConfig describing client.base_url, auth, and resources) plus the credential for the manifest's declared auth type — 'auth_token' (bearer), 'auth_api_key' (api_key), or 'auth_password' (http_basic). Secrets stay in these auth_* keys, never inline in the manifest.
 */
export type SourcePreviewRequestApiPayload = { [key: string]: unknown }

export interface SourcePreviewRequestApi {
    /** The source type to preview. Only 'Custom' (a user-defined REST API) is supported today.
     *
     * * `Ashby` - Ashby
     * * `Supabase` - Supabase
     * * `CustomerIO` - CustomerIO
     * * `Github` - Github
     * * `Stripe` - Stripe
     * * `Hubspot` - Hubspot
     * * `Postgres` - Postgres
     * * `Zendesk` - Zendesk
     * * `Snowflake` - Snowflake
     * * `Salesforce` - Salesforce
     * * `MySQL` - MySQL
     * * `MongoDB` - MongoDB
     * * `MSSQL` - MSSQL
     * * `Vitally` - Vitally
     * * `BigQuery` - BigQuery
     * * `Chargebee` - Chargebee
     * * `Clerk` - Clerk
     * * `GoogleAds` - GoogleAds
     * * `GoogleSearchConsole` - GoogleSearchConsole
     * * `TemporalIO` - TemporalIO
     * * `DoIt` - DoIt
     * * `GoogleSheets` - GoogleSheets
     * * `MetaAds` - MetaAds
     * * `Klaviyo` - Klaviyo
     * * `Mailchimp` - Mailchimp
     * * `Braze` - Braze
     * * `Mailjet` - Mailjet
     * * `Redshift` - Redshift
     * * `Polar` - Polar
     * * `RevenueCat` - RevenueCat
     * * `LinkedinAds` - LinkedinAds
     * * `RedditAds` - RedditAds
     * * `TikTokAds` - TikTokAds
     * * `BingAds` - BingAds
     * * `Shopify` - Shopify
     * * `Attio` - Attio
     * * `SnapchatAds` - SnapchatAds
     * * `Linear` - Linear
     * * `Intercom` - Intercom
     * * `Amplitude` - Amplitude
     * * `Mixpanel` - Mixpanel
     * * `Jira` - Jira
     * * `ActiveCampaign` - ActiveCampaign
     * * `Marketo` - Marketo
     * * `Adjust` - Adjust
     * * `AppsFlyer` - AppsFlyer
     * * `Freshdesk` - Freshdesk
     * * `GoogleAnalytics` - GoogleAnalytics
     * * `Pipedrive` - Pipedrive
     * * `SendGrid` - SendGrid
     * * `Slack` - Slack
     * * `PagerDuty` - PagerDuty
     * * `Asana` - Asana
     * * `Notion` - Notion
     * * `Airtable` - Airtable
     * * `Greenhouse` - Greenhouse
     * * `BambooHR` - BambooHR
     * * `Lever` - Lever
     * * `GitLab` - GitLab
     * * `Datadog` - Datadog
     * * `Sentry` - Sentry
     * * `Pendo` - Pendo
     * * `FullStory` - FullStory
     * * `AmazonAds` - AmazonAds
     * * `PinterestAds` - PinterestAds
     * * `AppleSearchAds` - AppleSearchAds
     * * `QuickBooks` - QuickBooks
     * * `Xero` - Xero
     * * `NetSuite` - NetSuite
     * * `WooCommerce` - WooCommerce
     * * `BigCommerce` - BigCommerce
     * * `PayPal` - PayPal
     * * `Square` - Square
     * * `Zoom` - Zoom
     * * `Trello` - Trello
     * * `Monday` - Monday
     * * `ClickUp` - ClickUp
     * * `Confluence` - Confluence
     * * `Recurly` - Recurly
     * * `SalesLoft` - SalesLoft
     * * `Outreach` - Outreach
     * * `Gong` - Gong
     * * `Calendly` - Calendly
     * * `Typeform` - Typeform
     * * `Iterable` - Iterable
     * * `ZohoCRM` - ZohoCRM
     * * `Close` - Close
     * * `Oracle` - Oracle
     * * `DynamoDB` - DynamoDB
     * * `Elasticsearch` - Elasticsearch
     * * `Kafka` - Kafka
     * * `LaunchDarkly` - LaunchDarkly
     * * `Braintree` - Braintree
     * * `Recharge` - Recharge
     * * `HelpScout` - HelpScout
     * * `Gorgias` - Gorgias
     * * `Instagram` - Instagram
     * * `YouTubeAnalytics` - YouTubeAnalytics
     * * `FacebookPages` - FacebookPages
     * * `TwitterAds` - TwitterAds
     * * `Workday` - Workday
     * * `ServiceNow` - ServiceNow
     * * `Pardot` - Pardot
     * * `Copper` - Copper
     * * `Front` - Front
     * * `ChartMogul` - ChartMogul
     * * `Zuora` - Zuora
     * * `Paddle` - Paddle
     * * `CircleCI` - CircleCI
     * * `CockroachDB` - CockroachDB
     * * `Firebase` - Firebase
     * * `AzureBlob` - AzureBlob
     * * `GoogleDrive` - GoogleDrive
     * * `OneDrive` - OneDrive
     * * `SharePoint` - SharePoint
     * * `Box` - Box
     * * `SFTP` - SFTP
     * * `MicrosoftTeams` - MicrosoftTeams
     * * `Aircall` - Aircall
     * * `Webflow` - Webflow
     * * `Okta` - Okta
     * * `Auth0` - Auth0
     * * `Productboard` - Productboard
     * * `Smartsheet` - Smartsheet
     * * `Wrike` - Wrike
     * * `Plaid` - Plaid
     * * `SurveyMonkey` - SurveyMonkey
     * * `Eventbrite` - Eventbrite
     * * `RingCentral` - RingCentral
     * * `Twilio` - Twilio
     * * `Freshsales` - Freshsales
     * * `Shortcut` - Shortcut
     * * `ConvertKit` - ConvertKit
     * * `Drip` - Drip
     * * `CampaignMonitor` - CampaignMonitor
     * * `MailerLite` - MailerLite
     * * `Omnisend` - Omnisend
     * * `Brevo` - Brevo
     * * `Postmark` - Postmark
     * * `Granola` - Granola
     * * `BuildBetter` - BuildBetter
     * * `Convex` - Convex
     * * `ClickHouse` - ClickHouse
     * * `Plain` - Plain
     * * `Resend` - Resend
     * * `PgAnalyze` - PgAnalyze
     * * `WorkOS` - WorkOS
     * * `AmazonS3` - AmazonS3
     * * `GoogleCloudStorage` - GoogleCloudStorage
     * * `Databricks` - Databricks
     * * `Dynamics365` - Dynamics365
     * * `SalesforceMarketingCloud` - SalesforceMarketingCloud
     * * `Db2` - Db2
     * * `Heap` - Heap
     * * `AdobeAnalytics` - AdobeAnalytics
     * * `Matomo` - Matomo
     * * `Optimizely` - Optimizely
     * * `Adyen` - Adyen
     * * `GoCardless` - GoCardless
     * * `Mollie` - Mollie
     * * `CheckoutCom` - CheckoutCom
     * * `Branch` - Branch
     * * `Criteo` - Criteo
     * * `Outbrain` - Outbrain
     * * `Taboola` - Taboola
     * * `AdRoll` - AdRoll
     * * `DisplayVideo360` - DisplayVideo360
     * * `GoogleAdManager` - GoogleAdManager
     * * `CampaignManager360` - CampaignManager360
     * * `SearchAds360` - SearchAds360
     * * `AdobeCommerce` - AdobeCommerce
     * * `AmazonSellingPartner` - AmazonSellingPartner
     * * `Ebay` - Ebay
     * * `Commercetools` - Commercetools
     * * `LightspeedRetail` - LightspeedRetail
     * * `ShipStation` - ShipStation
     * * `ConstantContact` - ConstantContact
     * * `Mailgun` - Mailgun
     * * `Eloqua` - Eloqua
     * * `Sailthru` - Sailthru
     * * `Ortto` - Ortto
     * * `Attentive` - Attentive
     * * `Kustomer` - Kustomer
     * * `Dixa` - Dixa
     * * `Gladly` - Gladly
     * * `Qualtrics` - Qualtrics
     * * `Delighted` - Delighted
     * * `AzureDevOps` - AzureDevOps
     * * `Rollbar` - Rollbar
     * * `Opsgenie` - Opsgenie
     * * `IncidentIo` - IncidentIo
     * * `Pingdom` - Pingdom
     * * `Cloudflare` - Cloudflare
     * * `CosmosDB` - CosmosDB
     * * `PlanetScale` - PlanetScale
     * * `SapHana` - SapHana
     * * `Rippling` - Rippling
     * * `HiBob` - HiBob
     * * `Personio` - Personio
     * * `Deel` - Deel
     * * `AdpWorkforceNow` - AdpWorkforceNow
     * * `Paylocity` - Paylocity
     * * `Gusto` - Gusto
     * * `CultureAmp` - CultureAmp
     * * `Lattice` - Lattice
     * * `SageIntacct` - SageIntacct
     * * `FreshBooks` - FreshBooks
     * * `Expensify` - Expensify
     * * `Ramp` - Ramp
     * * `Brex` - Brex
     * * `Coupa` - Coupa
     * * `SapConcur` - SapConcur
     * * `Apollo` - Apollo
     * * `Crunchbase` - Crunchbase
     * * `ZoomInfo` - ZoomInfo
     * * `Clari` - Clari
     * * `Chorus` - Chorus
     * * `Coda` - Coda
     * * `Guru` - Guru
     * * `Dropbox` - Dropbox
     * * `Docusign` - Docusign
     * * `PandaDoc` - PandaDoc
     * * `SapErp` - SapErp
     * * `SapSuccessFactors` - SapSuccessFactors
     * * `OracleEbs` - OracleEbs
     * * `OracleFusion` - OracleFusion
     * * `AmazonSNS` - AmazonSNS
     * * `AmazonEventBridge` - AmazonEventBridge
     * * `AmazonSQS` - AmazonSQS
     * * `AmazonKinesis` - AmazonKinesis
     * * `AmazonCloudWatch` - AmazonCloudWatch
     * * `OpenAIAds` - OpenAIAds
     * * `OneHundredMs` - OneHundredMs
     * * `SevenShifts` - SevenShifts
     * * `AcuityScheduling` - AcuityScheduling
     * * `AgileCRM` - AgileCRM
     * * `Aha` - Aha
     * * `Airbyte` - Airbyte
     * * `Akeneo` - Akeneo
     * * `Algolia` - Algolia
     * * `AlpacaBrokerAPI` - AlpacaBrokerAPI
     * * `ApifyDataset` - ApifyDataset
     * * `Appcues` - Appcues
     * * `Appfigures` - Appfigures
     * * `Appfollow` - Appfollow
     * * `Apptivo` - Apptivo
     * * `AssemblyAI` - AssemblyAI
     * * `Awin` - Awin
     * * `AwsCloudTrail` - AwsCloudTrail
     * * `AzureTableStorage` - AzureTableStorage
     * * `Babelforce` - Babelforce
     * * `Basecamp` - Basecamp
     * * `Beamer` - Beamer
     * * `BigMailer` - BigMailer
     * * `Bluetally` - Bluetally
     * * `BoldSign` - BoldSign
     * * `BreezyHR` - BreezyHR
     * * `Bugsnag` - Bugsnag
     * * `Buildkite` - Buildkite
     * * `Bunny` - Bunny
     * * `Buzzsprout` - Buzzsprout
     * * `CalCom` - CalCom
     * * `CallRail` - CallRail
     * * `Campayn` - Campayn
     * * `Canny` - Canny
     * * `CapsuleCRM` - CapsuleCRM
     * * `CaptainData` - CaptainData
     * * `CartCom` - CartCom
     * * `CastorEDC` - CastorEDC
     * * `Chameleon` - Chameleon
     * * `Chargedesk` - Chargedesk
     * * `Chargify` - Chargify
     * * `Chift` - Chift
     * * `Churnkey` - Churnkey
     * * `Cin7` - Cin7
     * * `CiscoMeraki` - CiscoMeraki
     * * `Clazar` - Clazar
     * * `Clockify` - Clockify
     * * `Clockodo` - Clockodo
     * * `Cloudbeds` - Cloudbeds
     * * `Coassemble` - Coassemble
     * * `Codefresh` - Codefresh
     * * `Concord` - Concord
     * * `ConfigCat` - ConfigCat
     * * `Couchbase` - Couchbase
     * * `Curve` - Curve
     * * `Customerly` - Customerly
     * * `Datascope` - Datascope
     * * `Dbt` - Dbt
     * * `Deputy` - Deputy
     * * `DevinAI` - DevinAI
     * * `Docuseal` - Docuseal
     * * `Dolibarr` - Dolibarr
     * * `Dremio` - Dremio
     * * `DropboxSign` - DropboxSign
     * * `Dwolla` - Dwolla
     * * `EConomic` - EConomic
     * * `Easypost` - Easypost
     * * `Easypromos` - Easypromos
     * * `Elasticemail` - Elasticemail
     * * `EmailOctopus` - EmailOctopus
     * * `EmploymentHero` - EmploymentHero
     * * `Encharge` - Encharge
     * * `Eventee` - Eventee
     * * `Eventzilla` - Eventzilla
     * * `Everhour` - Everhour
     * * `EZOfficeInventory` - EZOfficeInventory
     * * `Factorial` - Factorial
     * * `Fastbill` - Fastbill
     * * `Fastly` - Fastly
     * * `Fauna` - Fauna
     * * `Feishu` - Feishu
     * * `Fillout` - Fillout
     * * `Finage` - Finage
     * * `Firebolt` - Firebolt
     * * `FireHydrant` - FireHydrant
     * * `Fleetio` - Fleetio
     * * `Flexmail` - Flexmail
     * * `Flexport` - Flexport
     * * `FloatApp` - FloatApp
     * * `Flowlu` - Flowlu
     * * `Formbricks` - Formbricks
     * * `FreeAgent` - FreeAgent
     * * `Freightview` - Freightview
     * * `Freshcaller` - Freshcaller
     * * `Freshchat` - Freshchat
     * * `Freshservice` - Freshservice
     * * `Fulcrum` - Fulcrum
     * * `GainsightPx` - GainsightPx
     * * `GitBook` - GitBook
     * * `Glassfrog` - Glassfrog
     * * `Goldcast` - Goldcast
     * * `GoLogin` - GoLogin
     * * `Grafana` - Grafana
     * * `GreytHr` - GreytHr
     * * `Gridly` - Gridly
     * * `Harness` - Harness
     * * `Height` - Height
     * * `Hellobaton` - Hellobaton
     * * `HighLevel` - HighLevel
     * * `HoorayHR` - HoorayHR
     * * `Hubplanner` - Hubplanner
     * * `Humanitix` - Humanitix
     * * `Huntr` - Huntr
     * * `Inflowinventory` - Inflowinventory
     * * `InforNexus` - InforNexus
     * * `Insightful` - Insightful
     * * `Insightly` - Insightly
     * * `Instantly` - Instantly
     * * `Instatus` - Instatus
     * * `Intruder` - Intruder
     * * `Invoiced` - Invoiced
     * * `Invoiceninja` - Invoiceninja
     * * `JamfPro` - JamfPro
     * * `JobNimbus` - JobNimbus
     * * `Jotform` - Jotform
     * * `JudgeMeReviews` - JudgeMeReviews
     * * `JustCall` - JustCall
     * * `JustSift` - JustSift
     * * `K6Cloud` - K6Cloud
     * * `Katana` - Katana
     * * `Keka` - Keka
     * * `Kisi` - Kisi
     * * `Kissmetrics` - Kissmetrics
     * * `Klarna` - Klarna
     * * `Klaus` - Klaus
     * * `Lago` - Lago
     * * `Leadfeeder` - Leadfeeder
     * * `Lemlist` - Lemlist
     * * `LessAnnoyingCRM` - LessAnnoyingCRM
     * * `LinkedinPages` - LinkedinPages
     * * `Linkrunner` - Linkrunner
     * * `Linnworks` - Linnworks
     * * `Lob` - Lob
     * * `Lokalise` - Lokalise
     * * `Looker` - Looker
     * * `Luma` - Luma
     * * `MailerSend` - MailerSend
     * * `Mailosaur` - Mailosaur
     * * `Mailtrap` - Mailtrap
     * * `Mantle` - Mantle
     * * `Mention` - Mention
     * * `MercadoAds` - MercadoAds
     * * `Merge` - Merge
     * * `Metabase` - Metabase
     * * `Metricool` - Metricool
     * * `MicrosoftDataverse` - MicrosoftDataverse
     * * `MicrosoftEntraId` - MicrosoftEntraId
     * * `MicrosoftLists` - MicrosoftLists
     * * `Miro` - Miro
     * * `Missive` - Missive
     * * `MixMax` - MixMax
     * * `Mode` - Mode
     * * `Mux` - Mux
     * * `MyHours` - MyHours
     * * `N8n` - N8n
     * * `Navan` - Navan
     * * `NebiusAI` - NebiusAI
     * * `Nexiopay` - Nexiopay
     * * `NinjaOneRMM` - NinjaOneRMM
     * * `NoCRM` - NoCRM
     * * `NorthpassLMS` - NorthpassLMS
     * * `Nutshell` - Nutshell
     * * `Nylas` - Nylas
     * * `Oncehub` - Oncehub
     * * `Onepagecrm` - Onepagecrm
     * * `OneSignal` - OneSignal
     * * `Onfleet` - Onfleet
     * * `OpinionStage` - OpinionStage
     * * `OPUSWatch` - OPUSWatch
     * * `Orb` - Orb
     * * `Orbit` - Orbit
     * * `Oura` - Oura
     * * `Oveit` - Oveit
     * * `PabblySubscriptionsBilling` - PabblySubscriptionsBilling
     * * `Paperform` - Paperform
     * * `Papersign` - Papersign
     * * `Partnerize` - Partnerize
     * * `PartnerStack` - PartnerStack
     * * `PayFit` - PayFit
     * * `Paystack` - Paystack
     * * `Pennylane` - Pennylane
     * * `Perk` - Perk
     * * `PersistIq` - PersistIq
     * * `Persona` - Persona
     * * `Phyllo` - Phyllo
     * * `Picqer` - Picqer
     * * `Pipeliner` - Pipeliner
     * * `PivotalTracker` - PivotalTracker
     * * `Piwik` - Piwik
     * * `Planhat` - Planhat
     * * `Plausible` - Plausible
     * * `Poplar` - Poplar
     * * `PrestaShop` - PrestaShop
     * * `Pretix` - Pretix
     * * `Primetric` - Primetric
     * * `Printify` - Printify
     * * `Productive` - Productive
     * * `Pylon` - Pylon
     * * `Qonto` - Qonto
     * * `Qualaroo` - Qualaroo
     * * `Railz` - Railz
     * * `RDStationMarketing` - RDStationMarketing
     * * `Recruitee` - Recruitee
     * * `Reddit` - Reddit
     * * `ReferralHero` - ReferralHero
     * * `RentCast` - RentCast
     * * `Repairshopr` - Repairshopr
     * * `ReplyIo` - ReplyIo
     * * `RetailExpress` - RetailExpress
     * * `Retently` - Retently
     * * `RevolutMerchant` - RevolutMerchant
     * * `RocketChat` - RocketChat
     * * `Rocketlane` - Rocketlane
     * * `Rootly` - Rootly
     * * `Ruddr` - Ruddr
     * * `SafetyCulture` - SafetyCulture
     * * `SageHR` - SageHR
     * * `Salesflare` - Salesflare
     * * `SAPFieldglass` - SAPFieldglass
     * * `SavvyCal` - SavvyCal
     * * `Secoda` - Secoda
     * * `Segment` - Segment
     * * `Sendowl` - Sendowl
     * * `SendPulse` - SendPulse
     * * `Senseforce` - Senseforce
     * * `Serpstat` - Serpstat
     * * `Sharetribe` - Sharetribe
     * * `Shippo` - Shippo
     * * `ShopWired` - ShopWired
     * * `Shortio` - Shortio
     * * `Shutterstock` - Shutterstock
     * * `SigmaComputing` - SigmaComputing
     * * `SignNow` - SignNow
     * * `SimpleCast` - SimpleCast
     * * `Simplesat` - Simplesat
     * * `Smaily` - Smaily
     * * `SmartEngage` - SmartEngage
     * * `Smartreach` - Smartreach
     * * `Smartwaiver` - Smartwaiver
     * * `SolarwindsServiceDesk` - SolarwindsServiceDesk
     * * `SonarCloud` - SonarCloud
     * * `SparkPost` - SparkPost
     * * `SplitIo` - SplitIo
     * * `SpotifyAds` - SpotifyAds
     * * `SpotlerCRM` - SpotlerCRM
     * * `Squarespace` - Squarespace
     * * `Statsig` - Statsig
     * * `Statuspage` - Statuspage
     * * `Stigg` - Stigg
     * * `Strava` - Strava
     * * `SurveySparrow` - SurveySparrow
     * * `Survicate` - Survicate
     * * `Svix` - Svix
     * * `Systeme` - Systeme
     * * `Tavus` - Tavus
     * * `Teamtailor` - Teamtailor
     * * `Teamwork` - Teamwork
     * * `Tempo` - Tempo
     * * `Testrail` - Testrail
     * * `Thinkific` - Thinkific
     * * `ThinkificCourses` - ThinkificCourses
     * * `ThriveLearning` - ThriveLearning
     * * `Ticketmaster` - Ticketmaster
     * * `TicketTailor` - TicketTailor
     * * `TickTick` - TickTick
     * * `Timely` - Timely
     * * `Tinyemail` - Tinyemail
     * * `Todoist` - Todoist
     * * `Toggl` - Toggl
     * * `TrackPMS` - TrackPMS
     * * `Tremendous` - Tremendous
     * * `TrustPilot` - TrustPilot
     * * `Twitter` - Twitter
     * * `TyntecSMS` - TyntecSMS
     * * `Unleash` - Unleash
     * * `UpPromote` - UpPromote
     * * `Uptick` - Uptick
     * * `Uservoice` - Uservoice
     * * `Vantage` - Vantage
     * * `Veeqo` - Veeqo
     * * `Vercel` - Vercel
     * * `VismaEconomic` - VismaEconomic
     * * `VWO` - VWO
     * * `Waiteraid` - Waiteraid
     * * `Wasabi` - Wasabi
     * * `WhenIWork` - WhenIWork
     * * `Wordpress` - Wordpress
     * * `Workable` - Workable
     * * `Workflowmax` - Workflowmax
     * * `Workramp` - Workramp
     * * `Wufoo` - Wufoo
     * * `Xsolla` - Xsolla
     * * `YandexMetrica` - YandexMetrica
     * * `Yotpo` - Yotpo
     * * `Ynab` - Ynab
     * * `Younium` - Younium
     * * `YouSign` - YouSign
     * * `YoutubeData` - YoutubeData
     * * `ZapierSupportedStorage` - ZapierSupportedStorage
     * * `ZapSign` - ZapSign
     * * `ZendeskSell` - ZendeskSell
     * * `ZendeskSunshine` - ZendeskSunshine
     * * `Zenefits` - Zenefits
     * * `Zenloop` - Zenloop
     * * `ZohoAnalytics` - ZohoAnalytics
     * * `ZohoBigin` - ZohoBigin
     * * `ZohoBilling` - ZohoBilling
     * * `ZohoBooks` - ZohoBooks
     * * `ZohoCampaign` - ZohoCampaign
     * * `ZohoDesk` - ZohoDesk
     * * `ZohoExpense` - ZohoExpense
     * * `ZohoInventory` - ZohoInventory
     * * `ZohoInvoice` - ZohoInvoice
     * * `ZonkaFeedback` - ZonkaFeedback
     * * `AlphaVantage` - AlphaVantage
     * * `Aviationstack` - Aviationstack
     * * `Bitly` - Bitly
     * * `Blogger` - Blogger
     * * `Breezometer` - Breezometer
     * * `CareQualityCommission` - CareQualityCommission
     * * `Cimis` - Cimis
     * * `CoinApi` - CoinApi
     * * `CoinGecko` - CoinGecko
     * * `CoinMarketCap` - CoinMarketCap
     * * `DingConnect` - DingConnect
     * * `Dockerhub` - Dockerhub
     * * `ExchangeRatesApi` - ExchangeRatesApi
     * * `FinancialModelling` - FinancialModelling
     * * `Finnhub` - Finnhub
     * * `Finnworlds` - Finnworlds
     * * `Giphy` - Giphy
     * * `Gmail` - Gmail
     * * `GNews` - GNews
     * * `GoogleCalendar` - GoogleCalendar
     * * `GoogleClassroom` - GoogleClassroom
     * * `GoogleDirectory` - GoogleDirectory
     * * `GoogleForms` - GoogleForms
     * * `GooglePageSpeedInsights` - GooglePageSpeedInsights
     * * `GoogleTasks` - GoogleTasks
     * * `GoogleWebfonts` - GoogleWebfonts
     * * `GoogleWorkspaceAdminReports` - GoogleWorkspaceAdminReports
     * * `HuggingFace` - HuggingFace
     * * `IlluminaBasespace` - IlluminaBasespace
     * * `Imagga` - Imagga
     * * `Interzoid` - Interzoid
     * * `IP2Whois` - IP2Whois
     * * `KYVE` - KYVE
     * * `Marketstack` - Marketstack
     * * `Mendeley` - Mendeley
     * * `Nasa` - Nasa
     * * `NewYorkTimes` - NewYorkTimes
     * * `NewsApi` - NewsApi
     * * `NewsData` - NewsData
     * * `OpenDataDc` - OpenDataDc
     * * `OpenExchangeRates` - OpenExchangeRates
     * * `OpenAQ` - OpenAQ
     * * `OpenFDA` - OpenFDA
     * * `OpenWeather` - OpenWeather
     * * `Outlook` - Outlook
     * * `Perigon` - Perigon
     * * `Pexels` - Pexels
     * * `Pocket` - Pocket
     * * `Polygon` - Polygon
     * * `PyPI` - PyPI
     * * `Recreation` - Recreation
     * * `RKICovid` - RKICovid
     * * `Rss` - Rss
     * * `SimFin` - SimFin
     * * `StockData` - StockData
     * * `Guardian` - Guardian
     * * `TMDb` - TMDb
     * * `TVMaze` - TVMaze
     * * `TwelveData` - TwelveData
     * * `Ubidots` - Ubidots
     * * `USCensus` - USCensus
     * * `Watchmode` - Watchmode
     * * `WikipediaPageviews` - WikipediaPageviews
     * * `YahooFinance` - YahooFinance
     * * `Clarifai` - Clarifai
     * * `Adapty` - Adapty
     * * `Braintrust` - Braintrust
     * * `StreamElements` - StreamElements
     * * `Streamlabs` - Streamlabs
     * * `Datorama` - Datorama
     * * `Ahrefs` - Ahrefs
     * * `Lightfield` - Lightfield
     * * `Appstack` - Appstack
     * * `Razorpay` - Razorpay
     * * `Neon` - Neon
     * * `NewRelic` - NewRelic
     * * `Custom` - Custom
     * * `Tile38` - Tile38
     * * `Chatwoot` - Chatwoot
     * * `Sanity` - Sanity
     * * `Metronome` - Metronome
     * * `Jobber` - Jobber
     * * `Knock` - Knock
     * * `Leexi` - Leexi
     * * `RB2B` - RB2B
     * * `Superwall` - Superwall
     * * `Liana` - Liana
     * * `TawkTo` - TawkTo
     * * `Hightouch` - Hightouch
     * * `LemonSqueezy` - LemonSqueezy
     * * `Ikas` - Ikas
     * * `Talkwalker` - Talkwalker
     * * `NextdoorAds` - NextdoorAds
     * * `AppLovin` - AppLovin
     * * `Baserow` - Baserow
     * * `Plunk` - Plunk
     * * `Dub` - Dub
     * * `AirOps` - AirOps
     * * `Podium` - Podium
     * * `Loops` - Loops
     * * `Redis` - Redis
     * * `Mercury` - Mercury
     * * `Gojiberry` - Gojiberry
     * * `Teachable` - Teachable
     * * `PeecAI` - PeecAI
     * * `Healthchecks` - Healthchecks
     * * `Impact` - Impact
     * * `AikidoSecurity` - AikidoSecurity
     * * `Alguna` - Alguna
     * * `Anthropic` - Anthropic
     * * `Appwrite` - Appwrite
     * * `BlandAI` - BlandAI
     * * `BrowseAI` - BrowseAI
     * * `BrowserUse` - BrowserUse
     * * `ChartHop` - ChartHop
     * * `Cody` - Cody
     * * `Cursor` - Cursor
     * * `Decagon` - Decagon
     * * `Deepgram` - Deepgram
     * * `ElevenLabs` - ElevenLabs
     * * `Harvey` - Harvey
     * * `Hyperspell` - Hyperspell
     * * `Langfuse` - Langfuse
     * * `LingoDev` - LingoDev
     * * `M3ter` - M3ter
     * * `Maxio` - Maxio
     * * `Metorial` - Metorial
     * * `OpenRouter` - OpenRouter
     * * `TogetherAI` - TogetherAI
     * * `Vapi` - Vapi
     * * `Vespa` - Vespa
     * * `Writesonic` - Writesonic */
    source_type: ExternalDataSourceTypeEnumApi
    /** Source config as flat keys. For source_type 'Custom': 'manifest_json' (a stringified RESTAPIConfig describing client.base_url, auth, and resources) plus the credential for the manifest's declared auth type — 'auth_token' (bearer), 'auth_api_key' (api_key), or 'auth_password' (http_basic). Secrets stay in these auth_* keys, never inline in the manifest. */
    payload?: SourcePreviewRequestApiPayload
    /** Which manifest resource (table) to read a sample from — one of the resource names in manifest_json. */
    resource_name: string
    /**
     * Maximum sample rows to return (1–50). Defaults to 10.
     * @minimum 1
     * @maximum 50
     */
    limit?: number
}

export type SourcePreviewResponseApiRowsItem = { [key: string]: unknown }

export interface SourcePreviewColumnApi {
    /** Column name as it appears in the previewed rows. */
    name: string
    /** JSON type inferred from the first non-null value: string, integer, number, boolean, object, array, or null. */
    type: string
}

export interface SourcePreviewResponseApi {
    /** Up to `limit` sample rows, after data_selector extraction — the raw records the sync would ingest. */
    rows: SourcePreviewResponseApiRowsItem[]
    /** Number of sample rows returned (≤ limit). */
    row_count: number
    /** Columns observed across the sample rows, each with an inferred JSON type. */
    columns: SourcePreviewColumnApi[]
    /**
     * Set when the live read failed (e.g. the host was unreachable or returned an auth error); rows is then empty. Manifest, validation, and SSRF problems return HTTP 400 instead of populating this field.
     * @nullable
     */
    error: string | null
}

/**
 * Connection details as flat keys for the source_type (discover required fields with the wizard tool). Prefer references over raw secrets: pass {'credential_id': <id>} referencing the connection details the user stored via the connect-link page (discover ids with the stored_credentials endpoint) — they are merged in server-side and deleted once consumed. An already-connected OAuth integration can be passed via its id key instead (e.g. {'hubspot_integration_id': 123}). For source_type 'Custom' (a user-defined REST API) the keys are 'manifest_json' (a stringified RESTAPIConfig describing client.base_url, auth, and resources) plus the credential for the auth type the manifest declares — 'auth_token' (bearer), 'auth_api_key' (api_key), or 'auth_password' (http_basic); keep secrets in these auth_* keys, never inline in the manifest. A 'schemas' array is NOT required — all discovered tables are enabled automatically with sensible sync defaults.
 */
export type SourceSetupApiPayload = { [key: string]: unknown }

export interface SourceSetupApi {
    /** The source type to set up (e.g. 'Stripe', 'Postgres', 'Hubspot').
     *
     * * `Ashby` - Ashby
     * * `Supabase` - Supabase
     * * `CustomerIO` - CustomerIO
     * * `Github` - Github
     * * `Stripe` - Stripe
     * * `Hubspot` - Hubspot
     * * `Postgres` - Postgres
     * * `Zendesk` - Zendesk
     * * `Snowflake` - Snowflake
     * * `Salesforce` - Salesforce
     * * `MySQL` - MySQL
     * * `MongoDB` - MongoDB
     * * `MSSQL` - MSSQL
     * * `Vitally` - Vitally
     * * `BigQuery` - BigQuery
     * * `Chargebee` - Chargebee
     * * `Clerk` - Clerk
     * * `GoogleAds` - GoogleAds
     * * `GoogleSearchConsole` - GoogleSearchConsole
     * * `TemporalIO` - TemporalIO
     * * `DoIt` - DoIt
     * * `GoogleSheets` - GoogleSheets
     * * `MetaAds` - MetaAds
     * * `Klaviyo` - Klaviyo
     * * `Mailchimp` - Mailchimp
     * * `Braze` - Braze
     * * `Mailjet` - Mailjet
     * * `Redshift` - Redshift
     * * `Polar` - Polar
     * * `RevenueCat` - RevenueCat
     * * `LinkedinAds` - LinkedinAds
     * * `RedditAds` - RedditAds
     * * `TikTokAds` - TikTokAds
     * * `BingAds` - BingAds
     * * `Shopify` - Shopify
     * * `Attio` - Attio
     * * `SnapchatAds` - SnapchatAds
     * * `Linear` - Linear
     * * `Intercom` - Intercom
     * * `Amplitude` - Amplitude
     * * `Mixpanel` - Mixpanel
     * * `Jira` - Jira
     * * `ActiveCampaign` - ActiveCampaign
     * * `Marketo` - Marketo
     * * `Adjust` - Adjust
     * * `AppsFlyer` - AppsFlyer
     * * `Freshdesk` - Freshdesk
     * * `GoogleAnalytics` - GoogleAnalytics
     * * `Pipedrive` - Pipedrive
     * * `SendGrid` - SendGrid
     * * `Slack` - Slack
     * * `PagerDuty` - PagerDuty
     * * `Asana` - Asana
     * * `Notion` - Notion
     * * `Airtable` - Airtable
     * * `Greenhouse` - Greenhouse
     * * `BambooHR` - BambooHR
     * * `Lever` - Lever
     * * `GitLab` - GitLab
     * * `Datadog` - Datadog
     * * `Sentry` - Sentry
     * * `Pendo` - Pendo
     * * `FullStory` - FullStory
     * * `AmazonAds` - AmazonAds
     * * `PinterestAds` - PinterestAds
     * * `AppleSearchAds` - AppleSearchAds
     * * `QuickBooks` - QuickBooks
     * * `Xero` - Xero
     * * `NetSuite` - NetSuite
     * * `WooCommerce` - WooCommerce
     * * `BigCommerce` - BigCommerce
     * * `PayPal` - PayPal
     * * `Square` - Square
     * * `Zoom` - Zoom
     * * `Trello` - Trello
     * * `Monday` - Monday
     * * `ClickUp` - ClickUp
     * * `Confluence` - Confluence
     * * `Recurly` - Recurly
     * * `SalesLoft` - SalesLoft
     * * `Outreach` - Outreach
     * * `Gong` - Gong
     * * `Calendly` - Calendly
     * * `Typeform` - Typeform
     * * `Iterable` - Iterable
     * * `ZohoCRM` - ZohoCRM
     * * `Close` - Close
     * * `Oracle` - Oracle
     * * `DynamoDB` - DynamoDB
     * * `Elasticsearch` - Elasticsearch
     * * `Kafka` - Kafka
     * * `LaunchDarkly` - LaunchDarkly
     * * `Braintree` - Braintree
     * * `Recharge` - Recharge
     * * `HelpScout` - HelpScout
     * * `Gorgias` - Gorgias
     * * `Instagram` - Instagram
     * * `YouTubeAnalytics` - YouTubeAnalytics
     * * `FacebookPages` - FacebookPages
     * * `TwitterAds` - TwitterAds
     * * `Workday` - Workday
     * * `ServiceNow` - ServiceNow
     * * `Pardot` - Pardot
     * * `Copper` - Copper
     * * `Front` - Front
     * * `ChartMogul` - ChartMogul
     * * `Zuora` - Zuora
     * * `Paddle` - Paddle
     * * `CircleCI` - CircleCI
     * * `CockroachDB` - CockroachDB
     * * `Firebase` - Firebase
     * * `AzureBlob` - AzureBlob
     * * `GoogleDrive` - GoogleDrive
     * * `OneDrive` - OneDrive
     * * `SharePoint` - SharePoint
     * * `Box` - Box
     * * `SFTP` - SFTP
     * * `MicrosoftTeams` - MicrosoftTeams
     * * `Aircall` - Aircall
     * * `Webflow` - Webflow
     * * `Okta` - Okta
     * * `Auth0` - Auth0
     * * `Productboard` - Productboard
     * * `Smartsheet` - Smartsheet
     * * `Wrike` - Wrike
     * * `Plaid` - Plaid
     * * `SurveyMonkey` - SurveyMonkey
     * * `Eventbrite` - Eventbrite
     * * `RingCentral` - RingCentral
     * * `Twilio` - Twilio
     * * `Freshsales` - Freshsales
     * * `Shortcut` - Shortcut
     * * `ConvertKit` - ConvertKit
     * * `Drip` - Drip
     * * `CampaignMonitor` - CampaignMonitor
     * * `MailerLite` - MailerLite
     * * `Omnisend` - Omnisend
     * * `Brevo` - Brevo
     * * `Postmark` - Postmark
     * * `Granola` - Granola
     * * `BuildBetter` - BuildBetter
     * * `Convex` - Convex
     * * `ClickHouse` - ClickHouse
     * * `Plain` - Plain
     * * `Resend` - Resend
     * * `PgAnalyze` - PgAnalyze
     * * `WorkOS` - WorkOS
     * * `AmazonS3` - AmazonS3
     * * `GoogleCloudStorage` - GoogleCloudStorage
     * * `Databricks` - Databricks
     * * `Dynamics365` - Dynamics365
     * * `SalesforceMarketingCloud` - SalesforceMarketingCloud
     * * `Db2` - Db2
     * * `Heap` - Heap
     * * `AdobeAnalytics` - AdobeAnalytics
     * * `Matomo` - Matomo
     * * `Optimizely` - Optimizely
     * * `Adyen` - Adyen
     * * `GoCardless` - GoCardless
     * * `Mollie` - Mollie
     * * `CheckoutCom` - CheckoutCom
     * * `Branch` - Branch
     * * `Criteo` - Criteo
     * * `Outbrain` - Outbrain
     * * `Taboola` - Taboola
     * * `AdRoll` - AdRoll
     * * `DisplayVideo360` - DisplayVideo360
     * * `GoogleAdManager` - GoogleAdManager
     * * `CampaignManager360` - CampaignManager360
     * * `SearchAds360` - SearchAds360
     * * `AdobeCommerce` - AdobeCommerce
     * * `AmazonSellingPartner` - AmazonSellingPartner
     * * `Ebay` - Ebay
     * * `Commercetools` - Commercetools
     * * `LightspeedRetail` - LightspeedRetail
     * * `ShipStation` - ShipStation
     * * `ConstantContact` - ConstantContact
     * * `Mailgun` - Mailgun
     * * `Eloqua` - Eloqua
     * * `Sailthru` - Sailthru
     * * `Ortto` - Ortto
     * * `Attentive` - Attentive
     * * `Kustomer` - Kustomer
     * * `Dixa` - Dixa
     * * `Gladly` - Gladly
     * * `Qualtrics` - Qualtrics
     * * `Delighted` - Delighted
     * * `AzureDevOps` - AzureDevOps
     * * `Rollbar` - Rollbar
     * * `Opsgenie` - Opsgenie
     * * `IncidentIo` - IncidentIo
     * * `Pingdom` - Pingdom
     * * `Cloudflare` - Cloudflare
     * * `CosmosDB` - CosmosDB
     * * `PlanetScale` - PlanetScale
     * * `SapHana` - SapHana
     * * `Rippling` - Rippling
     * * `HiBob` - HiBob
     * * `Personio` - Personio
     * * `Deel` - Deel
     * * `AdpWorkforceNow` - AdpWorkforceNow
     * * `Paylocity` - Paylocity
     * * `Gusto` - Gusto
     * * `CultureAmp` - CultureAmp
     * * `Lattice` - Lattice
     * * `SageIntacct` - SageIntacct
     * * `FreshBooks` - FreshBooks
     * * `Expensify` - Expensify
     * * `Ramp` - Ramp
     * * `Brex` - Brex
     * * `Coupa` - Coupa
     * * `SapConcur` - SapConcur
     * * `Apollo` - Apollo
     * * `Crunchbase` - Crunchbase
     * * `ZoomInfo` - ZoomInfo
     * * `Clari` - Clari
     * * `Chorus` - Chorus
     * * `Coda` - Coda
     * * `Guru` - Guru
     * * `Dropbox` - Dropbox
     * * `Docusign` - Docusign
     * * `PandaDoc` - PandaDoc
     * * `SapErp` - SapErp
     * * `SapSuccessFactors` - SapSuccessFactors
     * * `OracleEbs` - OracleEbs
     * * `OracleFusion` - OracleFusion
     * * `AmazonSNS` - AmazonSNS
     * * `AmazonEventBridge` - AmazonEventBridge
     * * `AmazonSQS` - AmazonSQS
     * * `AmazonKinesis` - AmazonKinesis
     * * `AmazonCloudWatch` - AmazonCloudWatch
     * * `OpenAIAds` - OpenAIAds
     * * `OneHundredMs` - OneHundredMs
     * * `SevenShifts` - SevenShifts
     * * `AcuityScheduling` - AcuityScheduling
     * * `AgileCRM` - AgileCRM
     * * `Aha` - Aha
     * * `Airbyte` - Airbyte
     * * `Akeneo` - Akeneo
     * * `Algolia` - Algolia
     * * `AlpacaBrokerAPI` - AlpacaBrokerAPI
     * * `ApifyDataset` - ApifyDataset
     * * `Appcues` - Appcues
     * * `Appfigures` - Appfigures
     * * `Appfollow` - Appfollow
     * * `Apptivo` - Apptivo
     * * `AssemblyAI` - AssemblyAI
     * * `Awin` - Awin
     * * `AwsCloudTrail` - AwsCloudTrail
     * * `AzureTableStorage` - AzureTableStorage
     * * `Babelforce` - Babelforce
     * * `Basecamp` - Basecamp
     * * `Beamer` - Beamer
     * * `BigMailer` - BigMailer
     * * `Bluetally` - Bluetally
     * * `BoldSign` - BoldSign
     * * `BreezyHR` - BreezyHR
     * * `Bugsnag` - Bugsnag
     * * `Buildkite` - Buildkite
     * * `Bunny` - Bunny
     * * `Buzzsprout` - Buzzsprout
     * * `CalCom` - CalCom
     * * `CallRail` - CallRail
     * * `Campayn` - Campayn
     * * `Canny` - Canny
     * * `CapsuleCRM` - CapsuleCRM
     * * `CaptainData` - CaptainData
     * * `CartCom` - CartCom
     * * `CastorEDC` - CastorEDC
     * * `Chameleon` - Chameleon
     * * `Chargedesk` - Chargedesk
     * * `Chargify` - Chargify
     * * `Chift` - Chift
     * * `Churnkey` - Churnkey
     * * `Cin7` - Cin7
     * * `CiscoMeraki` - CiscoMeraki
     * * `Clazar` - Clazar
     * * `Clockify` - Clockify
     * * `Clockodo` - Clockodo
     * * `Cloudbeds` - Cloudbeds
     * * `Coassemble` - Coassemble
     * * `Codefresh` - Codefresh
     * * `Concord` - Concord
     * * `ConfigCat` - ConfigCat
     * * `Couchbase` - Couchbase
     * * `Curve` - Curve
     * * `Customerly` - Customerly
     * * `Datascope` - Datascope
     * * `Dbt` - Dbt
     * * `Deputy` - Deputy
     * * `DevinAI` - DevinAI
     * * `Docuseal` - Docuseal
     * * `Dolibarr` - Dolibarr
     * * `Dremio` - Dremio
     * * `DropboxSign` - DropboxSign
     * * `Dwolla` - Dwolla
     * * `EConomic` - EConomic
     * * `Easypost` - Easypost
     * * `Easypromos` - Easypromos
     * * `Elasticemail` - Elasticemail
     * * `EmailOctopus` - EmailOctopus
     * * `EmploymentHero` - EmploymentHero
     * * `Encharge` - Encharge
     * * `Eventee` - Eventee
     * * `Eventzilla` - Eventzilla
     * * `Everhour` - Everhour
     * * `EZOfficeInventory` - EZOfficeInventory
     * * `Factorial` - Factorial
     * * `Fastbill` - Fastbill
     * * `Fastly` - Fastly
     * * `Fauna` - Fauna
     * * `Feishu` - Feishu
     * * `Fillout` - Fillout
     * * `Finage` - Finage
     * * `Firebolt` - Firebolt
     * * `FireHydrant` - FireHydrant
     * * `Fleetio` - Fleetio
     * * `Flexmail` - Flexmail
     * * `Flexport` - Flexport
     * * `FloatApp` - FloatApp
     * * `Flowlu` - Flowlu
     * * `Formbricks` - Formbricks
     * * `FreeAgent` - FreeAgent
     * * `Freightview` - Freightview
     * * `Freshcaller` - Freshcaller
     * * `Freshchat` - Freshchat
     * * `Freshservice` - Freshservice
     * * `Fulcrum` - Fulcrum
     * * `GainsightPx` - GainsightPx
     * * `GitBook` - GitBook
     * * `Glassfrog` - Glassfrog
     * * `Goldcast` - Goldcast
     * * `GoLogin` - GoLogin
     * * `Grafana` - Grafana
     * * `GreytHr` - GreytHr
     * * `Gridly` - Gridly
     * * `Harness` - Harness
     * * `Height` - Height
     * * `Hellobaton` - Hellobaton
     * * `HighLevel` - HighLevel
     * * `HoorayHR` - HoorayHR
     * * `Hubplanner` - Hubplanner
     * * `Humanitix` - Humanitix
     * * `Huntr` - Huntr
     * * `Inflowinventory` - Inflowinventory
     * * `InforNexus` - InforNexus
     * * `Insightful` - Insightful
     * * `Insightly` - Insightly
     * * `Instantly` - Instantly
     * * `Instatus` - Instatus
     * * `Intruder` - Intruder
     * * `Invoiced` - Invoiced
     * * `Invoiceninja` - Invoiceninja
     * * `JamfPro` - JamfPro
     * * `JobNimbus` - JobNimbus
     * * `Jotform` - Jotform
     * * `JudgeMeReviews` - JudgeMeReviews
     * * `JustCall` - JustCall
     * * `JustSift` - JustSift
     * * `K6Cloud` - K6Cloud
     * * `Katana` - Katana
     * * `Keka` - Keka
     * * `Kisi` - Kisi
     * * `Kissmetrics` - Kissmetrics
     * * `Klarna` - Klarna
     * * `Klaus` - Klaus
     * * `Lago` - Lago
     * * `Leadfeeder` - Leadfeeder
     * * `Lemlist` - Lemlist
     * * `LessAnnoyingCRM` - LessAnnoyingCRM
     * * `LinkedinPages` - LinkedinPages
     * * `Linkrunner` - Linkrunner
     * * `Linnworks` - Linnworks
     * * `Lob` - Lob
     * * `Lokalise` - Lokalise
     * * `Looker` - Looker
     * * `Luma` - Luma
     * * `MailerSend` - MailerSend
     * * `Mailosaur` - Mailosaur
     * * `Mailtrap` - Mailtrap
     * * `Mantle` - Mantle
     * * `Mention` - Mention
     * * `MercadoAds` - MercadoAds
     * * `Merge` - Merge
     * * `Metabase` - Metabase
     * * `Metricool` - Metricool
     * * `MicrosoftDataverse` - MicrosoftDataverse
     * * `MicrosoftEntraId` - MicrosoftEntraId
     * * `MicrosoftLists` - MicrosoftLists
     * * `Miro` - Miro
     * * `Missive` - Missive
     * * `MixMax` - MixMax
     * * `Mode` - Mode
     * * `Mux` - Mux
     * * `MyHours` - MyHours
     * * `N8n` - N8n
     * * `Navan` - Navan
     * * `NebiusAI` - NebiusAI
     * * `Nexiopay` - Nexiopay
     * * `NinjaOneRMM` - NinjaOneRMM
     * * `NoCRM` - NoCRM
     * * `NorthpassLMS` - NorthpassLMS
     * * `Nutshell` - Nutshell
     * * `Nylas` - Nylas
     * * `Oncehub` - Oncehub
     * * `Onepagecrm` - Onepagecrm
     * * `OneSignal` - OneSignal
     * * `Onfleet` - Onfleet
     * * `OpinionStage` - OpinionStage
     * * `OPUSWatch` - OPUSWatch
     * * `Orb` - Orb
     * * `Orbit` - Orbit
     * * `Oura` - Oura
     * * `Oveit` - Oveit
     * * `PabblySubscriptionsBilling` - PabblySubscriptionsBilling
     * * `Paperform` - Paperform
     * * `Papersign` - Papersign
     * * `Partnerize` - Partnerize
     * * `PartnerStack` - PartnerStack
     * * `PayFit` - PayFit
     * * `Paystack` - Paystack
     * * `Pennylane` - Pennylane
     * * `Perk` - Perk
     * * `PersistIq` - PersistIq
     * * `Persona` - Persona
     * * `Phyllo` - Phyllo
     * * `Picqer` - Picqer
     * * `Pipeliner` - Pipeliner
     * * `PivotalTracker` - PivotalTracker
     * * `Piwik` - Piwik
     * * `Planhat` - Planhat
     * * `Plausible` - Plausible
     * * `Poplar` - Poplar
     * * `PrestaShop` - PrestaShop
     * * `Pretix` - Pretix
     * * `Primetric` - Primetric
     * * `Printify` - Printify
     * * `Productive` - Productive
     * * `Pylon` - Pylon
     * * `Qonto` - Qonto
     * * `Qualaroo` - Qualaroo
     * * `Railz` - Railz
     * * `RDStationMarketing` - RDStationMarketing
     * * `Recruitee` - Recruitee
     * * `Reddit` - Reddit
     * * `ReferralHero` - ReferralHero
     * * `RentCast` - RentCast
     * * `Repairshopr` - Repairshopr
     * * `ReplyIo` - ReplyIo
     * * `RetailExpress` - RetailExpress
     * * `Retently` - Retently
     * * `RevolutMerchant` - RevolutMerchant
     * * `RocketChat` - RocketChat
     * * `Rocketlane` - Rocketlane
     * * `Rootly` - Rootly
     * * `Ruddr` - Ruddr
     * * `SafetyCulture` - SafetyCulture
     * * `SageHR` - SageHR
     * * `Salesflare` - Salesflare
     * * `SAPFieldglass` - SAPFieldglass
     * * `SavvyCal` - SavvyCal
     * * `Secoda` - Secoda
     * * `Segment` - Segment
     * * `Sendowl` - Sendowl
     * * `SendPulse` - SendPulse
     * * `Senseforce` - Senseforce
     * * `Serpstat` - Serpstat
     * * `Sharetribe` - Sharetribe
     * * `Shippo` - Shippo
     * * `ShopWired` - ShopWired
     * * `Shortio` - Shortio
     * * `Shutterstock` - Shutterstock
     * * `SigmaComputing` - SigmaComputing
     * * `SignNow` - SignNow
     * * `SimpleCast` - SimpleCast
     * * `Simplesat` - Simplesat
     * * `Smaily` - Smaily
     * * `SmartEngage` - SmartEngage
     * * `Smartreach` - Smartreach
     * * `Smartwaiver` - Smartwaiver
     * * `SolarwindsServiceDesk` - SolarwindsServiceDesk
     * * `SonarCloud` - SonarCloud
     * * `SparkPost` - SparkPost
     * * `SplitIo` - SplitIo
     * * `SpotifyAds` - SpotifyAds
     * * `SpotlerCRM` - SpotlerCRM
     * * `Squarespace` - Squarespace
     * * `Statsig` - Statsig
     * * `Statuspage` - Statuspage
     * * `Stigg` - Stigg
     * * `Strava` - Strava
     * * `SurveySparrow` - SurveySparrow
     * * `Survicate` - Survicate
     * * `Svix` - Svix
     * * `Systeme` - Systeme
     * * `Tavus` - Tavus
     * * `Teamtailor` - Teamtailor
     * * `Teamwork` - Teamwork
     * * `Tempo` - Tempo
     * * `Testrail` - Testrail
     * * `Thinkific` - Thinkific
     * * `ThinkificCourses` - ThinkificCourses
     * * `ThriveLearning` - ThriveLearning
     * * `Ticketmaster` - Ticketmaster
     * * `TicketTailor` - TicketTailor
     * * `TickTick` - TickTick
     * * `Timely` - Timely
     * * `Tinyemail` - Tinyemail
     * * `Todoist` - Todoist
     * * `Toggl` - Toggl
     * * `TrackPMS` - TrackPMS
     * * `Tremendous` - Tremendous
     * * `TrustPilot` - TrustPilot
     * * `Twitter` - Twitter
     * * `TyntecSMS` - TyntecSMS
     * * `Unleash` - Unleash
     * * `UpPromote` - UpPromote
     * * `Uptick` - Uptick
     * * `Uservoice` - Uservoice
     * * `Vantage` - Vantage
     * * `Veeqo` - Veeqo
     * * `Vercel` - Vercel
     * * `VismaEconomic` - VismaEconomic
     * * `VWO` - VWO
     * * `Waiteraid` - Waiteraid
     * * `Wasabi` - Wasabi
     * * `WhenIWork` - WhenIWork
     * * `Wordpress` - Wordpress
     * * `Workable` - Workable
     * * `Workflowmax` - Workflowmax
     * * `Workramp` - Workramp
     * * `Wufoo` - Wufoo
     * * `Xsolla` - Xsolla
     * * `YandexMetrica` - YandexMetrica
     * * `Yotpo` - Yotpo
     * * `Ynab` - Ynab
     * * `Younium` - Younium
     * * `YouSign` - YouSign
     * * `YoutubeData` - YoutubeData
     * * `ZapierSupportedStorage` - ZapierSupportedStorage
     * * `ZapSign` - ZapSign
     * * `ZendeskSell` - ZendeskSell
     * * `ZendeskSunshine` - ZendeskSunshine
     * * `Zenefits` - Zenefits
     * * `Zenloop` - Zenloop
     * * `ZohoAnalytics` - ZohoAnalytics
     * * `ZohoBigin` - ZohoBigin
     * * `ZohoBilling` - ZohoBilling
     * * `ZohoBooks` - ZohoBooks
     * * `ZohoCampaign` - ZohoCampaign
     * * `ZohoDesk` - ZohoDesk
     * * `ZohoExpense` - ZohoExpense
     * * `ZohoInventory` - ZohoInventory
     * * `ZohoInvoice` - ZohoInvoice
     * * `ZonkaFeedback` - ZonkaFeedback
     * * `AlphaVantage` - AlphaVantage
     * * `Aviationstack` - Aviationstack
     * * `Bitly` - Bitly
     * * `Blogger` - Blogger
     * * `Breezometer` - Breezometer
     * * `CareQualityCommission` - CareQualityCommission
     * * `Cimis` - Cimis
     * * `CoinApi` - CoinApi
     * * `CoinGecko` - CoinGecko
     * * `CoinMarketCap` - CoinMarketCap
     * * `DingConnect` - DingConnect
     * * `Dockerhub` - Dockerhub
     * * `ExchangeRatesApi` - ExchangeRatesApi
     * * `FinancialModelling` - FinancialModelling
     * * `Finnhub` - Finnhub
     * * `Finnworlds` - Finnworlds
     * * `Giphy` - Giphy
     * * `Gmail` - Gmail
     * * `GNews` - GNews
     * * `GoogleCalendar` - GoogleCalendar
     * * `GoogleClassroom` - GoogleClassroom
     * * `GoogleDirectory` - GoogleDirectory
     * * `GoogleForms` - GoogleForms
     * * `GooglePageSpeedInsights` - GooglePageSpeedInsights
     * * `GoogleTasks` - GoogleTasks
     * * `GoogleWebfonts` - GoogleWebfonts
     * * `GoogleWorkspaceAdminReports` - GoogleWorkspaceAdminReports
     * * `HuggingFace` - HuggingFace
     * * `IlluminaBasespace` - IlluminaBasespace
     * * `Imagga` - Imagga
     * * `Interzoid` - Interzoid
     * * `IP2Whois` - IP2Whois
     * * `KYVE` - KYVE
     * * `Marketstack` - Marketstack
     * * `Mendeley` - Mendeley
     * * `Nasa` - Nasa
     * * `NewYorkTimes` - NewYorkTimes
     * * `NewsApi` - NewsApi
     * * `NewsData` - NewsData
     * * `OpenDataDc` - OpenDataDc
     * * `OpenExchangeRates` - OpenExchangeRates
     * * `OpenAQ` - OpenAQ
     * * `OpenFDA` - OpenFDA
     * * `OpenWeather` - OpenWeather
     * * `Outlook` - Outlook
     * * `Perigon` - Perigon
     * * `Pexels` - Pexels
     * * `Pocket` - Pocket
     * * `Polygon` - Polygon
     * * `PyPI` - PyPI
     * * `Recreation` - Recreation
     * * `RKICovid` - RKICovid
     * * `Rss` - Rss
     * * `SimFin` - SimFin
     * * `StockData` - StockData
     * * `Guardian` - Guardian
     * * `TMDb` - TMDb
     * * `TVMaze` - TVMaze
     * * `TwelveData` - TwelveData
     * * `Ubidots` - Ubidots
     * * `USCensus` - USCensus
     * * `Watchmode` - Watchmode
     * * `WikipediaPageviews` - WikipediaPageviews
     * * `YahooFinance` - YahooFinance
     * * `Clarifai` - Clarifai
     * * `Adapty` - Adapty
     * * `Braintrust` - Braintrust
     * * `StreamElements` - StreamElements
     * * `Streamlabs` - Streamlabs
     * * `Datorama` - Datorama
     * * `Ahrefs` - Ahrefs
     * * `Lightfield` - Lightfield
     * * `Appstack` - Appstack
     * * `Razorpay` - Razorpay
     * * `Neon` - Neon
     * * `NewRelic` - NewRelic
     * * `Custom` - Custom
     * * `Tile38` - Tile38
     * * `Chatwoot` - Chatwoot
     * * `Sanity` - Sanity
     * * `Metronome` - Metronome
     * * `Jobber` - Jobber
     * * `Knock` - Knock
     * * `Leexi` - Leexi
     * * `RB2B` - RB2B
     * * `Superwall` - Superwall
     * * `Liana` - Liana
     * * `TawkTo` - TawkTo
     * * `Hightouch` - Hightouch
     * * `LemonSqueezy` - LemonSqueezy
     * * `Ikas` - Ikas
     * * `Talkwalker` - Talkwalker
     * * `NextdoorAds` - NextdoorAds
     * * `AppLovin` - AppLovin
     * * `Baserow` - Baserow
     * * `Plunk` - Plunk
     * * `Dub` - Dub
     * * `AirOps` - AirOps
     * * `Podium` - Podium
     * * `Loops` - Loops
     * * `Redis` - Redis
     * * `Mercury` - Mercury
     * * `Gojiberry` - Gojiberry
     * * `Teachable` - Teachable
     * * `PeecAI` - PeecAI
     * * `Healthchecks` - Healthchecks
     * * `Impact` - Impact
     * * `AikidoSecurity` - AikidoSecurity
     * * `Alguna` - Alguna
     * * `Anthropic` - Anthropic
     * * `Appwrite` - Appwrite
     * * `BlandAI` - BlandAI
     * * `BrowseAI` - BrowseAI
     * * `BrowserUse` - BrowserUse
     * * `ChartHop` - ChartHop
     * * `Cody` - Cody
     * * `Cursor` - Cursor
     * * `Decagon` - Decagon
     * * `Deepgram` - Deepgram
     * * `ElevenLabs` - ElevenLabs
     * * `Harvey` - Harvey
     * * `Hyperspell` - Hyperspell
     * * `Langfuse` - Langfuse
     * * `LingoDev` - LingoDev
     * * `M3ter` - M3ter
     * * `Maxio` - Maxio
     * * `Metorial` - Metorial
     * * `OpenRouter` - OpenRouter
     * * `TogetherAI` - TogetherAI
     * * `Vapi` - Vapi
     * * `Vespa` - Vespa
     * * `Writesonic` - Writesonic */
    source_type: ExternalDataSourceTypeEnumApi
    /** Connection details as flat keys for the source_type (discover required fields with the wizard tool). Prefer references over raw secrets: pass {'credential_id': <id>} referencing the connection details the user stored via the connect-link page (discover ids with the stored_credentials endpoint) — they are merged in server-side and deleted once consumed. An already-connected OAuth integration can be passed via its id key instead (e.g. {'hubspot_integration_id': 123}). For source_type 'Custom' (a user-defined REST API) the keys are 'manifest_json' (a stringified RESTAPIConfig describing client.base_url, auth, and resources) plus the credential for the auth type the manifest declares — 'auth_token' (bearer), 'auth_api_key' (api_key), or 'auth_password' (http_basic); keep secrets in these auth_* keys, never inline in the manifest. A 'schemas' array is NOT required — all discovered tables are enabled automatically with sensible sync defaults. */
    payload?: SourceSetupApiPayload
    /**
     * Table name prefix in HogQL, e.g. 'stripe' produces stripe_charges. Defaults to the source type.
     * @maxLength 100
     * @nullable
     */
    prefix?: string | null
    /**
     * Human-readable description.
     * @maxLength 400
     * @nullable
     */
    description?: string | null
    /** Whether a synced source should also be live-queryable via direct connection. Defaults to true; ignored for pure direct-query sources. */
    direct_query_enabled?: boolean
}

export interface SourceSetupWebhookApi {
    /** Whether the webhook was registered with the external service. When true, webhook-capable tables (including webhook-only ones) sync via real-time webhooks; when false, tables fall back to the polling sync defaults and webhook-only tables stay disabled. */
    success: boolean
    /**
     * The PostHog endpoint the external service delivers events to.
     * @nullable
     */
    webhook_url: string | null
    /**
     * Why webhook registration failed (e.g. the credentials lack webhook permissions).
     * @nullable
     */
    error: string | null
    /** Webhook input names the user still needs to provide (e.g. a signing secret the external API did not return on create). Submit them via the update_webhook_inputs endpoint. */
    pending_inputs: string[]
}

export interface SourceSetupResponseApi {
    /** ID of the created external data source. */
    id: string
    /** Outcome of automatic webhook registration. Only present for sources that support webhooks (e.g. Stripe) and have webhook-capable tables. */
    webhook?: SourceSetupWebhookApi
}

/**
 * Connection details as flat keys for the source_type — the same fields the create flow accepts (host, port, password, API key, …). Checked against a live connection before being stored.
 */
export type SourceCredentialCreateApiPayload = { [key: string]: unknown }

export interface SourceCredentialCreateApi {
    /** The source type these credentials are for (e.g. 'Stripe', 'Postgres').
     *
     * * `Ashby` - Ashby
     * * `Supabase` - Supabase
     * * `CustomerIO` - CustomerIO
     * * `Github` - Github
     * * `Stripe` - Stripe
     * * `Hubspot` - Hubspot
     * * `Postgres` - Postgres
     * * `Zendesk` - Zendesk
     * * `Snowflake` - Snowflake
     * * `Salesforce` - Salesforce
     * * `MySQL` - MySQL
     * * `MongoDB` - MongoDB
     * * `MSSQL` - MSSQL
     * * `Vitally` - Vitally
     * * `BigQuery` - BigQuery
     * * `Chargebee` - Chargebee
     * * `Clerk` - Clerk
     * * `GoogleAds` - GoogleAds
     * * `GoogleSearchConsole` - GoogleSearchConsole
     * * `TemporalIO` - TemporalIO
     * * `DoIt` - DoIt
     * * `GoogleSheets` - GoogleSheets
     * * `MetaAds` - MetaAds
     * * `Klaviyo` - Klaviyo
     * * `Mailchimp` - Mailchimp
     * * `Braze` - Braze
     * * `Mailjet` - Mailjet
     * * `Redshift` - Redshift
     * * `Polar` - Polar
     * * `RevenueCat` - RevenueCat
     * * `LinkedinAds` - LinkedinAds
     * * `RedditAds` - RedditAds
     * * `TikTokAds` - TikTokAds
     * * `BingAds` - BingAds
     * * `Shopify` - Shopify
     * * `Attio` - Attio
     * * `SnapchatAds` - SnapchatAds
     * * `Linear` - Linear
     * * `Intercom` - Intercom
     * * `Amplitude` - Amplitude
     * * `Mixpanel` - Mixpanel
     * * `Jira` - Jira
     * * `ActiveCampaign` - ActiveCampaign
     * * `Marketo` - Marketo
     * * `Adjust` - Adjust
     * * `AppsFlyer` - AppsFlyer
     * * `Freshdesk` - Freshdesk
     * * `GoogleAnalytics` - GoogleAnalytics
     * * `Pipedrive` - Pipedrive
     * * `SendGrid` - SendGrid
     * * `Slack` - Slack
     * * `PagerDuty` - PagerDuty
     * * `Asana` - Asana
     * * `Notion` - Notion
     * * `Airtable` - Airtable
     * * `Greenhouse` - Greenhouse
     * * `BambooHR` - BambooHR
     * * `Lever` - Lever
     * * `GitLab` - GitLab
     * * `Datadog` - Datadog
     * * `Sentry` - Sentry
     * * `Pendo` - Pendo
     * * `FullStory` - FullStory
     * * `AmazonAds` - AmazonAds
     * * `PinterestAds` - PinterestAds
     * * `AppleSearchAds` - AppleSearchAds
     * * `QuickBooks` - QuickBooks
     * * `Xero` - Xero
     * * `NetSuite` - NetSuite
     * * `WooCommerce` - WooCommerce
     * * `BigCommerce` - BigCommerce
     * * `PayPal` - PayPal
     * * `Square` - Square
     * * `Zoom` - Zoom
     * * `Trello` - Trello
     * * `Monday` - Monday
     * * `ClickUp` - ClickUp
     * * `Confluence` - Confluence
     * * `Recurly` - Recurly
     * * `SalesLoft` - SalesLoft
     * * `Outreach` - Outreach
     * * `Gong` - Gong
     * * `Calendly` - Calendly
     * * `Typeform` - Typeform
     * * `Iterable` - Iterable
     * * `ZohoCRM` - ZohoCRM
     * * `Close` - Close
     * * `Oracle` - Oracle
     * * `DynamoDB` - DynamoDB
     * * `Elasticsearch` - Elasticsearch
     * * `Kafka` - Kafka
     * * `LaunchDarkly` - LaunchDarkly
     * * `Braintree` - Braintree
     * * `Recharge` - Recharge
     * * `HelpScout` - HelpScout
     * * `Gorgias` - Gorgias
     * * `Instagram` - Instagram
     * * `YouTubeAnalytics` - YouTubeAnalytics
     * * `FacebookPages` - FacebookPages
     * * `TwitterAds` - TwitterAds
     * * `Workday` - Workday
     * * `ServiceNow` - ServiceNow
     * * `Pardot` - Pardot
     * * `Copper` - Copper
     * * `Front` - Front
     * * `ChartMogul` - ChartMogul
     * * `Zuora` - Zuora
     * * `Paddle` - Paddle
     * * `CircleCI` - CircleCI
     * * `CockroachDB` - CockroachDB
     * * `Firebase` - Firebase
     * * `AzureBlob` - AzureBlob
     * * `GoogleDrive` - GoogleDrive
     * * `OneDrive` - OneDrive
     * * `SharePoint` - SharePoint
     * * `Box` - Box
     * * `SFTP` - SFTP
     * * `MicrosoftTeams` - MicrosoftTeams
     * * `Aircall` - Aircall
     * * `Webflow` - Webflow
     * * `Okta` - Okta
     * * `Auth0` - Auth0
     * * `Productboard` - Productboard
     * * `Smartsheet` - Smartsheet
     * * `Wrike` - Wrike
     * * `Plaid` - Plaid
     * * `SurveyMonkey` - SurveyMonkey
     * * `Eventbrite` - Eventbrite
     * * `RingCentral` - RingCentral
     * * `Twilio` - Twilio
     * * `Freshsales` - Freshsales
     * * `Shortcut` - Shortcut
     * * `ConvertKit` - ConvertKit
     * * `Drip` - Drip
     * * `CampaignMonitor` - CampaignMonitor
     * * `MailerLite` - MailerLite
     * * `Omnisend` - Omnisend
     * * `Brevo` - Brevo
     * * `Postmark` - Postmark
     * * `Granola` - Granola
     * * `BuildBetter` - BuildBetter
     * * `Convex` - Convex
     * * `ClickHouse` - ClickHouse
     * * `Plain` - Plain
     * * `Resend` - Resend
     * * `PgAnalyze` - PgAnalyze
     * * `WorkOS` - WorkOS
     * * `AmazonS3` - AmazonS3
     * * `GoogleCloudStorage` - GoogleCloudStorage
     * * `Databricks` - Databricks
     * * `Dynamics365` - Dynamics365
     * * `SalesforceMarketingCloud` - SalesforceMarketingCloud
     * * `Db2` - Db2
     * * `Heap` - Heap
     * * `AdobeAnalytics` - AdobeAnalytics
     * * `Matomo` - Matomo
     * * `Optimizely` - Optimizely
     * * `Adyen` - Adyen
     * * `GoCardless` - GoCardless
     * * `Mollie` - Mollie
     * * `CheckoutCom` - CheckoutCom
     * * `Branch` - Branch
     * * `Criteo` - Criteo
     * * `Outbrain` - Outbrain
     * * `Taboola` - Taboola
     * * `AdRoll` - AdRoll
     * * `DisplayVideo360` - DisplayVideo360
     * * `GoogleAdManager` - GoogleAdManager
     * * `CampaignManager360` - CampaignManager360
     * * `SearchAds360` - SearchAds360
     * * `AdobeCommerce` - AdobeCommerce
     * * `AmazonSellingPartner` - AmazonSellingPartner
     * * `Ebay` - Ebay
     * * `Commercetools` - Commercetools
     * * `LightspeedRetail` - LightspeedRetail
     * * `ShipStation` - ShipStation
     * * `ConstantContact` - ConstantContact
     * * `Mailgun` - Mailgun
     * * `Eloqua` - Eloqua
     * * `Sailthru` - Sailthru
     * * `Ortto` - Ortto
     * * `Attentive` - Attentive
     * * `Kustomer` - Kustomer
     * * `Dixa` - Dixa
     * * `Gladly` - Gladly
     * * `Qualtrics` - Qualtrics
     * * `Delighted` - Delighted
     * * `AzureDevOps` - AzureDevOps
     * * `Rollbar` - Rollbar
     * * `Opsgenie` - Opsgenie
     * * `IncidentIo` - IncidentIo
     * * `Pingdom` - Pingdom
     * * `Cloudflare` - Cloudflare
     * * `CosmosDB` - CosmosDB
     * * `PlanetScale` - PlanetScale
     * * `SapHana` - SapHana
     * * `Rippling` - Rippling
     * * `HiBob` - HiBob
     * * `Personio` - Personio
     * * `Deel` - Deel
     * * `AdpWorkforceNow` - AdpWorkforceNow
     * * `Paylocity` - Paylocity
     * * `Gusto` - Gusto
     * * `CultureAmp` - CultureAmp
     * * `Lattice` - Lattice
     * * `SageIntacct` - SageIntacct
     * * `FreshBooks` - FreshBooks
     * * `Expensify` - Expensify
     * * `Ramp` - Ramp
     * * `Brex` - Brex
     * * `Coupa` - Coupa
     * * `SapConcur` - SapConcur
     * * `Apollo` - Apollo
     * * `Crunchbase` - Crunchbase
     * * `ZoomInfo` - ZoomInfo
     * * `Clari` - Clari
     * * `Chorus` - Chorus
     * * `Coda` - Coda
     * * `Guru` - Guru
     * * `Dropbox` - Dropbox
     * * `Docusign` - Docusign
     * * `PandaDoc` - PandaDoc
     * * `SapErp` - SapErp
     * * `SapSuccessFactors` - SapSuccessFactors
     * * `OracleEbs` - OracleEbs
     * * `OracleFusion` - OracleFusion
     * * `AmazonSNS` - AmazonSNS
     * * `AmazonEventBridge` - AmazonEventBridge
     * * `AmazonSQS` - AmazonSQS
     * * `AmazonKinesis` - AmazonKinesis
     * * `AmazonCloudWatch` - AmazonCloudWatch
     * * `OpenAIAds` - OpenAIAds
     * * `OneHundredMs` - OneHundredMs
     * * `SevenShifts` - SevenShifts
     * * `AcuityScheduling` - AcuityScheduling
     * * `AgileCRM` - AgileCRM
     * * `Aha` - Aha
     * * `Airbyte` - Airbyte
     * * `Akeneo` - Akeneo
     * * `Algolia` - Algolia
     * * `AlpacaBrokerAPI` - AlpacaBrokerAPI
     * * `ApifyDataset` - ApifyDataset
     * * `Appcues` - Appcues
     * * `Appfigures` - Appfigures
     * * `Appfollow` - Appfollow
     * * `Apptivo` - Apptivo
     * * `AssemblyAI` - AssemblyAI
     * * `Awin` - Awin
     * * `AwsCloudTrail` - AwsCloudTrail
     * * `AzureTableStorage` - AzureTableStorage
     * * `Babelforce` - Babelforce
     * * `Basecamp` - Basecamp
     * * `Beamer` - Beamer
     * * `BigMailer` - BigMailer
     * * `Bluetally` - Bluetally
     * * `BoldSign` - BoldSign
     * * `BreezyHR` - BreezyHR
     * * `Bugsnag` - Bugsnag
     * * `Buildkite` - Buildkite
     * * `Bunny` - Bunny
     * * `Buzzsprout` - Buzzsprout
     * * `CalCom` - CalCom
     * * `CallRail` - CallRail
     * * `Campayn` - Campayn
     * * `Canny` - Canny
     * * `CapsuleCRM` - CapsuleCRM
     * * `CaptainData` - CaptainData
     * * `CartCom` - CartCom
     * * `CastorEDC` - CastorEDC
     * * `Chameleon` - Chameleon
     * * `Chargedesk` - Chargedesk
     * * `Chargify` - Chargify
     * * `Chift` - Chift
     * * `Churnkey` - Churnkey
     * * `Cin7` - Cin7
     * * `CiscoMeraki` - CiscoMeraki
     * * `Clazar` - Clazar
     * * `Clockify` - Clockify
     * * `Clockodo` - Clockodo
     * * `Cloudbeds` - Cloudbeds
     * * `Coassemble` - Coassemble
     * * `Codefresh` - Codefresh
     * * `Concord` - Concord
     * * `ConfigCat` - ConfigCat
     * * `Couchbase` - Couchbase
     * * `Curve` - Curve
     * * `Customerly` - Customerly
     * * `Datascope` - Datascope
     * * `Dbt` - Dbt
     * * `Deputy` - Deputy
     * * `DevinAI` - DevinAI
     * * `Docuseal` - Docuseal
     * * `Dolibarr` - Dolibarr
     * * `Dremio` - Dremio
     * * `DropboxSign` - DropboxSign
     * * `Dwolla` - Dwolla
     * * `EConomic` - EConomic
     * * `Easypost` - Easypost
     * * `Easypromos` - Easypromos
     * * `Elasticemail` - Elasticemail
     * * `EmailOctopus` - EmailOctopus
     * * `EmploymentHero` - EmploymentHero
     * * `Encharge` - Encharge
     * * `Eventee` - Eventee
     * * `Eventzilla` - Eventzilla
     * * `Everhour` - Everhour
     * * `EZOfficeInventory` - EZOfficeInventory
     * * `Factorial` - Factorial
     * * `Fastbill` - Fastbill
     * * `Fastly` - Fastly
     * * `Fauna` - Fauna
     * * `Feishu` - Feishu
     * * `Fillout` - Fillout
     * * `Finage` - Finage
     * * `Firebolt` - Firebolt
     * * `FireHydrant` - FireHydrant
     * * `Fleetio` - Fleetio
     * * `Flexmail` - Flexmail
     * * `Flexport` - Flexport
     * * `FloatApp` - FloatApp
     * * `Flowlu` - Flowlu
     * * `Formbricks` - Formbricks
     * * `FreeAgent` - FreeAgent
     * * `Freightview` - Freightview
     * * `Freshcaller` - Freshcaller
     * * `Freshchat` - Freshchat
     * * `Freshservice` - Freshservice
     * * `Fulcrum` - Fulcrum
     * * `GainsightPx` - GainsightPx
     * * `GitBook` - GitBook
     * * `Glassfrog` - Glassfrog
     * * `Goldcast` - Goldcast
     * * `GoLogin` - GoLogin
     * * `Grafana` - Grafana
     * * `GreytHr` - GreytHr
     * * `Gridly` - Gridly
     * * `Harness` - Harness
     * * `Height` - Height
     * * `Hellobaton` - Hellobaton
     * * `HighLevel` - HighLevel
     * * `HoorayHR` - HoorayHR
     * * `Hubplanner` - Hubplanner
     * * `Humanitix` - Humanitix
     * * `Huntr` - Huntr
     * * `Inflowinventory` - Inflowinventory
     * * `InforNexus` - InforNexus
     * * `Insightful` - Insightful
     * * `Insightly` - Insightly
     * * `Instantly` - Instantly
     * * `Instatus` - Instatus
     * * `Intruder` - Intruder
     * * `Invoiced` - Invoiced
     * * `Invoiceninja` - Invoiceninja
     * * `JamfPro` - JamfPro
     * * `JobNimbus` - JobNimbus
     * * `Jotform` - Jotform
     * * `JudgeMeReviews` - JudgeMeReviews
     * * `JustCall` - JustCall
     * * `JustSift` - JustSift
     * * `K6Cloud` - K6Cloud
     * * `Katana` - Katana
     * * `Keka` - Keka
     * * `Kisi` - Kisi
     * * `Kissmetrics` - Kissmetrics
     * * `Klarna` - Klarna
     * * `Klaus` - Klaus
     * * `Lago` - Lago
     * * `Leadfeeder` - Leadfeeder
     * * `Lemlist` - Lemlist
     * * `LessAnnoyingCRM` - LessAnnoyingCRM
     * * `LinkedinPages` - LinkedinPages
     * * `Linkrunner` - Linkrunner
     * * `Linnworks` - Linnworks
     * * `Lob` - Lob
     * * `Lokalise` - Lokalise
     * * `Looker` - Looker
     * * `Luma` - Luma
     * * `MailerSend` - MailerSend
     * * `Mailosaur` - Mailosaur
     * * `Mailtrap` - Mailtrap
     * * `Mantle` - Mantle
     * * `Mention` - Mention
     * * `MercadoAds` - MercadoAds
     * * `Merge` - Merge
     * * `Metabase` - Metabase
     * * `Metricool` - Metricool
     * * `MicrosoftDataverse` - MicrosoftDataverse
     * * `MicrosoftEntraId` - MicrosoftEntraId
     * * `MicrosoftLists` - MicrosoftLists
     * * `Miro` - Miro
     * * `Missive` - Missive
     * * `MixMax` - MixMax
     * * `Mode` - Mode
     * * `Mux` - Mux
     * * `MyHours` - MyHours
     * * `N8n` - N8n
     * * `Navan` - Navan
     * * `NebiusAI` - NebiusAI
     * * `Nexiopay` - Nexiopay
     * * `NinjaOneRMM` - NinjaOneRMM
     * * `NoCRM` - NoCRM
     * * `NorthpassLMS` - NorthpassLMS
     * * `Nutshell` - Nutshell
     * * `Nylas` - Nylas
     * * `Oncehub` - Oncehub
     * * `Onepagecrm` - Onepagecrm
     * * `OneSignal` - OneSignal
     * * `Onfleet` - Onfleet
     * * `OpinionStage` - OpinionStage
     * * `OPUSWatch` - OPUSWatch
     * * `Orb` - Orb
     * * `Orbit` - Orbit
     * * `Oura` - Oura
     * * `Oveit` - Oveit
     * * `PabblySubscriptionsBilling` - PabblySubscriptionsBilling
     * * `Paperform` - Paperform
     * * `Papersign` - Papersign
     * * `Partnerize` - Partnerize
     * * `PartnerStack` - PartnerStack
     * * `PayFit` - PayFit
     * * `Paystack` - Paystack
     * * `Pennylane` - Pennylane
     * * `Perk` - Perk
     * * `PersistIq` - PersistIq
     * * `Persona` - Persona
     * * `Phyllo` - Phyllo
     * * `Picqer` - Picqer
     * * `Pipeliner` - Pipeliner
     * * `PivotalTracker` - PivotalTracker
     * * `Piwik` - Piwik
     * * `Planhat` - Planhat
     * * `Plausible` - Plausible
     * * `Poplar` - Poplar
     * * `PrestaShop` - PrestaShop
     * * `Pretix` - Pretix
     * * `Primetric` - Primetric
     * * `Printify` - Printify
     * * `Productive` - Productive
     * * `Pylon` - Pylon
     * * `Qonto` - Qonto
     * * `Qualaroo` - Qualaroo
     * * `Railz` - Railz
     * * `RDStationMarketing` - RDStationMarketing
     * * `Recruitee` - Recruitee
     * * `Reddit` - Reddit
     * * `ReferralHero` - ReferralHero
     * * `RentCast` - RentCast
     * * `Repairshopr` - Repairshopr
     * * `ReplyIo` - ReplyIo
     * * `RetailExpress` - RetailExpress
     * * `Retently` - Retently
     * * `RevolutMerchant` - RevolutMerchant
     * * `RocketChat` - RocketChat
     * * `Rocketlane` - Rocketlane
     * * `Rootly` - Rootly
     * * `Ruddr` - Ruddr
     * * `SafetyCulture` - SafetyCulture
     * * `SageHR` - SageHR
     * * `Salesflare` - Salesflare
     * * `SAPFieldglass` - SAPFieldglass
     * * `SavvyCal` - SavvyCal
     * * `Secoda` - Secoda
     * * `Segment` - Segment
     * * `Sendowl` - Sendowl
     * * `SendPulse` - SendPulse
     * * `Senseforce` - Senseforce
     * * `Serpstat` - Serpstat
     * * `Sharetribe` - Sharetribe
     * * `Shippo` - Shippo
     * * `ShopWired` - ShopWired
     * * `Shortio` - Shortio
     * * `Shutterstock` - Shutterstock
     * * `SigmaComputing` - SigmaComputing
     * * `SignNow` - SignNow
     * * `SimpleCast` - SimpleCast
     * * `Simplesat` - Simplesat
     * * `Smaily` - Smaily
     * * `SmartEngage` - SmartEngage
     * * `Smartreach` - Smartreach
     * * `Smartwaiver` - Smartwaiver
     * * `SolarwindsServiceDesk` - SolarwindsServiceDesk
     * * `SonarCloud` - SonarCloud
     * * `SparkPost` - SparkPost
     * * `SplitIo` - SplitIo
     * * `SpotifyAds` - SpotifyAds
     * * `SpotlerCRM` - SpotlerCRM
     * * `Squarespace` - Squarespace
     * * `Statsig` - Statsig
     * * `Statuspage` - Statuspage
     * * `Stigg` - Stigg
     * * `Strava` - Strava
     * * `SurveySparrow` - SurveySparrow
     * * `Survicate` - Survicate
     * * `Svix` - Svix
     * * `Systeme` - Systeme
     * * `Tavus` - Tavus
     * * `Teamtailor` - Teamtailor
     * * `Teamwork` - Teamwork
     * * `Tempo` - Tempo
     * * `Testrail` - Testrail
     * * `Thinkific` - Thinkific
     * * `ThinkificCourses` - ThinkificCourses
     * * `ThriveLearning` - ThriveLearning
     * * `Ticketmaster` - Ticketmaster
     * * `TicketTailor` - TicketTailor
     * * `TickTick` - TickTick
     * * `Timely` - Timely
     * * `Tinyemail` - Tinyemail
     * * `Todoist` - Todoist
     * * `Toggl` - Toggl
     * * `TrackPMS` - TrackPMS
     * * `Tremendous` - Tremendous
     * * `TrustPilot` - TrustPilot
     * * `Twitter` - Twitter
     * * `TyntecSMS` - TyntecSMS
     * * `Unleash` - Unleash
     * * `UpPromote` - UpPromote
     * * `Uptick` - Uptick
     * * `Uservoice` - Uservoice
     * * `Vantage` - Vantage
     * * `Veeqo` - Veeqo
     * * `Vercel` - Vercel
     * * `VismaEconomic` - VismaEconomic
     * * `VWO` - VWO
     * * `Waiteraid` - Waiteraid
     * * `Wasabi` - Wasabi
     * * `WhenIWork` - WhenIWork
     * * `Wordpress` - Wordpress
     * * `Workable` - Workable
     * * `Workflowmax` - Workflowmax
     * * `Workramp` - Workramp
     * * `Wufoo` - Wufoo
     * * `Xsolla` - Xsolla
     * * `YandexMetrica` - YandexMetrica
     * * `Yotpo` - Yotpo
     * * `Ynab` - Ynab
     * * `Younium` - Younium
     * * `YouSign` - YouSign
     * * `YoutubeData` - YoutubeData
     * * `ZapierSupportedStorage` - ZapierSupportedStorage
     * * `ZapSign` - ZapSign
     * * `ZendeskSell` - ZendeskSell
     * * `ZendeskSunshine` - ZendeskSunshine
     * * `Zenefits` - Zenefits
     * * `Zenloop` - Zenloop
     * * `ZohoAnalytics` - ZohoAnalytics
     * * `ZohoBigin` - ZohoBigin
     * * `ZohoBilling` - ZohoBilling
     * * `ZohoBooks` - ZohoBooks
     * * `ZohoCampaign` - ZohoCampaign
     * * `ZohoDesk` - ZohoDesk
     * * `ZohoExpense` - ZohoExpense
     * * `ZohoInventory` - ZohoInventory
     * * `ZohoInvoice` - ZohoInvoice
     * * `ZonkaFeedback` - ZonkaFeedback
     * * `AlphaVantage` - AlphaVantage
     * * `Aviationstack` - Aviationstack
     * * `Bitly` - Bitly
     * * `Blogger` - Blogger
     * * `Breezometer` - Breezometer
     * * `CareQualityCommission` - CareQualityCommission
     * * `Cimis` - Cimis
     * * `CoinApi` - CoinApi
     * * `CoinGecko` - CoinGecko
     * * `CoinMarketCap` - CoinMarketCap
     * * `DingConnect` - DingConnect
     * * `Dockerhub` - Dockerhub
     * * `ExchangeRatesApi` - ExchangeRatesApi
     * * `FinancialModelling` - FinancialModelling
     * * `Finnhub` - Finnhub
     * * `Finnworlds` - Finnworlds
     * * `Giphy` - Giphy
     * * `Gmail` - Gmail
     * * `GNews` - GNews
     * * `GoogleCalendar` - GoogleCalendar
     * * `GoogleClassroom` - GoogleClassroom
     * * `GoogleDirectory` - GoogleDirectory
     * * `GoogleForms` - GoogleForms
     * * `GooglePageSpeedInsights` - GooglePageSpeedInsights
     * * `GoogleTasks` - GoogleTasks
     * * `GoogleWebfonts` - GoogleWebfonts
     * * `GoogleWorkspaceAdminReports` - GoogleWorkspaceAdminReports
     * * `HuggingFace` - HuggingFace
     * * `IlluminaBasespace` - IlluminaBasespace
     * * `Imagga` - Imagga
     * * `Interzoid` - Interzoid
     * * `IP2Whois` - IP2Whois
     * * `KYVE` - KYVE
     * * `Marketstack` - Marketstack
     * * `Mendeley` - Mendeley
     * * `Nasa` - Nasa
     * * `NewYorkTimes` - NewYorkTimes
     * * `NewsApi` - NewsApi
     * * `NewsData` - NewsData
     * * `OpenDataDc` - OpenDataDc
     * * `OpenExchangeRates` - OpenExchangeRates
     * * `OpenAQ` - OpenAQ
     * * `OpenFDA` - OpenFDA
     * * `OpenWeather` - OpenWeather
     * * `Outlook` - Outlook
     * * `Perigon` - Perigon
     * * `Pexels` - Pexels
     * * `Pocket` - Pocket
     * * `Polygon` - Polygon
     * * `PyPI` - PyPI
     * * `Recreation` - Recreation
     * * `RKICovid` - RKICovid
     * * `Rss` - Rss
     * * `SimFin` - SimFin
     * * `StockData` - StockData
     * * `Guardian` - Guardian
     * * `TMDb` - TMDb
     * * `TVMaze` - TVMaze
     * * `TwelveData` - TwelveData
     * * `Ubidots` - Ubidots
     * * `USCensus` - USCensus
     * * `Watchmode` - Watchmode
     * * `WikipediaPageviews` - WikipediaPageviews
     * * `YahooFinance` - YahooFinance
     * * `Clarifai` - Clarifai
     * * `Adapty` - Adapty
     * * `Braintrust` - Braintrust
     * * `StreamElements` - StreamElements
     * * `Streamlabs` - Streamlabs
     * * `Datorama` - Datorama
     * * `Ahrefs` - Ahrefs
     * * `Lightfield` - Lightfield
     * * `Appstack` - Appstack
     * * `Razorpay` - Razorpay
     * * `Neon` - Neon
     * * `NewRelic` - NewRelic
     * * `Custom` - Custom
     * * `Tile38` - Tile38
     * * `Chatwoot` - Chatwoot
     * * `Sanity` - Sanity
     * * `Metronome` - Metronome
     * * `Jobber` - Jobber
     * * `Knock` - Knock
     * * `Leexi` - Leexi
     * * `RB2B` - RB2B
     * * `Superwall` - Superwall
     * * `Liana` - Liana
     * * `TawkTo` - TawkTo
     * * `Hightouch` - Hightouch
     * * `LemonSqueezy` - LemonSqueezy
     * * `Ikas` - Ikas
     * * `Talkwalker` - Talkwalker
     * * `NextdoorAds` - NextdoorAds
     * * `AppLovin` - AppLovin
     * * `Baserow` - Baserow
     * * `Plunk` - Plunk
     * * `Dub` - Dub
     * * `AirOps` - AirOps
     * * `Podium` - Podium
     * * `Loops` - Loops
     * * `Redis` - Redis
     * * `Mercury` - Mercury
     * * `Gojiberry` - Gojiberry
     * * `Teachable` - Teachable
     * * `PeecAI` - PeecAI
     * * `Healthchecks` - Healthchecks
     * * `Impact` - Impact
     * * `AikidoSecurity` - AikidoSecurity
     * * `Alguna` - Alguna
     * * `Anthropic` - Anthropic
     * * `Appwrite` - Appwrite
     * * `BlandAI` - BlandAI
     * * `BrowseAI` - BrowseAI
     * * `BrowserUse` - BrowserUse
     * * `ChartHop` - ChartHop
     * * `Cody` - Cody
     * * `Cursor` - Cursor
     * * `Decagon` - Decagon
     * * `Deepgram` - Deepgram
     * * `ElevenLabs` - ElevenLabs
     * * `Harvey` - Harvey
     * * `Hyperspell` - Hyperspell
     * * `Langfuse` - Langfuse
     * * `LingoDev` - LingoDev
     * * `M3ter` - M3ter
     * * `Maxio` - Maxio
     * * `Metorial` - Metorial
     * * `OpenRouter` - OpenRouter
     * * `TogetherAI` - TogetherAI
     * * `Vapi` - Vapi
     * * `Vespa` - Vespa
     * * `Writesonic` - Writesonic */
    source_type: ExternalDataSourceTypeEnumApi
    /** Connection details as flat keys for the source_type — the same fields the create flow accepts (host, port, password, API key, …). Checked against a live connection before being stored. */
    payload: SourceCredentialCreateApiPayload
}

export interface SourceCredentialApi {
    /** Stored credential id. Pass to the setup endpoint as {'credential_id': <id>} to create the source. */
    credential_id: string
    /** The source type the stored credentials are for. */
    source_type: string
    /** When the credentials were stored. */
    created_at: string
    /** When the stored credentials expire. Unconsumed credentials are unusable past this time. */
    expires_at: string
}

export type ExternalDataSchemasListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    /**
     * A search term.
     */
    search?: string
}

export type ExternalDataSchemasLogsRetrieveParams = {
    /**
     * Only return entries after this ISO 8601 timestamp.
     */
    after?: string
    /**
     * Only return entries before this ISO 8601 timestamp.
     */
    before?: string
    /**
     * Filter logs to a specific execution instance.
     * @minLength 1
     */
    instance_id?: string
    /**
     * Comma-separated log levels to include, e.g. 'WARN,ERROR'. Valid levels: DEBUG, LOG, INFO, WARN, ERROR.
     * @minLength 1
     */
    level?: string
    /**
     * Maximum number of log entries to return (1-500, default 50).
     * @minimum 1
     * @maximum 500
     */
    limit?: number
    /**
     * Case-insensitive substring search across log messages.
     * @minLength 1
     */
    search?: string
}

export type ExternalDataSourcesListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    /**
     * A search term.
     */
    search?: string
}

export type ExternalDataSourcesBulkUpdateSchemasPartialUpdateParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    /**
     * A search term.
     */
    search?: string
}

export type ExternalDataSourcesRepairCdcCreate200 = {
    success?: boolean
    schemas_reset?: number
}

export type ExternalDataSourcesCheckCdcPrerequisitesCreate200 = {
    valid?: boolean
    errors?: string[]
}

export type ExternalDataSourcesConnectLinkRetrieveParams = {
    /**
     * The source type to generate a connect link for (e.g. 'Stripe', 'Postgres', 'Hubspot').
     */
    source_type: string
}

export type ExternalDataSourcesConnectionsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    /**
     * A search term.
     */
    search?: string
}

export type ExternalDataSourcesStoredCredentialsListParams = {
    /**
     * A search term.
     */
    search?: string
    /**
     * Only return stored credentials for this source type (e.g. 'Stripe', 'Postgres').
     */
    source_type?: string
}

export type ExternalDataSourcesWizardRetrieveParams = {
    /**
     * Comma-separated source type(s) to return config for, e.g. 'Postgres' or 'Postgres,Stripe'. Strongly recommended: the unfiltered response describes every supported source and is very large. Omit only to enumerate the available types.
     */
    source_type?: string
}
