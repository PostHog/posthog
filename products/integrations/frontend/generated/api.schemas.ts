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
 * * `data` - Data
 * * `product` - Product Management
 * * `founder` - Founder
 * * `leadership` - Leadership
 * * `marketing` - Marketing
 * * `sales` - Sales / Success
 * * `other` - Other
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

/**
 * @nullable
 */
export type UserBasicApiHedgehogConfig = { [key: string]: unknown } | null

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
    role_at_organization?: RoleAtOrganizationEnumApi | BlankEnumApi | null
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
 * * `anthropic` - Anthropic
 * * `apns` - Apple Push
 * * `aws-s3` - Aws S3
 * * `azure-blob` - Azure Blob
 * * `bing-ads` - Bing Ads
 * * `clickup` - Clickup
 * * `customerio-app` - Customerio App
 * * `customerio-track` - Customerio Track
 * * `customerio-webhook` - Customerio Webhook
 * * `databricks` - Databricks
 * * `email` - Email
 * * `firebase` - Firebase
 * * `github` - Github
 * * `gitlab` - Gitlab
 * * `google-ads` - Google Ads
 * * `google-analytics` - Google Analytics
 * * `google-cloud-service-account` - Google Cloud Service Account
 * * `google-cloud-storage` - Google Cloud Storage
 * * `google-pubsub` - Google Pubsub
 * * `google-search-console` - Google Search Console
 * * `google-sheets` - Google Sheets
 * * `hubspot` - Hubspot
 * * `intercom` - Intercom
 * * `jira` - Jira
 * * `linear` - Linear
 * * `linkedin-ads` - Linkedin Ads
 * * `meta-ads` - Meta Ads
 * * `pinterest-ads` - Pinterest Ads
 * * `postgresql` - Postgresql
 * * `reddit-ads` - Reddit Ads
 * * `s3-compatible` - S3 Compatible
 * * `salesforce` - Salesforce
 * * `slack` - Slack
 * * `slack-posthog-code` - Slack Posthog Code
 * * `snapchat` - Snapchat
 * * `stripe` - Stripe
 * * `tiktok-ads` - Tiktok Ads
 * * `twilio` - Twilio
 * * `vercel` - Vercel
 */
export type IntegrationKindEnumApi = (typeof IntegrationKindEnumApi)[keyof typeof IntegrationKindEnumApi]

