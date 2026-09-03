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
 * * `screenshot` - Screenshot
 * * `iframe` - Iframe
 * * `recording` - Recording
 */
export type SavedHeatmapTypeEnumApi = (typeof SavedHeatmapTypeEnumApi)[keyof typeof SavedHeatmapTypeEnumApi]

export const SavedHeatmapTypeEnumApi = {
    Screenshot: 'screenshot',
    Iframe: 'iframe',
    Recording: 'recording',
} as const

/**
 * * `server` - Server
 * * `toolbar` - Toolbar
 */
export type SavedHeatmapSourceEnumApi = (typeof SavedHeatmapSourceEnumApi)[keyof typeof SavedHeatmapSourceEnumApi]

export const SavedHeatmapSourceEnumApi = {
    Server: 'server',
    Toolbar: 'toolbar',
} as const

/**
 * * `processing` - Processing
 * * `completed` - Completed
 * * `failed` - Failed
 */
export type SavedHeatmapStatusEnumApi = (typeof SavedHeatmapStatusEnumApi)[keyof typeof SavedHeatmapStatusEnumApi]

export const SavedHeatmapStatusEnumApi = {
    Processing: 'processing',
    Completed: 'completed',
    Failed: 'failed',
} as const

export interface HeatmapSnapshotMetadataApi {
    /** Viewport width (CSS pixels) this screenshot was rendered at. */
    width: number
    /** Whether the rendered image for this width is ready to fetch from the content endpoint. */
    has_content: boolean
}

/**
 * * `engineering` - Engineering
 * * `data` - Data
 * * `product` - Product Management
 * * `founder` - Founder
 * * `leadership` - Leadership
 * * `marketing` - Marketing
 * * `sales` - Sales / Success
 * * `student` - Student
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
    Student: 'student',
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
 * Mixin for serializers to add user access control fields
 */
export interface HeatmapScreenshotResponseApi {
    readonly id: string
    /** Short, URL-safe identifier used as the lookup key for saved-heatmap routes. */
    readonly short_id: string
    /**
     * Human-readable label for the saved heatmap.
     * @maxLength 400
     * @nullable
     */
    name?: string | null
    /**
     * The page URL this saved heatmap renders and overlays data on.
     * @maxLength 2000
     */
    url: string
    /** URL whose heatmap data is overlaid on the screenshot (defaults to 'url'). */
    data_url?: string | null
    /** Viewport widths (CSS pixels) the screenshot is rendered at. */
    readonly target_widths: readonly number[]
    /** Render mode: 'screenshot', 'iframe', or 'recording'.
     *
     * * `screenshot` - Screenshot
     * * `iframe` - Iframe
     * * `recording` - Recording */
    type?: SavedHeatmapTypeEnumApi
    /** How the screenshot was captured: 'server' (rendered headlessly via Browserless) or 'toolbar' (captured client-side from the on-page toolbar, e.g. for pages behind a login).
     *
     * * `server` - Server
     * * `toolbar` - Toolbar */
    readonly source: SavedHeatmapSourceEnumApi
    /** Screenshot generation status: 'processing', 'completed', or 'failed'.
     *
     * * `processing` - Processing
     * * `completed` - Completed
     * * `failed` - Failed */
    readonly status: SavedHeatmapStatusEnumApi
    /** Whether at least one rendered image is ready to fetch. */
    readonly has_content: boolean
    /** Per-width render metadata. Fetch the actual image bytes for a width from the content endpoint. */
    readonly snapshots: readonly HeatmapSnapshotMetadataApi[]
    /** Soft-delete flag; deleted heatmaps are hidden from the list. */
    deleted?: boolean
    /** Whether the headless browser dismisses cookie/consent banners before capturing the screenshot. Only applies to 'screenshot' heatmaps. */
    block_consent_modals?: boolean
    readonly created_by: UserBasicApi
    readonly created_at: string
    readonly updated_at: string
    /**
     * Error detail when screenshot generation failed, otherwise null.
     * @nullable
     */
    readonly exception: string | null
    /**
     * The effective access level the user has for this object
     * @nullable
     */
    readonly user_access_level: string | null
}

export interface HeatmapResponseItemApi {
    count: number
    pointer_y: number
    pointer_relative_x: number
    pointer_target_fixed: boolean
}

export interface HeatmapFoldSummaryApi {
    /** Number of non-fixed interactions of this type on the page in the window (the population the above/below-the-fold split applies to; fixed-position elements are excluded since they're always on screen). */
    total_count: number
    /** How many of those interactions happened below the user's initial viewport — i.e. they had to scroll to reach them. */
    below_fold_count: number
    /** Percentage of non-fixed interactions that were below the initial viewport (0-100). A high value means engaged content sits off the first screen and is a candidate to move up. */
    pct_below_fold: number
    /**
     * Median viewport height in CSS pixels across the matched interactions — the typical fold line to recommend against. Null when there are no interactions.
     * @nullable
     */
    median_viewport_height: number | null
}

export interface HeatmapsResponseApi {
    results: HeatmapResponseItemApi[]
    /** Above/below-the-fold summary for the returned interactions. Present for click/rageclick/mousemove; omitted for scrolldepth. */
    fold?: HeatmapFoldSummaryApi | null
    /** True when more coordinate points exist beyond the returned page. Raise 'limit' or page with 'offset' to fetch them. Always false for scrolldepth, which returns every bucket. */
    has_more?: boolean
}

export interface HeatmapEventItemApi {
    /** @nullable */
    session_id?: string | null
    distinct_id: string
    timestamp: string
    pointer_relative_x: number
    pointer_y: number
    current_url: string
    type: string
}

