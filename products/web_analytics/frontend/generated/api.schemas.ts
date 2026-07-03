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
export type HeatmapTypeApi = (typeof HeatmapTypeApi)[keyof typeof HeatmapTypeApi]

export const HeatmapTypeApi = {
    Screenshot: 'screenshot',
    Iframe: 'iframe',
    Recording: 'recording',
} as const

/**
 * * `processing` - Processing
 * * `completed` - Completed
 * * `failed` - Failed
 */
export type HeatmapScreenshotResponseStatusEnumApi =
    (typeof HeatmapScreenshotResponseStatusEnumApi)[keyof typeof HeatmapScreenshotResponseStatusEnumApi]

export const HeatmapScreenshotResponseStatusEnumApi = {
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
    /**
     * URL whose heatmap data is overlaid on the screenshot (defaults to 'url').
     * @maxLength 2000
     * @nullable
     */
    data_url?: string | null
    /** Viewport widths (CSS pixels) the screenshot is rendered at. */
    target_widths?: unknown
    /** Render mode: 'screenshot', 'iframe', or 'recording'.
     *
     * * `screenshot` - Screenshot
     * * `iframe` - Iframe
     * * `recording` - Recording */
    type?: HeatmapTypeApi
    /** Screenshot generation status: 'processing', 'completed', or 'failed'.
     *
     * * `processing` - Processing
     * * `completed` - Completed
     * * `failed` - Failed */
    readonly status: HeatmapScreenshotResponseStatusEnumApi
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
    /**
     * URL whose heatmap data is overlaid on the screenshot. Defaults to 'url' when omitted.
     * @maxLength 2000
     * @nullable
     */
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
    type?: HeatmapTypeApi
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
    /**
     * URL whose heatmap data is overlaid on the screenshot. Defaults to 'url' when omitted.
     * @maxLength 2000
     * @nullable
     */
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
    type?: HeatmapTypeApi
    /** Set true to soft-delete the saved heatmap. */
    deleted?: boolean
    /** When true, ask the headless browser to dismiss cookie/consent banners before capturing the screenshot. Off by default: the blocker can stall the render on some sites and time out. Only applies to 'screenshot' heatmaps. */
    block_consent_modals?: boolean
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
