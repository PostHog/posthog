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
 * * `vercel` - Vercel
 */
export type OrganizationIntegrationKindEnumApi =
    (typeof OrganizationIntegrationKindEnumApi)[keyof typeof OrganizationIntegrationKindEnumApi]

export const OrganizationIntegrationKindEnumApi = {
    Vercel: 'vercel',
} as const

/**
 * * `engineering` - Engineering
 * `data` - Data
 * `product` - Product Management
 * `founder` - Founder
 * `leadership` - Leadership
 * `marketing` - Marketing
 * `sales` - Sales / Success
 * `other` - Other
 */
export type RoleAtOrganizationEnumApi = (typeof RoleAtOrganizationEnumApi)[keyof typeof RoleAtOrganizationEnumApi]

export const RoleAtOrganizationEnumApi = {
    Engineering: 'engineering',
    Data: 'data',
    Product: 'product',
    Founder: 'founder',
    Leadership: 'leadership',
    Marketing: 'marketing',
    Sales: 'sales',
    Other: 'other',
} as const

export type BlankEnumApi = (typeof BlankEnumApi)[keyof typeof BlankEnumApi]

export const BlankEnumApi = {
    '': '',
} as const

export type NullEnumApi = (typeof NullEnumApi)[keyof typeof NullEnumApi]

export const NullEnumApi = {} as const

/**
 * @nullable
 */
export type UserBasicApiHedgehogConfig = { [key: string]: unknown } | null | null

export interface UserBasicApi {
    readonly id: number
    readonly uuid: string
    /**
     * @maxLength 200
     * @nullable
     */
    distinct_id?: string | null
    /** @maxLength 150 */
    first_name?: string
    /** @maxLength 150 */
    last_name?: string
    /** @maxLength 254 */
    email: string
    /** @nullable */
    is_email_verified?: boolean | null
    /** @nullable */
    readonly hedgehog_config: UserBasicApiHedgehogConfig
    role_at_organization?: RoleAtOrganizationEnumApi | BlankEnumApi | NullEnumApi | null
}

/**
 * Serializer for organization-level integrations.
 */
export interface PatchedOrganizationIntegrationApi {
    readonly id?: string
    readonly kind?: OrganizationIntegrationKindEnumApi
    /** @nullable */
    readonly integration_id?: string | null
    readonly config?: unknown
    readonly created_at?: string
    readonly updated_at?: string
    readonly created_by?: UserBasicApi
}

/**
 * Serializer for organization-level integrations.
 */
export interface OrganizationIntegrationApi {
    readonly id: string
    readonly kind: OrganizationIntegrationKindEnumApi
    /** @nullable */
    readonly integration_id: string | null
    readonly config: unknown
    readonly created_at: string
    readonly updated_at: string
    readonly created_by: UserBasicApi
}

/**
 * * `slack` - Slack
 * `slack-posthog-code` - Slack Posthog Code
 * `salesforce` - Salesforce
 * `hubspot` - Hubspot
 * `google-pubsub` - Google Pubsub
 * `google-cloud-storage` - Google Cloud Storage
 * `google-ads` - Google Ads
 * `google-sheets` - Google Sheets
 * `google-cloud-service-account` - Google Cloud Service Account
 * `snapchat` - Snapchat
 * `linkedin-ads` - Linkedin Ads
 * `reddit-ads` - Reddit Ads
 * `tiktok-ads` - Tiktok Ads
 * `bing-ads` - Bing Ads
 * `intercom` - Intercom
 * `email` - Email
 * `linear` - Linear
 * `github` - Github
 * `gitlab` - Gitlab
 * `meta-ads` - Meta Ads
 * `twilio` - Twilio
 * `clickup` - Clickup
 * `vercel` - Vercel
 * `databricks` - Databricks
 * `azure-blob` - Azure Blob
 * `firebase` - Firebase
 * `jira` - Jira
 * `pinterest-ads` - Pinterest Ads
 * `stripe` - Stripe
 * `customerio-app` - Customerio App
 * `customerio-webhook` - Customerio Webhook
 * `customerio-track` - Customerio Track
 */
export type IntegrationKindEnumApi = (typeof IntegrationKindEnumApi)[keyof typeof IntegrationKindEnumApi]

export const IntegrationKindEnumApi = {
    Slack: 'slack',
    SlackPosthogCode: 'slack-posthog-code',
    Salesforce: 'salesforce',
    Hubspot: 'hubspot',
    GooglePubsub: 'google-pubsub',
    GoogleCloudStorage: 'google-cloud-storage',
    GoogleAds: 'google-ads',
    GoogleSheets: 'google-sheets',
    GoogleCloudServiceAccount: 'google-cloud-service-account',
    Snapchat: 'snapchat',
    LinkedinAds: 'linkedin-ads',
    RedditAds: 'reddit-ads',
    TiktokAds: 'tiktok-ads',
    BingAds: 'bing-ads',
    Intercom: 'intercom',
    Email: 'email',
    Linear: 'linear',
    Github: 'github',
    Gitlab: 'gitlab',
    MetaAds: 'meta-ads',
    Twilio: 'twilio',
    Clickup: 'clickup',
    Vercel: 'vercel',
    Databricks: 'databricks',
    AzureBlob: 'azure-blob',
    Firebase: 'firebase',
    Jira: 'jira',
    PinterestAds: 'pinterest-ads',
    Stripe: 'stripe',
    CustomerioApp: 'customerio-app',
    CustomerioWebhook: 'customerio-webhook',
    CustomerioTrack: 'customerio-track',
} as const

/**
 * Standard Integration serializer.
 */
export interface IntegrationConfigApi {
    readonly id: number
    kind: IntegrationKindEnumApi
    config?: unknown
    readonly created_at: string
    readonly created_by: UserBasicApi
    readonly errors: string
    readonly display_name: string
}

export interface PaginatedIntegrationConfigListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: IntegrationConfigApi[]
}

/**
 * Standard Integration serializer.
 */
export interface PatchedIntegrationConfigApi {
    readonly id?: number
    kind?: IntegrationKindEnumApi
    config?: unknown
    readonly created_at?: string
    readonly created_by?: UserBasicApi
    readonly errors?: string
    readonly display_name?: string
}

export interface GitHubBranchesResponseApi {
    /** List of branch names */
    branches: string[]
    /**
     * The default branch of the repository
     * @nullable
     */
    default_branch?: string | null
    /** Whether more branches exist beyond the returned page */
    has_more: boolean
}

export interface GitHubRepoApi {
    id: number
    name: string
    full_name: string
}

export interface GitHubReposResponseApi {
    repositories: GitHubRepoApi[]
    /** Whether more repositories are available beyond this page. */
    has_more: boolean
}

export interface GitHubReposRefreshResponseApi {
    /** The refreshed repository cache. */
    repositories: GitHubRepoApi[]
}

export type IntegrationsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type IntegrationsGithubBranchesRetrieveParams = {
    /**
     * Maximum number of branches to return
     * @minimum 1
     * @maximum 1000
     */
    limit?: number
    /**
     * Number of branches to skip
     * @minimum 0
     */
    offset?: number
    /**
     * Repository in owner/repo format
     * @minLength 1
     */
    repo: string
    /**
     * Optional case-insensitive branch name search query.
     */
    search?: string
}

export type IntegrationsGithubReposRetrieveParams = {
    /**
     * Maximum number of repositories to return per request (max 500).
     * @minimum 1
     * @maximum 500
     */
    limit?: number
    /**
     * Number of repositories to skip before returning results.
     * @minimum 0
     */
    offset?: number
    /**
     * Optional case-insensitive repository name search query.
     */
    search?: string
}