export interface HeatmapEventsResponseApi {
    results: HeatmapEventItemApi[]
    total_count: number
    has_more: boolean
}

export interface SavedHeatmapListResponseApi {
    results: HeatmapScreenshotResponseApi[]
    /** Total number of saved heatmaps matching the filters. */
    count: number
}

export interface SavedHeatmapRequestApi {
    /**
     * Human-readable label for the saved heatmap.
     * @maxLength 400
     * @nullable
     */
    name?: string | null
    /**
     * Exact page URL to render and overlay heatmap data on. Wildcards are not allowed.
     * @maxLength 2000
     */
    url: string
    /** URL whose heatmap data is overlaid on the screenshot. Defaults to 'url' when omitted. */
    data_url?: string | null
    /**
     * Viewport widths (px, 100-3000) to render the heatmap screenshot at — one render per width. Defaults to [320, 375, 425, 768, 1024, 1440, 1920] when omitted. At most 16 widths.
     * @maxItems 16
     * @items.minimum 100
     * @items.maximum 3000
     */
    widths?: number[]
    /** Render mode: 'screenshot' (renders the page headlessly, default), 'iframe', or 'recording'. Only 'screenshot' generates image bytes.
     *
     * * `screenshot` - Screenshot
     * * `iframe` - Iframe
     * * `recording` - Recording */
    type?: SavedHeatmapTypeEnumApi
    /** Set true to soft-delete the saved heatmap. */
    deleted?: boolean
    /** When true, ask the headless browser to dismiss cookie/consent banners before capturing the screenshot. Off by default: the blocker can stall the render on some sites and time out. Only applies to 'screenshot' heatmaps. */
    block_consent_modals?: boolean
}

export interface PatchedSavedHeatmapRequestApi {
    /**
     * Human-readable label for the saved heatmap.
     * @maxLength 400
     * @nullable
     */
    name?: string | null
    /**
     * Exact page URL to render and overlay heatmap data on. Wildcards are not allowed.
     * @maxLength 2000
     */
    url?: string
    /** URL whose heatmap data is overlaid on the screenshot. Defaults to 'url' when omitted. */
    data_url?: string | null
    /**
     * Viewport widths (px, 100-3000) to render the heatmap screenshot at — one render per width. Defaults to [320, 375, 425, 768, 1024, 1440, 1920] when omitted. At most 16 widths.
     * @maxItems 16
     * @items.minimum 100
     * @items.maximum 3000
     */
    widths?: number[]
    /** Render mode: 'screenshot' (renders the page headlessly, default), 'iframe', or 'recording'. Only 'screenshot' generates image bytes.
     *
     * * `screenshot` - Screenshot
     * * `iframe` - Iframe
     * * `recording` - Recording */
    type?: SavedHeatmapTypeEnumApi
    /** Set true to soft-delete the saved heatmap. */
    deleted?: boolean
    /** When true, ask the headless browser to dismiss cookie/consent banners before capturing the screenshot. Off by default: the blocker can stall the render on some sites and time out. Only applies to 'screenshot' heatmaps. */
    block_consent_modals?: boolean
}

export interface SavedHeatmapCaptureRequestApi {
    /**
     * Single screenshot of the page, captured client-side by the toolbar (JPEG or PNG). Max 20MB. Pair with 'width'. Use 'images'/'widths' instead to save several viewport widths on one heatmap.
     * @nullable
     */
    image?: string | null
    /**
     * Viewport width (CSS pixels) the single 'image' was captured at.
     * @minimum 100
     * @maximum 3000
     */
    width?: number
    /**
     * One screenshot per viewport width, parallel to 'widths' (same length, same order). Lets a single toolbar capture cover the same viewport widths the server renders. At most 16 widths.
     * @maxItems 16
     */
    images?: string[]
    /**
     * Viewport widths (CSS pixels) the 'images' were captured at, parallel to 'images'.
     * @maxItems 16
     * @items.minimum 100
     * @items.maximum 3000
     */
    widths?: number[]
    /**
     * Exact page URL the screenshot was captured on. Wildcards are not allowed; this is stored as both the heatmap URL and its data URL, so the overlay reads aggregate data for this exact URL.
     * @maxLength 2000
     */
    url: string
    /**
     * Human-readable label for the saved heatmap. Defaults to the URL when omitted.
     * @maxLength 400
     */
    name?: string
}

export interface HeatmapPreflightRequestApi {
    /** Exact page URL to probe. Wildcards are not allowed. This is the URL that would be loaded in the live preview iframe, not the data URL used to look up heatmap events. */
    url: string
}

/**
 * * `allowed` - allowed
 * * `blocked` - blocked
 * * `unknown` - unknown
 */
export type FramingEnumApi = (typeof FramingEnumApi)[keyof typeof FramingEnumApi]

export const FramingEnumApi = {
    Allowed: 'allowed',
    Blocked: 'blocked',
    Unknown: 'unknown',
} as const

/**
 * * `x_frame_options` - x_frame_options
 * * `frame_ancestors` - frame_ancestors
 */
export type BlockedByEnumApi = (typeof BlockedByEnumApi)[keyof typeof BlockedByEnumApi]

export const BlockedByEnumApi = {
    XFrameOptions: 'x_frame_options',
    FrameAncestors: 'frame_ancestors',
} as const

