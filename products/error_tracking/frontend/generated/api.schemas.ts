/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
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
 * * `archived` - Archived
 * `active` - Active
 * `resolved` - Resolved
 * `pending_release` - Pending release
 * `suppressed` - Suppressed
 */
export type ErrorTrackingIssueFullStatusEnumApi =
    (typeof ErrorTrackingIssueFullStatusEnumApi)[keyof typeof ErrorTrackingIssueFullStatusEnumApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const ErrorTrackingIssueFullStatusEnumApi = {
    archived: 'archived',
    active: 'active',
    resolved: 'resolved',
    pending_release: 'pending_release',
    suppressed: 'suppressed',
} as const

export interface ErrorTrackingIssueAssignmentApi {
    readonly id: string
    readonly type: string
}

/**
 * * `slack` - Slack
 * `salesforce` - Salesforce
 * `hubspot` - Hubspot
 * `google-pubsub` - Google Pubsub
 * `google-cloud-storage` - Google Cloud Storage
 * `google-ads` - Google Ads
 * `google-sheets` - Google Sheets
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
 */
export type KindCf2EnumApi = (typeof KindCf2EnumApi)[keyof typeof KindCf2EnumApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const KindCf2EnumApi = {
    slack: 'slack',
    salesforce: 'salesforce',
    hubspot: 'hubspot',
    'google-pubsub': 'google-pubsub',
    'google-cloud-storage': 'google-cloud-storage',
    'google-ads': 'google-ads',
    'google-sheets': 'google-sheets',
    snapchat: 'snapchat',
    'linkedin-ads': 'linkedin-ads',
    'reddit-ads': 'reddit-ads',
    'tiktok-ads': 'tiktok-ads',
    'bing-ads': 'bing-ads',
    intercom: 'intercom',
    email: 'email',
    linear: 'linear',
    github: 'github',
    gitlab: 'gitlab',
    'meta-ads': 'meta-ads',
    twilio: 'twilio',
    clickup: 'clickup',
    vercel: 'vercel',
    databricks: 'databricks',
    'azure-blob': 'azure-blob',
    firebase: 'firebase',
    jira: 'jira',
} as const

export interface ErrorTrackingExternalReferenceIntegrationApi {
    readonly id: number
    readonly kind: KindCf2EnumApi
    readonly display_name: string
}

export interface ErrorTrackingExternalReferenceApi {
    readonly id: string
    readonly integration: ErrorTrackingExternalReferenceIntegrationApi
    integration_id: number
    config: unknown
    issue: string
    readonly external_url: string
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
    metadata?: unknown
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
    metadata?: unknown
    version?: string
    project?: string
}

export interface ErrorTrackingStackFrameApi {
    readonly id: string
    readonly raw_id: string
    readonly created_at: string
    contents: unknown
    resolved: boolean
    context?: unknown
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

export type EnvironmentsErrorTrackingFingerprintsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type EnvironmentsErrorTrackingIssuesListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type EnvironmentsErrorTrackingReleasesListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type EnvironmentsErrorTrackingStackFramesListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type EnvironmentsErrorTrackingSymbolSetsListParams = {
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
