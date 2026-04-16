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
 * @nullable
 */
export type ErrorTrackingAssignmentRuleApiAssignee = {
    readonly type?: 'user' | 'role'
    readonly id?: number | string
} | null | null

export interface ErrorTrackingAssignmentRuleApi {
    readonly id: string
    filters: unknown
    /** @nullable */
    readonly assignee: ErrorTrackingAssignmentRuleApiAssignee
    /**
     * @minimum -2147483648
     * @maximum 2147483647
     */
    order_key: number
    disabled_data?: unknown | null
    readonly created_at: string
    readonly updated_at: string
}

export interface PaginatedErrorTrackingAssignmentRuleListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: ErrorTrackingAssignmentRuleApi[]
}

/**
 * @nullable
 */
export type PatchedErrorTrackingAssignmentRuleApiAssignee = {
    readonly type?: 'user' | 'role'
    readonly id?: number | string
} | null | null

export interface PatchedErrorTrackingAssignmentRuleApi {
    readonly id?: string
    filters?: unknown
    /** @nullable */
    readonly assignee?: PatchedErrorTrackingAssignmentRuleApiAssignee
    /**
     * @minimum -2147483648
     * @maximum 2147483647
     */
    order_key?: number
    disabled_data?: unknown | null
    readonly created_at?: string
    readonly updated_at?: string
}

export type IntegrationKindApi = (typeof IntegrationKindApi)[keyof typeof IntegrationKindApi]

export const IntegrationKindApi = {
    Slack: 'slack',
    SlackPosthogCode: 'slack-posthog-code',
    Salesforce: 'salesforce',
    Hubspot: 'hubspot',
    GooglePubsub: 'google-pubsub',
    GoogleCloudServiceAccount: 'google-cloud-service-account',
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
    PinterestAds: 'pinterest-ads',
    CustomerioApp: 'customerio-app',
    CustomerioWebhook: 'customerio-webhook',
    CustomerioTrack: 'customerio-track',
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

/**
 * @nullable
 */
export type ErrorTrackingGroupingRuleApiAssignee = {
    readonly type?: 'user' | 'role'
    readonly id?: number | string
} | null | null

/**
 * Issue linked to this rule
 * @nullable
 */
export type ErrorTrackingGroupingRuleApiIssue = { [key: string]: string } | null | null

export interface ErrorTrackingGroupingRuleApi {
    readonly id: string
    filters: unknown
    /** @nullable */
    readonly assignee: ErrorTrackingGroupingRuleApiAssignee
    /**
     * Issue linked to this rule
     * @nullable
     */
    readonly issue: ErrorTrackingGroupingRuleApiIssue
    /**
     * @minimum -2147483648
     * @maximum 2147483647
     */
    order_key: number
    disabled_data?: unknown | null
    readonly created_at: string
    readonly updated_at: string
}

export interface PaginatedErrorTrackingGroupingRuleListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: ErrorTrackingGroupingRuleApi[]
}

/**
 * @nullable
 */
export type PatchedErrorTrackingGroupingRuleApiAssignee = {
    readonly type?: 'user' | 'role'
    readonly id?: number | string
} | null | null

/**
 * Issue linked to this rule
 * @nullable
 */
export type PatchedErrorTrackingGroupingRuleApiIssue = { [key: string]: string } | null | null

export interface PatchedErrorTrackingGroupingRuleApi {
    readonly id?: string
    filters?: unknown
    /** @nullable */
    readonly assignee?: PatchedErrorTrackingGroupingRuleApiAssignee
    /**
     * Issue linked to this rule
     * @nullable
     */
    readonly issue?: PatchedErrorTrackingGroupingRuleApiIssue
    /**
     * @minimum -2147483648
     * @maximum 2147483647
     */
    order_key?: number
    disabled_data?: unknown | null
    readonly created_at?: string
    readonly updated_at?: string
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
    readonly id: number | string | null
    readonly type: string
}

/**
 * @nullable
 */
export type ErrorTrackingIssueFullApiCohort = {
    readonly id?: number
    readonly name?: string
} | null | null

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
    /** @nullable */
    readonly cohort: ErrorTrackingIssueFullApiCohort
}

export interface PaginatedErrorTrackingIssueFullListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: ErrorTrackingIssueFullApi[]
}

/**
 * @nullable
 */
export type PatchedErrorTrackingIssueFullApiCohort = {
    readonly id?: number
    readonly name?: string
} | null | null

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
    /** @nullable */
    readonly cohort?: PatchedErrorTrackingIssueFullApiCohort
}

export interface ErrorTrackingIssueMergeRequestApi {
    /** IDs of the issues to merge into the current issue. */
    ids: string[]
}

export interface ErrorTrackingIssueMergeResponseApi {
    /** Whether the merge completed successfully. */
    success: boolean
}

export interface ErrorTrackingIssueSplitFingerprintApi {
    /** Fingerprint to split into a new issue. */
    fingerprint: string
    /** Optional name for the new issue created from this fingerprint. */
    name?: string
    /** Optional description for the new issue created from this fingerprint. */
    description?: string
}

export interface ErrorTrackingIssueSplitRequestApi {
    /** Fingerprints to split into new issues. Each fingerprint becomes its own new issue. */
    fingerprints?: ErrorTrackingIssueSplitFingerprintApi[]
}

export interface ErrorTrackingIssueSplitResponseApi {
    /** Whether the split completed successfully. */
    success: boolean
    /** IDs of the new issues created by the split. */
    new_issue_ids: string[]
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

export interface ErrorTrackingSpikeEventIssueApi {
    readonly id: string
    /** @nullable */
    readonly name: string | null
    /** @nullable */
    readonly description: string | null
}

export interface ErrorTrackingSpikeEventApi {
    readonly id: string
    readonly issue: ErrorTrackingSpikeEventIssueApi
    readonly detected_at: string
    readonly computed_baseline: number
    readonly current_bucket_value: number
}

export interface PaginatedErrorTrackingSpikeEventListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: ErrorTrackingSpikeEventApi[]
}

export interface ErrorTrackingStackFrameApi {
    readonly id: string
    /** Raw frame ID in 'hash/part' format */
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
    disabled_data?: unknown | null
    sampling_rate?: number
    readonly created_at: string
    readonly updated_at: string
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
    disabled_data?: unknown | null
    sampling_rate?: number
    readonly created_at?: string
    readonly updated_at?: string
}

/**
 * Release associated with this symbol set
 * @nullable
 */
export type ErrorTrackingSymbolSetApiRelease = { [key: string]: unknown } | null | null

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
    /**
     * Release associated with this symbol set
     * @nullable
     */
    readonly release: ErrorTrackingSymbolSetApiRelease
}

export interface PaginatedErrorTrackingSymbolSetListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: ErrorTrackingSymbolSetApi[]
}

/**
 * Release associated with this symbol set
 * @nullable
 */
export type PatchedErrorTrackingSymbolSetApiRelease = { [key: string]: unknown } | null | null

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
    /**
     * Release associated with this symbol set
     * @nullable
     */
    readonly release?: PatchedErrorTrackingSymbolSetApiRelease
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

export type ErrorTrackingSpikeEventsListParams = {
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