export interface HeatmapPreflightResponseApi {
    /** Whether the page can be embedded in the live preview iframe. 'blocked' means the site's own headers forbid it, so only a screenshot or session recording background can work. 'unknown' means we could not tell, for example because the page was unreachable or redirected.
     *
     * * `allowed` - allowed
     * * `blocked` - blocked
     * * `unknown` - unknown */
    framing: FramingEnumApi
    /** Which response header forbids embedding, when framing is 'blocked'. Null otherwise.
     *
     * * `x_frame_options` - x_frame_options
     * * `frame_ancestors` - frame_ancestors */
    blocked_by: BlockedByEnumApi | null
    /**
     * HTTP status the page returned to us. A 4xx or 5xx here points at the customer's host or CDN rather than at PostHog. Null when the page could not be reached at all.
     * @nullable
     */
    http_status: number | null
    /**
     * Short whitespace-collapsed excerpt of the response body, only present for non-2xx responses, so the user can see what their host returned. Truncated.
     * @nullable
     */
    body_excerpt: string | null
}

export interface HeatmapPrewarmRequestApi {
    /** Exact page URL to speculatively render ahead of heatmap creation. Wildcards are not allowed. */
    url: string
    /** When true, ask the headless browser to dismiss cookie/consent banners before capturing. Must match the value used at creation time for the prewarmed render to be reused. */
    block_consent_modals?: boolean
}

export interface LlmsTxtFetchRequestApi {
    /**
     * Public HTTP or HTTPS URL of the llms.txt file to load.
     * @maxLength 2048
     */
    url: string
}

export interface LlmsTxtFetchResponseApi {
    /** UTF-8 contents of the fetched llms.txt file. */
    content: string
    /** Final public URL after redirects. */
    url: string
}

/**
 * * `Up` - Up
 * * `Down` - Down
 */
export type WoWChangeDirectionEnumApi = (typeof WoWChangeDirectionEnumApi)[keyof typeof WoWChangeDirectionEnumApi]

export const WoWChangeDirectionEnumApi = {
    Up: 'Up',
    Down: 'Down',
} as const

export interface WoWChangeApi {
    /** Absolute percentage change, rounded to nearest integer. */
    percent: number
    /** Direction of the change relative to the prior period.
     *
     * * `Up` - Up
     * * `Down` - Down */
    direction: WoWChangeDirectionEnumApi
    /** Hex color indicating whether the change is a positive or negative signal. */
    color: string
    /** Short label, e.g. 'Up 12%'. */
    text: string
    /** Verbose label, e.g. 'Up 12% from prior period'. */
    long_text: string
}

export interface NumericMetricApi {
    /** Value for the most recent period. */
    current: number
    /**
     * Value for the prior period, if available.
     * @nullable
     */
    previous: number | null
    /** Period-over-period change, null when not meaningful. */
    change: WoWChangeApi | null
}

export interface DurationMetricApi {
    /** Human-readable duration, e.g. '2m 34s'. */
    current: string
    /**
     * Prior-period duration, e.g. '2m 10s'.
     * @nullable
     */
    previous: string | null
    /** Period-over-period change, null when not meaningful. */
    change: WoWChangeApi | null
}

export interface TopPageApi {
    /** Host for the page, if recorded. */
    host: string
    /** URL path. */
    path: string
    /** Unique visitors in the period. */
    visitors: number
    /** Period-over-period change in visitors, null when not meaningful. */
    change: WoWChangeApi | null
}

export interface TopSourceApi {
    /** Initial referring domain. */
    name: string
    /** Unique visitors from this source. */
    visitors: number
    /** Period-over-period change in visitors, null when not meaningful. */
    change: WoWChangeApi | null
}

export interface GoalApi {
    /** Goal name (action name). */
    name: string
    /** Total conversions in the period. */
    conversions: number
    /** Period-over-period change in conversions, null when not meaningful. */
    change: WoWChangeApi | null
}

export interface RecapPersonaApi {
    /** Stable persona identifier. One of: just_getting_started, conversion_machine, traffic_magnet, crowd_favorite, search_hog, word_of_mouth, loyal_following, rising_star, steady_hog. */
    id: string
    /** Display name for the persona, e.g. 'Traffic Magnet'. */
    name: string
    /** Emoji representing the persona. */
    emoji: string
    /** One-line explanation of why this persona was assigned this week. */
    blurb: string
    /** Hex accent color for rendering the persona card. */
    color: string
}

export interface RecapHighlightApi {
    /** Stable highlight identifier, e.g. 'milestone', 'rising_page', 'top_source'. */
    id: string
    /** Emoji for the highlight. */
    emoji: string
    /** Short headline for the highlight, e.g. 'Rising star page'. */
    title: string
    /** The standout value, e.g. a page path or visitor count. */
    value: string
    /** Supporting sentence for the highlight. */
    detail: string
}

export interface WebAnalyticsRecapResponseApi {
    /** Unique visitors. */
    visitors: NumericMetricApi
    /** Total pageviews. */
    pageviews: NumericMetricApi
    /** Total sessions. */
    sessions: NumericMetricApi
    /** Bounce rate (0–100). */
    bounce_rate: NumericMetricApi
    /** Average session duration. */
    avg_session_duration: DurationMetricApi
    /** Top 5 pages by unique visitors. */
    top_pages: TopPageApi[]
    /** Top 5 traffic sources by unique visitors. */
    top_sources: TopSourceApi[]
    /** Goal conversions. */
    goals: GoalApi[]
    /** Link to the Web analytics dashboard for this project. */
    dashboard_url: string
    /** The single weekly persona assigned from this week's data. */
    persona: RecapPersonaApi
    /** Up to three screenshot-worthy superlatives for the week. */
    highlights: RecapHighlightApi[]
    /** Human-readable period label, e.g. 'Last 7 days'. */
    period_label: string
    /** First date included in the recap period, in the project timezone. */
    period_start: string
    /** Final date included in the recap period, in the project timezone. */
    period_end: string
    /** Name of the project this recap is for. */
    project_name: string
    /** Canonical link to this project's weekly recap. */
    recap_url: string
}

