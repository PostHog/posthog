/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
export interface ErrorTrackingAssignmentRuleApi {
    readonly id: string
    filters: unknown
    readonly assignee: string
    /**
     * @minimum -2147483648
     * @maximum 2147483647
     */
    order_key: number
    disabled_data?: unknown | null
}

export interface PaginatedErrorTrackingAssignmentRuleListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: ErrorTrackingAssignmentRuleApi[]
}

export interface PatchedErrorTrackingAssignmentRuleApi {
    readonly id?: string
    filters?: unknown
    readonly assignee?: string
    /**
     * @minimum -2147483648
     * @maximum 2147483647
     */
    order_key?: number
    disabled_data?: unknown | null
}

/**
 * * `web` - Web
 */
export type LibraryEnumApi = (typeof LibraryEnumApi)[keyof typeof LibraryEnumApi]

export const LibraryEnumApi = {
    Web: 'web',
} as const

/**
 * * `all` - All
 * `any` - Any
 */
export type MatchTypeEnumApi = (typeof MatchTypeEnumApi)[keyof typeof MatchTypeEnumApi]

export const MatchTypeEnumApi = {
    All: 'all',
    Any: 'any',
} as const

export interface ErrorTrackingAutoCaptureControlsApi {
    readonly id: string
    readonly library: LibraryEnumApi
    match_type?: MatchTypeEnumApi
    /** @pattern ^-?\d{0,1}(?:\.\d{0,2})?$ */
    sample_rate?: string
    linked_feature_flag?: unknown | null
    /** @nullable */
    event_triggers?: (string | null)[] | null
    /** @nullable */
    url_triggers?: (unknown | null)[] | null
    /** @nullable */
    url_blocklist?: (unknown | null)[] | null
}

export interface PaginatedErrorTrackingAutoCaptureControlsListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: ErrorTrackingAutoCaptureControlsApi[]
}

export interface PatchedErrorTrackingAutoCaptureControlsApi {
    readonly id?: string
    readonly library?: LibraryEnumApi
    match_type?: MatchTypeEnumApi
    /** @pattern ^-?\d{0,1}(?:\.\d{0,2})?$ */
    sample_rate?: string
    linked_feature_flag?: unknown | null
    /** @nullable */
    event_triggers?: (string | null)[] | null
    /** @nullable */
    url_triggers?: (unknown | null)[] | null
    /** @nullable */
    url_blocklist?: (unknown | null)[] | null
}

export type IntegrationKindApi = (typeof IntegrationKindApi)[keyof typeof IntegrationKindApi]

export const IntegrationKindApi = {
    Slack: 'slack',
    Salesforce: 'salesforce',
    Hubspot: 'hubspot',
    GooglePubsub: 'google-pubsub',
    GoogleCloudStorage: 'google-cloud-storage',
    GoogleAds: 'google-ads',
    GoogleSheets: 'google-sheets',
    LinkedinAds: 'linkedin-ads',
    Snapchat: 'snapchat',
    Intercom: 'intercom',
    Email: 'email',
    Twilio: 'twilio',
    Linear: 'linear',
    Github: 'github',
    Gitlab: 'gitlab',
    MetaAds: 'meta-ads',
    Clickup: 'clickup',
    RedditAds: 'reddit-ads',
    Databricks: 'databricks',
    TiktokAds: 'tiktok-ads',
    BingAds: 'bing-ads',
    Vercel: 'vercel',
    AzureBlob: 'azure-blob',
    Firebase: 'firebase',
    Jira: 'jira',
} as const

export interface ErrorTrackingExternalReferenceIntegrationApi {
    display_name: string
    id: number
    kind: IntegrationKindApi
}

export interface ErrorTrackingExternalReferenceApi {
    external_url: string
    id: string
    integration: ErrorTrackingExternalReferenceIntegrationApi
}

export interface PaginatedErrorTrackingExternalReferenceListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: ErrorTrackingExternalReferenceApi[]
}

export interface PatchedErrorTrackingExternalReferenceApi {
    readonly id?: string
    readonly integration?: ErrorTrackingExternalReferenceIntegrationApi
    integration_id?: number
    config?: unknown
    issue?: string
    readonly external_url?: string
}

export interface ErrorTrackingFingerprintApi {
    fingerprint: string
    readonly issue_id: string
    readonly created_at: string
}

export interface PaginatedErrorTrackingFingerprintListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: ErrorTrackingFingerprintApi[]
}

export interface ErrorTrackingGroupingRuleApi {
    readonly id: string
    filters: unknown
    readonly assignee: string
    /**
     * @minimum -2147483648
     * @maximum 2147483647
     */
    order_key: number
    disabled_data?: unknown | null
}

export interface PaginatedErrorTrackingGroupingRuleListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: ErrorTrackingGroupingRuleApi[]
}

export interface PatchedErrorTrackingGroupingRuleApi {
    readonly id?: string
    filters?: unknown
    readonly assignee?: string
    /**
     * @minimum -2147483648
     * @maximum 2147483647
     */
    order_key?: number
    disabled_data?: unknown | null
}

/**
 * * `archived` - Archived
 * `active` - Active
 * `resolved` - Resolved
 * `pending_release` - Pending release
 * `suppressed` - Suppressed
 */
export type ErrorTrackingIssueFullStatusEnumApi =
    (typeof ErrorTrackingIssueFullStatusEnumApi)[keyof typeof ErrorTrackingIssueFullStatusEnumApi]

export const ErrorTrackingIssueFullStatusEnumApi = {
    Archived: 'archived',
    Active: 'active',
    Resolved: 'resolved',
    PendingRelease: 'pending_release',
    Suppressed: 'suppressed',
} as const

export interface ErrorTrackingIssueAssignmentApi {
    readonly id: string
    readonly type: string
}

export interface ErrorTrackingIssueFullApi {
    readonly id: string
    status?: ErrorTrackingIssueFullStatusEnumApi
    /** @nullable */
    name?: string | null
    /** @nullable */
    description?: string | null
    first_seen: string
    assignee: ErrorTrackingIssueAssignmentApi
    external_issues: ErrorTrackingExternalReferenceApi[]
    readonly cohort: string
}

export interface PaginatedErrorTrackingIssueFullListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: ErrorTrackingIssueFullApi[]
}

export interface PatchedErrorTrackingIssueFullApi {
    readonly id?: string
    status?: ErrorTrackingIssueFullStatusEnumApi
    /** @nullable */
    name?: string | null
    /** @nullable */
    description?: string | null
    first_seen?: string
    assignee?: ErrorTrackingIssueAssignmentApi
    external_issues?: ErrorTrackingExternalReferenceApi[]
    readonly cohort?: string
}

export interface ErrorTrackingReleaseApi {
    readonly id: string
    hash_id: string
    readonly team_id: number
    readonly created_at: string
    metadata?: unknown | null
    version: string
    project: string
}

export interface PaginatedErrorTrackingReleaseListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: ErrorTrackingReleaseApi[]
}

export interface PatchedErrorTrackingReleaseApi {
    readonly id?: string
    hash_id?: string
    readonly team_id?: number
    readonly created_at?: string
    metadata?: unknown | null
    version?: string
    project?: string
}

export interface ErrorTrackingStackFrameApi {
    readonly id: string
    readonly raw_id: string
    readonly created_at: string
    contents: unknown
    resolved: boolean
    context?: unknown | null
    symbol_set_ref?: string
    readonly release: ErrorTrackingReleaseApi
}

export interface PaginatedErrorTrackingStackFrameListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: ErrorTrackingStackFrameApi[]
}

export interface ErrorTrackingSuppressionRuleApi {
    readonly id: string
    filters: unknown
    /**
     * @minimum -2147483648
     * @maximum 2147483647
     */
    order_key: number
}

export interface PaginatedErrorTrackingSuppressionRuleListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: ErrorTrackingSuppressionRuleApi[]
}

export interface PatchedErrorTrackingSuppressionRuleApi {
    readonly id?: string
    filters?: unknown
    /**
     * @minimum -2147483648
     * @maximum 2147483647
     */
    order_key?: number
}

export interface ErrorTrackingSymbolSetApi {
    readonly id: string
    ref: string
    readonly team_id: number
    readonly created_at: string
    /** @nullable */
    last_used?: string | null
    /** @nullable */
    storage_ptr?: string | null
    /** @nullable */
    failure_reason?: string | null
    readonly release: string
}

export interface PaginatedErrorTrackingSymbolSetListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: ErrorTrackingSymbolSetApi[]
}

export interface PatchedErrorTrackingSymbolSetApi {
    readonly id?: string
    ref?: string
    readonly team_id?: number
    readonly created_at?: string
    /** @nullable */
    last_used?: string | null
    /** @nullable */
    storage_ptr?: string | null
    /** @nullable */
    failure_reason?: string | null
    readonly release?: string
}

export type ErrorTrackingAssignmentRulesListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type ErrorTrackingAutocaptureControlsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type ErrorTrackingExternalReferencesListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type ErrorTrackingFingerprintsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type ErrorTrackingGroupingRulesListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type ErrorTrackingIssuesListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type ErrorTrackingReleasesListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type ErrorTrackingStackFramesListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type ErrorTrackingSuppressionRulesListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type ErrorTrackingSymbolSetsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type ErrorTrackingReleasesList2Params = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type ErrorTrackingSymbolSetsList2Params = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}
