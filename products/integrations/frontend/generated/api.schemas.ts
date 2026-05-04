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

export interface RoleExternalReferenceApi {
    readonly id: string
    /**
     * Integration kind (e.g., github, linear, jira, slack).
     * @maxLength 32
     */
    provider: string
    /**
     * Provider organization/workspace/site identifier.
     * @maxLength 255
     */
    provider_organization_id: string
    /**
     * Stable provider role identifier.
     * @maxLength 255
     */
    provider_role_id: string
    /**
     * Human-friendly provider role identifier.
     * @maxLength 255
     * @nullable
     */
    provider_role_slug?: string | null
    /**
     * Display name of the provider role.
     * @maxLength 255
     */
    provider_role_name: string
    /** PostHog role UUID this external role maps to. */
    role: string
    readonly created_at: string
    readonly created_by: UserBasicApi
}

export interface PaginatedRoleExternalReferenceListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: RoleExternalReferenceApi[]
}

export interface RoleLookupResponseApi {
    /** Matching reference, or null if none exists. */
    reference: RoleExternalReferenceApi | null
}

/**
 * * `apns` - Apple Push
 * `azure-blob` - Azure Blob
 * `bing-ads` - Bing Ads
 * `clickup` - Clickup
 * `customerio-app` - Customerio App
 * `customerio-track` - Customerio Track
 * `customerio-webhook` - Customerio Webhook
 * `databricks` - Databricks
 * `email` - Email
 * `firebase` - Firebase
 * `github` - Github
 * `gitlab` - Gitlab
 * `google-ads` - Google Ads
 * `google-cloud-service-account` - Google Cloud Service Account
 * `google-cloud-storage` - Google Cloud Storage
 * `google-pubsub` - Google Pubsub
 * `google-sheets` - Google Sheets
 * `hubspot` - Hubspot
 * `intercom` - Intercom
 * `jira` - Jira
 * `linear` - Linear
 * `linkedin-ads` - Linkedin Ads
 * `meta-ads` - Meta Ads
 * `pinterest-ads` - Pinterest Ads
 * `postgresql` - Postgresql
 * `reddit-ads` - Reddit Ads
 * `salesforce` - Salesforce
 * `slack` - Slack
 * `slack-posthog-code` - Slack Posthog Code
 * `snapchat` - Snapchat
 * `stripe` - Stripe
 * `tiktok-ads` - Tiktok Ads
 * `twilio` - Twilio
 * `vercel` - Vercel
 */
export type IntegrationKindEnumApi = (typeof IntegrationKindEnumApi)[keyof typeof IntegrationKindEnumApi]

export const IntegrationKindEnumApi = {
    Apns: 'apns',
    AzureBlob: 'azure-blob',
    BingAds: 'bing-ads',
    Clickup: 'clickup',
    CustomerioApp: 'customerio-app',
    CustomerioTrack: 'customerio-track',
    CustomerioWebhook: 'customerio-webhook',
    Databricks: 'databricks',
    Email: 'email',
    Firebase: 'firebase',
    Github: 'github',
    Gitlab: 'gitlab',
    GoogleAds: 'google-ads',
    GoogleCloudServiceAccount: 'google-cloud-service-account',
    GoogleCloudStorage: 'google-cloud-storage',
    GooglePubsub: 'google-pubsub',
    GoogleSheets: 'google-sheets',
    Hubspot: 'hubspot',
    Intercom: 'intercom',
    Jira: 'jira',
    Linear: 'linear',
    LinkedinAds: 'linkedin-ads',
    MetaAds: 'meta-ads',
    PinterestAds: 'pinterest-ads',
    Postgresql: 'postgresql',
    RedditAds: 'reddit-ads',
    Salesforce: 'salesforce',
    Slack: 'slack',
    SlackPosthogCode: 'slack-posthog-code',
    Snapchat: 'snapchat',
    Stripe: 'stripe',
    TiktokAds: 'tiktok-ads',
    Twilio: 'twilio',
    Vercel: 'vercel',
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

export interface SlackChannelApi {
    /** Slack channel ID (e.g. C0123ABC) — pass to cdp-functions inputs.channel. */
    id: string
    /** Slack channel name without the leading '#'. */
    name: string
    /** True if the channel is private. */
    is_private: boolean
    /** True if the PostHog Slack app is a member of the channel and can post to it. */
    is_member: boolean
    /** True if the channel is shared with another Slack workspace. */
    is_ext_shared: boolean
    /** True if the channel is private and the PostHog Slack app cannot access it. */
    is_private_without_access: boolean
}

export interface SlackChannelsResponseApi {
    /** Slack channels visible to the PostHog Slack app. */
    channels: SlackChannelApi[]
    /**
     * ISO 8601 timestamp of the last full Slack API refresh (only set on full lists, not single-channel lookups).
     * @nullable
     */
    lastRefreshedAt?: string | null
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

export interface UserGitHubAccountApi {
    /**
     * GitHub account type for the installation (e.g. User or Organization).
     * @nullable
     */
    type?: string | null
    /**
     * GitHub login or organization name tied to the installation.
     * @nullable
     */
    name?: string | null
}

export interface UserGitHubIntegrationItemApi {
    /** PostHog UserIntegration row id. */
    id: string
    /** Integration kind; always `github` for this API. */
    kind: string
    /** GitHub App installation id. */
    installation_id: string
    /**
     * Repository selection mode from GitHub (e.g. selected or all).
     * @nullable
     */
    repository_selection?: string | null
    /** Installation account metadata from GitHub. */
    account?: UserGitHubAccountApi | null
    /** True when this installation id matches a team-level GitHub integration on the active project. */
    uses_shared_installation: boolean
    /** When this integration row was created. */
    created_at: string
}

export interface UserGitHubIntegrationListResponseApi {
    /** GitHub personal integrations for the authenticated user. */
    results: UserGitHubIntegrationItemApi[]
}

export interface PaginatedUserGitHubIntegrationListResponseListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: UserGitHubIntegrationListResponseApi[]
}

export interface UserGitHubLinkStartRequestApi {
    /**
     * Optional team/project id (e.g. PostHog Code); web UI uses the session's current team.
     * @nullable
     */
    team_id?: number | null
    /** Optional client hint (e.g. posthog_code) for return routing after OAuth. */
    connect_from?: string
}

export interface UserGitHubLinkStartResponseApi {
    /** URL to open in the browser to install or authorize the GitHub App for this user. */
    install_url: string
    /** OAuth or install flow used for this GitHub connection. */
    connect_flow: string
}

export type RoleExternalReferencesListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type RoleExternalReferencesLookupRetrieveParams = {
    /**
     * Integration kind (e.g., github, linear, jira, slack).
     * @minLength 1
     */
    provider: string
    /**
     * Provider organization/workspace/site identifier.
     * @minLength 1
     */
    provider_organization_id: string
    /**
     * Stable provider role identifier.
     * @minLength 1
     */
    provider_role_id?: string
    /**
     * Human-friendly provider role identifier.
     * @minLength 1
     */
    provider_role_slug?: string
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

export type UsersIntegrationsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type UsersIntegrationsGithubBranchesRetrieveParams = {
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

export type UsersIntegrationsGithubReposRetrieveParams = {
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