export interface WeeklyDigestResponseApi {
    /** Unique visitors. */
    visitors: NumericMetricApi
    /** Total pageviews. */
    pageviews: NumericMetricApi
    /** Total sessions. */
    sessions: NumericMetricApi
    /** Bounce rate (0–100). */
    bounce_rate: NumericMetricApi
    /** Average session duration. */
    avg_session_duration: DurationMetricApi
    /** Top 5 pages by unique visitors. */
    top_pages: TopPageApi[]
    /** Top 5 traffic sources by unique visitors. */
    top_sources: TopSourceApi[]
    /** Goal conversions. */
    goals: GoalApi[]
    /** Link to the Web analytics dashboard for this project. */
    dashboard_url: string
}

export interface AcknowledgeCelebrationRequestApi {
    /** Track of the celebration being acknowledged. */
    track_key: string
    /**
     * Stage number being acknowledged, 1-5.
     * @minimum 1
     * @maximum 5
     */
    stage: number
}

export interface AcknowledgeCelebrationResponseApi {
    /** True if a matching pending celebration was cleared (idempotent). */
    acknowledged: boolean
}

/**
 * * `user` - user
 * * `team` - team
 */
export type AchievementDefinitionScopeEnumApi =
    (typeof AchievementDefinitionScopeEnumApi)[keyof typeof AchievementDefinitionScopeEnumApi]

export const AchievementDefinitionScopeEnumApi = {
    User: 'user',
    Team: 'team',
} as const

export interface AchievementStageApi {
    /** Stage number within the track, 1-5. */
    stage: number
    /** Stage name within the track, e.g. 'On a roll'. */
    name: string
    /** Progress value needed to unlock this stage, resolved for the user's streak arm. */
    threshold: number
}

export interface AchievementDefinitionApi {
    /** Stable track identifier, e.g. 'streak'. */
    key: string
    /** Human-readable track name. */
    display_name: string
    /** One-line description of what the track rewards. */
    description: string
    /** Whether the track is tracked per user or per team.
     *
     * * `user` - user
     * * `team` - team */
    scope: AchievementDefinitionScopeEnumApi
    /** True for the streak track, whose thresholds vary by the streak-cadence experiment arm. */
    is_experiment_track: boolean
    /** The five stages of this track, in ascending threshold order. */
    stages: AchievementStageApi[]
}

/**
 * Map of unlocked stage number (as a string, '1'-'5') to the ISO timestamp it was unlocked.
 */
export type AchievementProgressApiUnlockedAt = { [key: string]: string }

export interface AchievementProgressApi {
    /** Track this progress row belongs to. */
    track_key: string
    /** Highest stage unlocked so far, 0-5. */
    current_stage: number
    /** Most recently computed progress value for the track. */
    progress_value: number
    /**
     * When the track was last recomputed, or null if it never has been.
     * @nullable
     */
    last_computed_at: string | null
    /** Map of unlocked stage number (as a string, '1'-'5') to the ISO timestamp it was unlocked. */
    unlocked_at: AchievementProgressApiUnlockedAt
}

export interface PendingCelebrationApi {
    /** Track whose stage was newly unlocked. */
    track_key: string
    /** Newly unlocked stage number, 1-5. */
    stage: number
    /** Name of the unlocked stage, shown in the celebration UI. */
    stage_name: string
}

export interface AchievementsListResponseApi {
    /** All Wave-1 track definitions, thresholds resolved for the user's streak arm. */
    definitions: AchievementDefinitionApi[]
    /** The requesting user's progress on per-user tracks. */
    user_progress: AchievementProgressApi[]
    /** The team's progress on per-team tracks. */
    team_progress: AchievementProgressApi[]
    /** Newly unlocked stages awaiting an in-session celebration; acknowledge each to clear it. */
    pending_celebrations: PendingCelebrationApi[]
}

export interface WebAnalyticsUserPreferencesApi {
    /** When true, the requesting user has hidden the Web analytics achievements gamification UI and suppressed achievement-unlocked notifications for this project. Scoped per (project, user). */
    achievements_opt_out: boolean
}

/**
 * * `data` - data
 * * `recording` - recording
 */
export type InteractionKindEnumApi = (typeof InteractionKindEnumApi)[keyof typeof InteractionKindEnumApi]

export const InteractionKindEnumApi = {
    Data: 'data',
    Recording: 'recording',
} as const

export interface RecordInteractionRequestApi {
    /** Which interaction counter to increment: 'data' (slicing/filtering the dashboard) or 'recording' (opening a session recording).
     *
     * * `data` - data
     * * `recording` - recording */
    interaction_kind: InteractionKindEnumApi
}

export interface RecordInteractionResponseApi {
    /** True once the interaction has been counted for the user. */
    recorded: boolean
}

export interface RecordVisitResponseApi {
    /** True once today's visit row exists for the user. */
    recorded: boolean
}

export interface ContentAutopilotSiteProfileApi {
    readonly id: string
    /**
     * Name used to identify this site in the workspace.
     * @maxLength 255
     */
    name?: string
    /**
     * Authorized site origin for this profile.
     * @maxLength 2048
     */
    domain: string
    /** Public sitemap and factual source URLs used to build the site profile. */
    source_urls: string[]
    /** Same-origin URL path prefixes allowed for research. */
    content_boundaries: string[]
    /** Brand, terminology, and editorial rules applied to every proposal. */
    brand_rules: string[]
    /** Whether to use connected Google Search Console data. */
    search_console_enabled?: boolean
    readonly created_at: string
    readonly updated_at: string
}

export interface PaginatedContentAutopilotSiteProfileListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: ContentAutopilotSiteProfileApi[]
}