export const IntegrationKindEnumApi = {
    Anthropic: 'anthropic',
    Apns: 'apns',
    AwsS3: 'aws-s3',
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
    GoogleAnalytics: 'google-analytics',
    GoogleCloudServiceAccount: 'google-cloud-service-account',
    GoogleCloudStorage: 'google-cloud-storage',
    GooglePubsub: 'google-pubsub',
    GoogleSearchConsole: 'google-search-console',
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
    S3Compatible: 's3-compatible',
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
    /** Whether more channels match the current search beyond this page. */
    has_more?: boolean
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
    /** GitHub repository numeric identifier. */
    id: number
    /** Repository short name (without the owner prefix). */
    name: string
    /** Fully-qualified repository name as 'owner/repo'. */
    full_name: string
    /** Whether the repository is private. */
    private?: boolean
    /** The repository's default branch (e.g. 'main'). */
    default_branch?: string
    /** Primary programming language GitHub detected for the repository. */
    language?: string
    /** ISO 8601 timestamp of the most recent push, useful for sorting by recent activity. */
    pushed_at?: string
    /** Whether the repository is archived. */
    archived?: boolean
    /** Whether the PostHog GitHub App has write access — required to open pull requests. */
    can_push?: boolean
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

export interface GitHubTeamApi {
    /** GitHub team numeric identifier. */
    id: number
    /** GitHub team slug. */
    slug: string
    /** GitHub team display name. */
    name: string
}

export interface GitHubTeamsResponseApi {
    /** List of GitHub teams available to the installation organization. */
    teams: GitHubTeamApi[]
    /** Whether more teams are available beyond this page. */
    has_more: boolean
}

export interface GoogleSearchConsoleSiteApi {
    /** Site URL in canonical Google format — `https://example.com/` for URL-prefix properties (trailing slash mandatory) or `sc-domain:example.com` for Domain properties. */
    siteUrl: string
    /** The connected user's permission level for this site. One of `siteOwner`, `siteFullUser`, `siteRestrictedUser`, `siteUnverifiedUser`. */
    permissionLevel: string
}

export interface GoogleSearchConsoleSitesResponseApi {
    sites: GoogleSearchConsoleSiteApi[]
}

export interface JiraProjectApi {
    /** Jira project ID. */
    id: string
    /** Jira project key to pass as error tracking config.project_key. */
    key: string
    /** Jira project display name. */
    name: string
}

export interface JiraProjectsResponseApi {
    /** Jira projects available to this integration. */
    projects: JiraProjectApi[]
}

export interface LinearTeamApi {
    /** Linear team ID to pass as error tracking config.team_id. */
    id: string
    /** Linear team display name. */
    name: string
}

export interface LinearTeamsResponseApi {
    /** Linear teams available to this integration. */
    teams: LinearTeamApi[]
}

export interface GitHubLinkExistingRequestApi {
    /**
     * Sibling team in the same organization whose GitHub installation should be reused.
     * @nullable
     */
    source_team_id?: number | null
    /** GitHub installation ID to link; resolved within the organization when source_team_id is omitted. */
    installation_id?: string
}

/**
 * * `posthog_code` - posthog_code
 */
export type ConnectFromEnumApi = (typeof ConnectFromEnumApi)[keyof typeof ConnectFromEnumApi]

export const ConnectFromEnumApi = {
    PosthogCode: 'posthog_code',
} as const

export interface GitHubOAuthAuthorizeRequestApi {
    /** GitHub installation ID to carry through the User OAuth flow. */
    installation_id?: string
    /** Relative URL to redirect to after the OAuth flow completes. */
    next?: string
    /** Originating surface for the connect flow; only 'posthog_code' is recognized.
     *
     * * `posthog_code` - posthog_code */
    connect_from?: ConnectFromEnumApi
}

export interface GitHubOAuthAuthorizeResponseApi {
    /** GitHub User OAuth URL the client should redirect to. */
    oauth_url: string
}

export interface GitHubPrepareCallbackRequestApi {
    /** Relative URL to redirect to after GitHub setup completes (e.g. account-connected for PostHog Code). */
    next?: string
    /** GitHub installation ID being managed; binds the seeded update state so a callback can't swap in a different installation. */
    installation_id?: string
}

export interface IntegrationAccessRequestApi {
    /** The kind of integration the member is requesting be connected (e.g. 'slack', 'github').
     *
     * * `anthropic` - Anthropic
     * * `apns` - Apple Push
     * * `aws-s3` - Aws S3
     * * `azure-blob` - Azure Blob
     * * `bing-ads` - Bing Ads
     * * `clickup` - Clickup
     * * `customerio-app` - Customerio App
     * * `customerio-track` - Customerio Track
     * * `customerio-webhook` - Customerio Webhook
     * * `databricks` - Databricks
     * * `email` - Email
     * * `firebase` - Firebase
     * * `github` - Github
     * * `gitlab` - Gitlab
     * * `google-ads` - Google Ads
     * * `google-analytics` - Google Analytics
     * * `google-cloud-service-account` - Google Cloud Service Account
     * * `google-cloud-storage` - Google Cloud Storage
     * * `google-pubsub` - Google Pubsub
     * * `google-search-console` - Google Search Console
     * * `google-sheets` - Google Sheets
     * * `hubspot` - Hubspot
     * * `intercom` - Intercom
     * * `jira` - Jira
     * * `linear` - Linear
     * * `linkedin-ads` - Linkedin Ads
     * * `meta-ads` - Meta Ads
     * * `pinterest-ads` - Pinterest Ads
     * * `postgresql` - Postgresql
     * * `reddit-ads` - Reddit Ads
     * * `s3-compatible` - S3 Compatible
     * * `salesforce` - Salesforce
     * * `slack` - Slack
     * * `slack-posthog-code` - Slack Posthog Code
     * * `snapchat` - Snapchat
     * * `stripe` - Stripe
     * * `tiktok-ads` - Tiktok Ads
     * * `twilio` - Twilio
     * * `vercel` - Vercel */
    kind: IntegrationKindEnumApi
    /**
     * Explanation from the requester of why this integration is needed. Shown to admins in the notification email.
     * @maxLength 2000
     */
    reason: string
}

export interface IntegrationAccessRequestResponseApi {
    /** Whether the access request was accepted and the project admins were notified. */
    success: boolean
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
     * * `anthropic` - Anthropic
     * * `apns` - Apple Push
     * * `aws-s3` - Aws S3
     * * `azure-blob` - Azure Blob
     * * `bing-ads` - Bing Ads
     * * `clickup` - Clickup
     * * `customerio-app` - Customerio App
     * * `customerio-track` - Customerio Track
     * * `customerio-webhook` - Customerio Webhook
     * * `databricks` - Databricks
     * * `email` - Email
     * * `firebase` - Firebase
     * * `github` - Github
     * * `gitlab` - Gitlab
     * * `google-ads` - Google Ads
     * * `google-analytics` - Google Analytics
     * * `google-cloud-service-account` - Google Cloud Service Account
     * * `google-cloud-storage` - Google Cloud Storage
     * * `google-pubsub` - Google Pubsub
     * * `google-search-console` - Google Search Console
     * * `google-sheets` - Google Sheets
     * * `hubspot` - Hubspot
     * * `intercom` - Intercom
     * * `jira` - Jira
     * * `linear` - Linear
     * * `linkedin-ads` - Linkedin Ads
     * * `meta-ads` - Meta Ads
     * * `pinterest-ads` - Pinterest Ads
     * * `postgresql` - Postgresql
     * * `reddit-ads` - Reddit Ads
     * * `s3-compatible` - S3 Compatible
     * * `salesforce` - Salesforce
     * * `slack` - Slack
     * * `slack-posthog-code` - Slack Posthog Code
     * * `snapchat` - Snapchat
     * * `stripe` - Stripe
     * * `tiktok-ads` - Tiktok Ads
     * * `twilio` - Twilio
     * * `vercel` - Vercel
     */
    kind?: IntegrationsListKind
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type IntegrationsListKind = (typeof IntegrationsListKind)[keyof typeof IntegrationsListKind]

export const IntegrationsListKind = {
    Anthropic: 'anthropic',
    Apns: 'apns',
    AwsS3: 'aws-s3',
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
    GoogleAnalytics: 'google-analytics',
    GoogleCloudServiceAccount: 'google-cloud-service-account',
    GoogleCloudStorage: 'google-cloud-storage',
    GooglePubsub: 'google-pubsub',
    GoogleSearchConsole: 'google-search-console',
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
    S3Compatible: 's3-compatible',
    Salesforce: 'salesforce',
    Slack: 'slack',
    SlackPosthogCode: 'slack-posthog-code',
    Snapchat: 'snapchat',
    Stripe: 'stripe',
    TiktokAds: 'tiktok-ads',
    Twilio: 'twilio',
    Vercel: 'vercel',
} as const

export type IntegrationsChannelsRetrieveParams = {
    /**
     * Maximum number of channels to return per request (max 200).
     * @minimum 1
     * @maximum 200
     */
    limit?: number
    /**
     * Number of channels to skip before returning results.
     * @minimum 0
     */
    offset?: number
    /**
     * Optional case-insensitive channel name or ID search query.
     */
    search?: string
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

export type IntegrationsGithubTeamsRetrieveParams = {
    /**
     * Maximum number of teams to return per request (max 500).
     * @minimum 1
     * @maximum 500
     */
    limit?: number
    /**
     * Number of teams to skip before returning results.
     * @minimum 0
     */
    offset?: number
    /**
     * Optional case-insensitive team name or slug search query.
     */
    search?: string
}