export interface PatchedContentAutopilotSiteProfileApi {
    readonly id?: string
    /**
     * Name used to identify this site in the workspace.
     * @maxLength 255
     */
    name?: string
    /**
     * Authorized site origin for this profile.
     * @maxLength 2048
     */
    domain?: string
    /** Public sitemap and factual source URLs used to build the site profile. */
    source_urls?: string[]
    /** Same-origin URL path prefixes allowed for research. */
    content_boundaries?: string[]
    /** Brand, terminology, and editorial rules applied to every proposal. */
    brand_rules?: string[]
    /** Whether to use connected Google Search Console data. */
    search_console_enabled?: boolean
    readonly created_at?: string
    readonly updated_at?: string
}

export interface ContentAutopilotSiteDiscoveryRequestApi {
    /** Public site URL to inspect for onboarding defaults. */
    domain: string
}

export interface ContentAutopilotSiteDiscoveryResponseApi {
    /** Site name inferred from the homepage or hostname. */
    name: string
    /** Normalized site origin. */
    domain: string
    /** Detected sitemap URLs or an editable conventional suggestion. */
    source_urls: string[]
    /** Editable same-origin path boundaries. */
    content_boundaries: string[]
    /** Whether at least one sitemap was verified. */
    sitemap_detected: boolean
    /** Non-blocking discovery warnings. */
    warnings: string[]
}

/**
 * * `new_content` - New content
 * * `page_improvement` - Page improvement
 */
export type ContentAutopilotProposalProposalTypeEnumApi =
    (typeof ContentAutopilotProposalProposalTypeEnumApi)[keyof typeof ContentAutopilotProposalProposalTypeEnumApi]

export const ContentAutopilotProposalProposalTypeEnumApi = {
    NewContent: 'new_content',
    PageImprovement: 'page_improvement',
} as const

/**
 * * `generating` - Generating
 * * `ready_for_review` - Ready for review
 * * `rejected` - Rejected
 * * `exported` - Exported
 * * `failed` - Failed
 */
export type ContentAutopilotProposalLifecycleStatusEnumApi =
    (typeof ContentAutopilotProposalLifecycleStatusEnumApi)[keyof typeof ContentAutopilotProposalLifecycleStatusEnumApi]

export const ContentAutopilotProposalLifecycleStatusEnumApi = {
    Generating: 'generating',
    ReadyForReview: 'ready_for_review',
    Rejected: 'rejected',
    Exported: 'exported',
    Failed: 'failed',
} as const

/**
 * * `poor_ctr` - Poor click-through rate
 * * `content_gap` - Content gap
 * * `organic_decline` - Organic decline
 * * `ai_visibility_gap` - AI visibility gap
 * * `site_hygiene` - Site hygiene
 */
export type OpportunityKindEnumApi = (typeof OpportunityKindEnumApi)[keyof typeof OpportunityKindEnumApi]

export const OpportunityKindEnumApi = {
    PoorCtr: 'poor_ctr',
    ContentGap: 'content_gap',
    OrganicDecline: 'organic_decline',
    AiVisibilityGap: 'ai_visibility_gap',
    SiteHygiene: 'site_hygiene',
} as const

export interface ContentAutopilotEvidenceApi {
    /** Reason the opportunity was selected.
     *
     * * `poor_ctr` - Poor click-through rate
     * * `content_gap` - Content gap
     * * `organic_decline` - Organic decline
     * * `ai_visibility_gap` - AI visibility gap
     * * `site_hygiene` - Site hygiene */
    opportunity_kind: OpportunityKindEnumApi
    /** Plain-language explanation of the supporting evidence. */
    explanation: string
    /** Page supported by this evidence. */
    page_url?: string
    /** Search query supported by this evidence. */
    query?: string
}

export interface ContentAutopilotValidationCheckApi {
    /** Stable identifier for the validation gate. */
    check_key: string
    /** Human-readable validation name. */
    label: string
    /** Whether the proposal passed this validation. */
    passed: boolean
    /** Validation result and any action needed. */
    message: string
    /** Whether failure prevents export. */
    blocking: boolean
}

export interface ContentAutopilotValidationReportApi {
    /** Whether every blocking validation passed. */
    passed: boolean
    /** Factual, brand, intent, originality, linking, crawlability, and schema checks. */
    checks: ContentAutopilotValidationCheckApi[]
}

export interface ContentAutopilotProposalListApi {
    readonly id: string
    readonly run_id: string
    readonly proposal_type: ContentAutopilotProposalProposalTypeEnumApi
    readonly lifecycle_status: ContentAutopilotProposalLifecycleStatusEnumApi
    readonly title: string
    readonly target_query: string
    /** Performance evidence for this proposal. */
    evidence: ContentAutopilotEvidenceApi[]
    /** Blocking and advisory validation results. */
    validation_report: ContentAutopilotValidationReportApi
    /** Repository-relative export path. */
    readonly file_path: string
    readonly created_at: string
    readonly updated_at: string
}

export interface PaginatedContentAutopilotProposalListListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: ContentAutopilotProposalListApi[]
}

export interface ContentAutopilotFrontmatterEntryApi {
    /** Frontmatter field name. */
    key: string
    /** Serialized frontmatter value. */
    value: string
}

export interface ContentAutopilotPackageApi {
    /** Repository-relative Markdown or MDX file path. */
    file_path: string
    /** Content title. */
    title: string
    /** Search description or summary. */
    description: string
    /** URL slug. */
    slug: string
    /** Ordered frontmatter entries. */
    frontmatter: ContentAutopilotFrontmatterEntryApi[]
    /** Validated same-origin internal links included in the content. */
    internal_links: string[]
    /** Portable source notes included with the export. */
    source_notes: string[]
}

export interface ContentAutopilotProposalApi {
    readonly id: string
    /** Run that generated this proposal. */
    readonly run_id: string
    /** New article or bounded page improvement.
     *
     * * `new_content` - New content
     * * `page_improvement` - Page improvement */
    readonly proposal_type: ContentAutopilotProposalProposalTypeEnumApi
    /** Review and export lifecycle status.
     *
     * * `generating` - Generating
     * * `ready_for_review` - Ready for review
     * * `rejected` - Rejected
     * * `exported` - Exported
     * * `failed` - Failed */
    readonly lifecycle_status: ContentAutopilotProposalLifecycleStatusEnumApi
    /** Review title for this proposal. */
    readonly title: string
    /** Primary query or topic targeted by this proposal. */
    readonly target_query: string
    /** Existing or intended public URL. */
    readonly target_url: string
    /** Performance evidence for this proposal. */
    evidence: ContentAutopilotEvidenceApi[]
    /** Blocking and advisory validation results. */
    validation_report: ContentAutopilotValidationReportApi
    /** Structured package that accompanies the exported Markdown. */
    content_package: ContentAutopilotPackageApi
    /** Existing content for page-improvement diffs. */
    readonly original_markdown: string
    /** Full proposed Markdown after edits. */
    readonly proposed_markdown: string
    readonly created_at: string
    readonly updated_at: string
}

export interface ContentAutopilotProposalEditRequestApi {
    /**
     * Edited Markdown to save for review.
     * @maxLength 500000
     */
    proposed_markdown: string
    /** Updated structured package to save with the proposal. */
    content_package: ContentAutopilotPackageApi
}

export interface ContentAutopilotExportResponseApi {
    /** Suggested export filename. */
    filename: string
    /** Validated Markdown content. */
    markdown: string
    /** Structured JSON package for a CMS adapter. */
    content_package: ContentAutopilotPackageApi
}

/**
 * * `pending` - Pending
 * * `generating` - Generating
 * * `ready_for_review` - Ready for review
 * * `completed` - Completed
 * * `canceled` - Canceled
 * * `failed` - Failed
 */
export type ContentAutopilotRunRunStatusEnumApi =
    (typeof ContentAutopilotRunRunStatusEnumApi)[keyof typeof ContentAutopilotRunRunStatusEnumApi]

export const ContentAutopilotRunRunStatusEnumApi = {
    Pending: 'pending',
    Generating: 'generating',
    ReadyForReview: 'ready_for_review',
    Completed: 'completed',
    Canceled: 'canceled',
    Failed: 'failed',
} as const

/**
 * * `standard` - Standard
 * * `lower` - Lower
 */
export type ContentAutopilotSnapshotConfidenceEnumApi =
    (typeof ContentAutopilotSnapshotConfidenceEnumApi)[keyof typeof ContentAutopilotSnapshotConfidenceEnumApi]

export const ContentAutopilotSnapshotConfidenceEnumApi = {
    Standard: 'standard',
    Lower: 'lower',
} as const

export interface ContentAutopilotSnapshotApi {
    /** Site domain used for the run. */
    domain?: string
    /** Confidence level based on the available data sources.
     *
     * * `standard` - Standard
     * * `lower` - Lower */
    confidence?: ContentAutopilotSnapshotConfidenceEnumApi
    /** Public sources authorized for this run. */
    source_urls?: string[]
    /** Site paths authorized for this run. */
    content_boundaries?: string[]
    /** Editorial rules captured for this run. */
    brand_rules?: string[]
}

export interface ContentAutopilotErrorApi {
    /** Stable machine-readable error code. */
    error_code: string
    /** Error explanation suitable for the review workspace. */
    message: string
}

export interface ContentAutopilotRunApi {
    readonly id: string
    /** Site profile used by this run. */
    readonly profile_id: string
    /** Current durable workflow status.
     *
     * * `pending` - Pending
     * * `generating` - Generating
     * * `ready_for_review` - Ready for review
     * * `completed` - Completed
     * * `canceled` - Canceled
     * * `failed` - Failed */
    readonly run_status: ContentAutopilotRunRunStatusEnumApi
    /** Immutable inputs captured at run start. */
    input_snapshot: ContentAutopilotSnapshotApi
    /** Inspectable workflow errors from this run. */
    errors: ContentAutopilotErrorApi[]
    readonly created_at: string
    readonly updated_at: string
    /** @nullable */
    readonly completed_at: string | null
}

export interface PaginatedContentAutopilotRunListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: ContentAutopilotRunApi[]
}

export interface ContentAutopilotRunStartRequestApi {
    /** Site profile to research. */
    profile_id: string
}

export interface WebAnalyticsFilterPresetApi {
    readonly id: string
    readonly short_id: string
    /** @maxLength 400 */
    name: string
    description?: string
    pinned?: boolean
    readonly created_at: string
    readonly created_by: UserBasicApi
    deleted?: boolean
    filters?: unknown
    readonly last_modified_at: string
    readonly last_modified_by: UserBasicApi
}

export interface PaginatedWebAnalyticsFilterPresetListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: WebAnalyticsFilterPresetApi[]
}

export interface PatchedWebAnalyticsFilterPresetApi {
    readonly id?: string
    readonly short_id?: string
    /** @maxLength 400 */
    name?: string
    description?: string
    pinned?: boolean
    readonly created_at?: string
    readonly created_by?: UserBasicApi
    deleted?: boolean
    filters?: unknown
    readonly last_modified_at?: string
    readonly last_modified_by?: UserBasicApi
}

export interface ApplyPathCleaningSuggestionResponseApi {
    /** Number of rules merged into the team's path_cleaning_filters. */
    applied: number
}

export interface PathCleaningPreviewExampleApi {
    /** A real sampled path before the suggested rules are applied. */
    before: string
    /** The same path after all suggested rules run in order. */
    after: string
    /** Pageviews this path received in the sampling window. */
    views: number
}

export interface PreviewPathCleaningSuggestionResponseApi {
    /** Up to 20 before/after pairs for sampled paths the suggested rules would rewrite. */
    examples: PathCleaningPreviewExampleApi[]
    /** How many of the sampled paths the suggested rules rewrite in total. */
    changed_path_count: number
    /** How many top paths were sampled for this preview. */
    sampled_path_count: number
}

export interface SuggestedRuleApi {
    /** re2 pattern matching the dynamic path segment. */
    regex: string
    /** Replacement with angle-bracket placeholders, e.g. /users/<id>. */
    alias: string
    /** Apply order; rules run sequentially, output feeds the next. */
    order: number
    /** How many of the sampled paths this rule rewrites — evidence the rule was validated on real traffic. */
    match_count: number
}

/**
 * A path-cleaning suggestion, stored as a `path_cleaning_suggestions` health issue.
 */
export interface PathCleaningSuggestionIssueApi {
    /** Health-issue id; pass it to the apply endpoint or the health-issues API. */
    id: string
    /** When the suggestion was generated (ISO 8601). */
    created_at: string
    /** Validated path-cleaning rules proposed for this team, most specific first. */
    rules: SuggestedRuleApi[]
    /** LLM that generated the rules. */
    model: string
    /** How many real paths were sampled for generation. */
    sampled_path_count: number
    /** Distinct pathnames seen in the sampling window. */
    distinct_path_count: number
}

export interface GeneratePathCleaningSuggestionResponseApi {
    /** generated, skipped_low_cardinality, skipped_no_paths, skipped_configured, or error. */
    status: string
    /** The stored suggestion when status is generated, else null. */
    suggestion?: PathCleaningSuggestionIssueApi | null
}

export type HeatmapScreenshotsContentRetrieveParams = {
    /**
     * Viewport width (CSS pixels) to fetch. Defaults to 1024. If no exact render exists for this width the closest available one is returned.
     */
    width?: number
}

export type HeatmapsListParams = {
    /**
     * How to aggregate counts: 'total_count' (every interaction, default) or 'unique_visitors' (distinct people).
     *
     * * `unique_visitors` - unique_visitors
     * * `total_count` - total_count
     * @minLength 1
     */
    aggregation?: HeatmapsListAggregation
    /**
     * JSON array of cohort IDs (e.g. '[123, 456]') to restrict results to people in those cohorts. Feature-flagged; ignored when the cohort filter is not enabled for the caller.
     * @nullable
     */
    cohort_ids?: string | null
    /**
     * Start of the window. Relative (e.g. '-7d', '-30d', '-1mStart') or an absolute 'YYYY-MM-DD' date. Defaults to '-7d'. Heatmap data is retained for 90 days.
     * @minLength 1
     */
    date_from?: string
    /**
     * End of the window, inclusive. Relative or absolute 'YYYY-MM-DD'. Defaults to today.
     * @minLength 1
     */
    date_to?: string
    /**
     * JSON array of event filters (e.g. '[{"id": "purchase", "properties": []}]') to restrict results to sessions in which those events occurred. Each entry needs a string 'id' (the event name) and may carry a 'properties' array of property filters applied to that event, each of type 'event' or 'element'. Several entries are combined with AND: the session must contain a matching event for every entry. At most 10 entries, each with at most 20 property filters. Requires project-wide heatmap access, since the filter reads the project's events rather than one saved heatmap. Feature-flagged; ignored when the event filter is not enabled for the caller.
     * @nullable
     */
    events?: string | null
    /**
     * When true, exclude sessions from internal/test accounts using the project's test-account filters.
     * @nullable
     */
    filter_test_accounts?: boolean | null
    /**
     * When true (default), drop interactions recorded at the (0, 0) origin, which are usually noise.
     */
    hide_zero_coordinates?: boolean
    /**
     * Maximum number of coordinate points to return, ordered hottest-first by count. Defaults to 500. Pass 0 to fetch the full set (every coordinate) needed to render a complete heatmap overlay. Ignored for the 'scrolldepth' type, which always returns every bucket.
     * @minimum 0
     * @maximum 1000000
     */
    limit?: number
    /**
     * Number of hottest-first points to skip, for paging through cooler coordinates. Ignored for the 'scrolldepth' type.
     * @minimum 0
     * @maximum 1000000
     */
    offset?: number
    /**
     * The interaction type to return. One of: 'click' (default), 'rageclick', 'mousemove', or 'scrolldepth'. Scrolldepth returns scroll buckets instead of x/y coordinates.
     * @minLength 1
     */
    type?: string
    /**
     * Match a single page by exact URL (trailing slash is ignored). Mutually exclusive with url_pattern.
     * @minLength 1
     */
    url_exact?: string
    /**
     * Match pages by regex against the full current_url (anchored automatically). Use this to aggregate across query strings or path segments. Mutually exclusive with url_exact.
     * @minLength 1
     */
    url_pattern?: string
    /**
     * Only include interactions captured at a viewport at most this wide, in CSS pixels.
     */
    viewport_width_max?: number
    /**
     * Only include interactions captured at a viewport at least this wide, in CSS pixels. Use with viewport_width_max to isolate a device class (e.g. 360-768 for mobile).
     */
    viewport_width_min?: number
}

export type HeatmapsListAggregation = (typeof HeatmapsListAggregation)[keyof typeof HeatmapsListAggregation]

export const HeatmapsListAggregation = {
    UniqueVisitors: 'unique_visitors',
    TotalCount: 'total_count',
} as const

export type HeatmapsEventsRetrieveParams = {
    /**
     * How to aggregate counts: 'total_count' (every interaction, default) or 'unique_visitors' (distinct people).
     *
     * * `unique_visitors` - unique_visitors
     * * `total_count` - total_count
     * @minLength 1
     */
    aggregation?: HeatmapsEventsRetrieveAggregation
    /**
     * JSON array of cohort IDs (e.g. '[123, 456]') to restrict results to people in those cohorts. Feature-flagged; ignored when the cohort filter is not enabled for the caller.
     * @nullable
     */
    cohort_ids?: string | null
    /**
     * Start of the window. Relative (e.g. '-7d', '-30d', '-1mStart') or an absolute 'YYYY-MM-DD' date. Defaults to '-7d'. Heatmap data is retained for 90 days.
     * @minLength 1
     */
    date_from?: string
    /**
     * End of the window, inclusive. Relative or absolute 'YYYY-MM-DD'. Defaults to today.
     * @minLength 1
     */
    date_to?: string
    /**
     * JSON array of event filters (e.g. '[{"id": "purchase", "properties": []}]') to restrict results to sessions in which those events occurred. Each entry needs a string 'id' (the event name) and may carry a 'properties' array of property filters applied to that event, each of type 'event' or 'element'. Several entries are combined with AND: the session must contain a matching event for every entry. At most 10 entries, each with at most 20 property filters. Requires project-wide heatmap access, since the filter reads the project's events rather than one saved heatmap. Feature-flagged; ignored when the event filter is not enabled for the caller.
     * @nullable
     */
    events?: string | null
    /**
     * When true, exclude sessions from internal/test accounts using the project's test-account filters.
     * @nullable
     */
    filter_test_accounts?: boolean | null
    /**
     * When true (default), drop interactions recorded at the (0, 0) origin, which are usually noise.
     */
    hide_zero_coordinates?: boolean
    /**
     * Maximum interactions to return (1-100).
     * @minimum 1
     * @maximum 100
     */
    limit?: number
    /**
     * Number of interactions to skip, for pagination.
     * @minimum 0
     */
    offset?: number
    /**
     * JSON array of the heatmap coordinates to drill into, e.g. '[{"x": 0.5, "y": 100}]'. Each point needs 'x' (relative x, 0..1) and 'y' (absolute client-y pixels) matching values returned by the heatmaps list endpoint; an optional 'target_fixed' boolean matches fixed-position elements. Returns the individual session interactions behind those spots.
     * @minLength 1
     */
    points: string
    /**
     * The interaction type to return. One of: 'click' (default), 'rageclick', 'mousemove', or 'scrolldepth'. Scrolldepth returns scroll buckets instead of x/y coordinates.
     * @minLength 1
     */
    type?: string
    /**
     * Match a single page by exact URL (trailing slash is ignored). Mutually exclusive with url_pattern.
     * @minLength 1
     */
    url_exact?: string
    /**
     * Match pages by regex against the full current_url (anchored automatically). Use this to aggregate across query strings or path segments. Mutually exclusive with url_exact.
     * @minLength 1
     */
    url_pattern?: string
    /**
     * Only include interactions captured at a viewport at most this wide, in CSS pixels.
     */
    viewport_width_max?: number
    /**
     * Only include interactions captured at a viewport at least this wide, in CSS pixels. Use with viewport_width_max to isolate a device class (e.g. 360-768 for mobile).
     */
    viewport_width_min?: number
}

export type HeatmapsEventsRetrieveAggregation =
    (typeof HeatmapsEventsRetrieveAggregation)[keyof typeof HeatmapsEventsRetrieveAggregation]

export const HeatmapsEventsRetrieveAggregation = {
    UniqueVisitors: 'unique_visitors',
    TotalCount: 'total_count',
} as const

export type SavedListParams = {
    /**
     * Filter by the creating user's ID.
     */
    created_by?: number
    /**
     * Maximum saved heatmaps to return.
     */
    limit?: number
    /**
     * Number to skip, for pagination.
     */
    offset?: number
    /**
     * Field to order by, e.g. '-updated_at' (default) or 'created_at'.
     * @minLength 1
     */
    order?: string
    /**
     * Case-insensitive substring match on URL or name.
     * @minLength 1
     */
    search?: string
    /**
     * Filter by generation status: 'processing', 'completed', or 'failed'.
     * @minLength 1
     */
    status?: string
    /**
     * Filter by render mode: 'screenshot', 'iframe', or 'recording'.
     * @minLength 1
     */
    type?: string
}

export type WebAnalyticsRecapParams = {
    /**
     * When true (default), include period-over-period change for each metric comparing against the prior equal-length period. Set to false to skip the comparison query.
     */
    compare?: boolean
    /**
     * Lookback window in days (1–90). Defaults to 7.
     */
    days?: number
}

export type WebAnalyticsWeeklyDigestParams = {
    /**
     * When true (default), include period-over-period change for each metric comparing against the prior equal-length period. Set to false to skip the comparison query (faster).
     */
    compare?: boolean
    /**
     * Lookback window in days (1–90). Defaults to 7.
     */
    days?: number
}

export type WebAnalyticsContentAutopilotProfilesListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type WebAnalyticsContentAutopilotProposalsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    /**
     * Only return proposals for this site profile.
     */
    profile_id?: string
    /**
     * Only return proposals from this content run.
     */
    run_id?: string
}

export type WebAnalyticsContentAutopilotRunsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    /**
     * Only return runs for this site profile.
     */
    profile_id?: string
}

export type WebAnalyticsFilterPresetsListParams = {
    created_by?: number
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    short_id?: string
}
