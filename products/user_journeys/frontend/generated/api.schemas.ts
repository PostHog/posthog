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
 * Marks the step as a pageview of a matching URL.
 */
export type PageviewStepApiType = (typeof PageviewStepApiType)[keyof typeof PageviewStepApiType]

export const PageviewStepApiType = {
    Pageview: 'pageview',
} as const

/**
 * * `exact` - Exact
 * * `contains` - Contains
 * * `regex` - Regex
 */
export type UrlMatchingEnumApi = (typeof UrlMatchingEnumApi)[keyof typeof UrlMatchingEnumApi]

export const UrlMatchingEnumApi = {
    Exact: 'exact',
    Contains: 'contains',
    Regex: 'regex',
} as const

export interface PageviewStepApi {
    /** Marks the step as a pageview of a matching URL. */
    type: PageviewStepApiType
    /**
     * URL, URL fragment or regular expression the page URL must match.
     * @maxLength 2048
     */
    url: string
    /** How `url` is compared with the page URL: `exact` matches the whole URL, `contains` matches a case-insensitive substring, and `regex` matches a regular expression.
     *
     * * `exact` - Exact
     * * `contains` - Contains
     * * `regex` - Regex */
    url_matching?: UrlMatchingEnumApi
}

/**
 * Marks the step as an autocaptured click on a matching element.
 */
export type ElementClickStepApiType = (typeof ElementClickStepApiType)[keyof typeof ElementClickStepApiType]

export const ElementClickStepApiType = {
    ElementClick: 'element_click',
} as const

export interface ElementClickStepApi {
    /** Marks the step as an autocaptured click on a matching element. */
    type: ElementClickStepApiType
    /**
     * CSS selector of the clicked element, for example `button.signup`.
     * @maxLength 1024
     */
    selector: string
    /**
     * Exact text of the clicked element. Leave out to match any text.
     * @maxLength 400
     * @nullable
     */
    text?: string | null
    /**
     * Exact link target of the clicked element. Leave out to match any link.
     * @maxLength 2048
     * @nullable
     */
    href?: string | null
    /**
     * URL of the page the click happens on. Leave out to match the click on any page.
     * @maxLength 2048
     * @nullable
     */
    url?: string | null
    /** How `url` is compared with the page URL: `exact` matches the whole URL, `contains` matches a case-insensitive substring, and `regex` matches a regular expression.
     *
     * * `exact` - Exact
     * * `contains` - Contains
     * * `regex` - Regex */
    url_matching?: UrlMatchingEnumApi
}

export type JourneyStepApi = PageviewStepApi | ElementClickStepApi

/**
 * * `pending` - Pending
 * * `running` - Running
 * * `passed` - Passed
 * * `failed` - Failed
 * * `errored` - Errored
 */
export type JourneyRunStatusEnumApi = (typeof JourneyRunStatusEnumApi)[keyof typeof JourneyRunStatusEnumApi]

export const JourneyRunStatusEnumApi = {
    Pending: 'pending',
    Running: 'running',
    Passed: 'passed',
    Failed: 'failed',
    Errored: 'errored',
} as const

export interface JourneyLatestRunApi {
    /** Unique identifier of the run. */
    readonly id: string
    /** Status of the run: `pending`, `running`, `passed`, `failed` or `errored`.
     *
     * * `pending` - Pending
     * * `running` - Running
     * * `passed` - Passed
     * * `failed` - Failed
     * * `errored` - Errored */
    status: JourneyRunStatusEnumApi
    /** When the run was created. */
    created_at: string
    /**
     * When the run ended. Null while it is pending or running.
     * @nullable
     */
    finished_at: string | null
    /**
     * Position of the first failed step, from 0. Null unless a step of the run failed.
     * @nullable
     */
    failed_step_index: number | null
}

/**
 * * `toolbar` - Toolbar
 * * `manual` - Manual
 */
export type JourneySourceEnumApi = (typeof JourneySourceEnumApi)[keyof typeof JourneySourceEnumApi]

export const JourneySourceEnumApi = {
    Toolbar: 'toolbar',
    Manual: 'manual',
} as const

export interface JourneyApi {
    /** Ordered steps a session must complete, from 2 to 20. Each step is a pageview or a click on an element. */
    steps: JourneyStepApi[]
    /** The journey's newest run, so a list can show whether the journey still works. Null if it never ran. */
    readonly latest_run: JourneyLatestRunApi | null
    /** Unique identifier of the journey. */
    id: string
    /** Project the journey belongs to. */
    team_id: number
    /** Display name for the journey. */
    name: string
    /** What the journey covers and why it matters. */
    description: string
    /** Minutes a session has to go from the first step to the last, from 1 to 1440. */
    conversion_window_minutes: number
    /** Where the journey was defined: `toolbar` for the toolbar, `manual` for the app or the API.
     *
     * * `toolbar` - Toolbar
     * * `manual` - Manual */
    source: JourneySourceEnumApi
    /**
     * ID of the user who created the journey, if known.
     * @nullable
     */
    created_by_id: number | null
    /** When the journey was created. */
    created_at: string
    /** When the journey was last changed. */
    updated_at: string
    /**
     * Full http or https URL where a journey run opens the browser. Leave it null to start at the first step, which then must be an exact pageview of a full URL. Its host must be one of the project's authorized URLs when a run starts.
     * @nullable
     */
    start_url?: string | null
}

export interface PaginatedJourneyListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: JourneyApi[]
}

export interface CreateJourneyInputApi {
    /**
     * Ordered steps a session must complete, from 2 to 20. Each step is a pageview or a click on an element.
     * @minItems 2
     * @maxItems 20
     */
    steps: JourneyStepApi[]
    /**
     * Display name for the journey.
     * @maxLength 255
     */
    name: string
    /** What the journey covers and why it matters. */
    description?: string
    /**
     * Minutes a session has to go from the first step to the last, from 1 to 1440.
     * @minimum 1
     * @maximum 1440
     */
    conversion_window_minutes?: number
    /** Where the journey was defined: `toolbar` for the toolbar, `manual` for the app or the API.
     *
     * * `toolbar` - Toolbar
     * * `manual` - Manual */
    source?: JourneySourceEnumApi
    /**
     * Full http or https URL where a journey run opens the browser. Leave it null to start at the first step, which then must be an exact pageview of a full URL. Its host must be one of the project's authorized URLs when a run starts.
     * @maxLength 2048
     * @nullable
     */
    start_url?: string | null
}

/**
 * * `manual` - Manual
 * * `deploy` - Deploy
 */
export type JourneyRunTriggerEnumApi = (typeof JourneyRunTriggerEnumApi)[keyof typeof JourneyRunTriggerEnumApi]

export const JourneyRunTriggerEnumApi = {
    Manual: 'manual',
    Deploy: 'deploy',
} as const

/**
 * * `element_not_found` - Element not found
 * * `element_not_visible` - Element not visible
 * * `element_obscured` - Element covered by another element
 * * `element_outside_viewport_unreachable` - Element outside the viewport and can't be scrolled to
 * * `navigation_mismatch` - Page URL doesn't match
 * * `navigation_failed` - Page failed to load
 * * `navigation_blocked` - Navigation to a URL that isn't allowed
 * * `timeout` - Timed out
 */
export type JourneyStepFailureReasonEnumApi =
    (typeof JourneyStepFailureReasonEnumApi)[keyof typeof JourneyStepFailureReasonEnumApi]

export const JourneyStepFailureReasonEnumApi = {
    ElementNotFound: 'element_not_found',
    ElementNotVisible: 'element_not_visible',
    ElementObscured: 'element_obscured',
    ElementOutsideViewportUnreachable: 'element_outside_viewport_unreachable',
    NavigationMismatch: 'navigation_mismatch',
    NavigationFailed: 'navigation_failed',
    NavigationBlocked: 'navigation_blocked',
    Timeout: 'timeout',
} as const

export interface JourneyRunApi {
    /** Unique identifier of the run. */
    id: string
    /** Project the run belongs to. */
    team_id: number
    /** Journey the run replayed. */
    journey_id: string
    /** What started the run: `manual` for a person, `deploy` for a deployment.
     *
     * * `manual` - Manual
     * * `deploy` - Deploy */
    trigger: JourneyRunTriggerEnumApi
    /** `pending` until a worker picks the run up, then `running`. It ends as `passed` when every step passed, `failed` when a step failed, or `errored` when the run couldn't finish, for example because no browser was available.
     *
     * * `pending` - Pending
     * * `running` - Running
     * * `passed` - Passed
     * * `failed` - Failed
     * * `errored` - Errored */
    status: JourneyRunStatusEnumApi
    /**
     * URL the browser opened first, after `base_url` replaced its origin. Null until the run starts.
     * @nullable
     */
    start_url: string | null
    /**
     * Origin that replaced the journey's recorded origin, so the same paths ran against another deployment, for example a preview. Null when the run used the recorded origin.
     * @nullable
     */
    base_url: string | null
    /**
     * Commit of the deployment the run checked, when the trigger sent one.
     * @nullable
     */
    commit_sha: string | null
    /**
     * Branch of the deployment the run checked, when the trigger sent one.
     * @nullable
     */
    branch: string | null
    /** Browser viewport width in CSS pixels. */
    viewport_width: number
    /** Browser viewport height in CSS pixels. */
    viewport_height: number
    /**
     * Why an `errored` run couldn't finish. Null for every other status.
     * @nullable
     */
    error: string | null
    /**
     * The run this run's screenshots were compared with: the newest earlier passed run of the same journey at the same viewport. Null when there was none.
     * @nullable
     */
    baseline_run_id: string | null
    /**
     * ID of the user who started the run, if a user did.
     * @nullable
     */
    created_by_id: number | null
    /** When the run was created. */
    created_at: string
    /**
     * When a worker started the run.
     * @nullable
     */
    started_at: string | null
    /**
     * When the run ended.
     * @nullable
     */
    finished_at: string | null
    /**
     * The deploy that started the run. Null for a run a person started.
     * @nullable
     */
    deploy_id: string | null
    /**
     * Position of the first failed step, from 0. Null unless a step failed.
     * @nullable
     */
    failed_step_index: number | null
    /** Why the first failed step failed. Null unless a step failed.
     *
     * * `element_not_found` - Element not found
     * * `element_not_visible` - Element not visible
     * * `element_obscured` - Element covered by another element
     * * `element_outside_viewport_unreachable` - Element outside the viewport and can't be scrolled to
     * * `navigation_mismatch` - Page URL doesn't match
     * * `navigation_failed` - Page failed to load
     * * `navigation_blocked` - Navigation to a URL that isn't allowed
     * * `timeout` - Timed out */
    failure_reason: JourneyStepFailureReasonEnumApi | null
}

export interface PaginatedJourneyRunListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: JourneyRunApi[]
}

export interface CreateJourneyRunApi {
    /**
     * Run against another deployment of the same site, for example a preview. Only the origin (scheme, host and port) is used: it replaces the origin of every URL the journey opens and checks. Its host must be one of the project's authorized URLs.
     * @maxLength 2048
     * @nullable
     */
    base_url?: string | null
    /**
     * Commit of the deployment under test, kept on the run for reference.
     * @maxLength 64
     * @nullable
     */
    commit_sha?: string | null
    /**
     * Branch of the deployment under test, kept on the run for reference.
     * @maxLength 255
     * @nullable
     */
    branch?: string | null
    /**
     * Browser viewport width in CSS pixels, from 320 to 1920.
     * @minimum 320
     * @maximum 1920
     */
    viewport_width?: number
    /**
     * Browser viewport height in CSS pixels, from 320 to 1200.
     * @minimum 320
     * @maximum 1200
     */
    viewport_height?: number
}

/**
 * * `passed` - Passed
 * * `failed` - Failed
 * * `skipped` - Skipped
 */
export type JourneyRunStepStatusEnumApi = (typeof JourneyRunStepStatusEnumApi)[keyof typeof JourneyRunStepStatusEnumApi]

export const JourneyRunStepStatusEnumApi = {
    Passed: 'passed',
    Failed: 'failed',
    Skipped: 'skipped',
} as const

/**
 * * `unchanged` - Unchanged
 * * `changed` - Changed
 * * `new` - New
 */
export type JourneyVisualChangeEnumApi = (typeof JourneyVisualChangeEnumApi)[keyof typeof JourneyVisualChangeEnumApi]

export const JourneyVisualChangeEnumApi = {
    Unchanged: 'unchanged',
    Changed: 'changed',
    New: 'new',
} as const

export interface JourneyRunStepApi {
    /** The step as it was defined when the run started. */
    step: JourneyStepApi
    /** Position of the step in the journey, from 0. */
    index: number
    /** `passed` or `failed`, or `skipped` when an earlier step failed, because later steps can't run from the wrong page.
     *
     * * `passed` - Passed
     * * `failed` - Failed
     * * `skipped` - Skipped */
    status: JourneyRunStepStatusEnumApi
    /** Why a `failed` step failed. Null for other statuses.
     *
     * * `element_not_found` - Element not found
     * * `element_not_visible` - Element not visible
     * * `element_obscured` - Element covered by another element
     * * `element_outside_viewport_unreachable` - Element outside the viewport and can't be scrolled to
     * * `navigation_mismatch` - Page URL doesn't match
     * * `navigation_failed` - Page failed to load
     * * `navigation_blocked` - Navigation to a URL that isn't allowed
     * * `timeout` - Timed out */
    failure_reason: JourneyStepFailureReasonEnumApi | null
    /** What happened at the step, in words. Empty for a step that passed without notes. */
    message: string
    /**
     * Short-lived URL of the viewport screenshot. A click step is captured before the click, and a failed step is captured as the run found the page.
     * @nullable
     */
    screenshot_url: string | null
    /**
     * Short-lived URL of the same step's screenshot in the baseline run, if compared.
     * @nullable
     */
    baseline_screenshot_url: string | null
    /**
     * Short-lived URL of an image that marks the pixels that changed from the baseline.
     * @nullable
     */
    diff_screenshot_url: string | null
    /**
     * Percentage of pixels that changed from the baseline screenshot, from 0 to 100.
     * @nullable
     */
    diff_percentage: number | null
    /** `unchanged` or `changed` compared with the baseline, or `new` when the baseline has no screenshot of the same step. A visual change never fails a run.
     *
     * * `unchanged` - Unchanged
     * * `changed` - Changed
     * * `new` - New */
    visual_change: JourneyVisualChangeEnumApi | null
    /**
     * Milliseconds the step took. Null for a skipped step.
     * @nullable
     */
    duration_ms: number | null
}

export interface JourneyRunDetailApi {
    /** Every step of the run, in order. Empty until it ends. */
    steps: JourneyRunStepApi[]
    /** Unique identifier of the run. */
    id: string
    /** Project the run belongs to. */
    team_id: number
    /** Journey the run replayed. */
    journey_id: string
    /** What started the run: `manual` for a person, `deploy` for a deployment.
     *
     * * `manual` - Manual
     * * `deploy` - Deploy */
    trigger: JourneyRunTriggerEnumApi
    /** `pending` until a worker picks the run up, then `running`. It ends as `passed` when every step passed, `failed` when a step failed, or `errored` when the run couldn't finish, for example because no browser was available.
     *
     * * `pending` - Pending
     * * `running` - Running
     * * `passed` - Passed
     * * `failed` - Failed
     * * `errored` - Errored */
    status: JourneyRunStatusEnumApi
    /**
     * URL the browser opened first, after `base_url` replaced its origin. Null until the run starts.
     * @nullable
     */
    start_url: string | null
    /**
     * Origin that replaced the journey's recorded origin, so the same paths ran against another deployment, for example a preview. Null when the run used the recorded origin.
     * @nullable
     */
    base_url: string | null
    /**
     * Commit of the deployment the run checked, when the trigger sent one.
     * @nullable
     */
    commit_sha: string | null
    /**
     * Branch of the deployment the run checked, when the trigger sent one.
     * @nullable
     */
    branch: string | null
    /** Browser viewport width in CSS pixels. */
    viewport_width: number
    /** Browser viewport height in CSS pixels. */
    viewport_height: number
    /**
     * Why an `errored` run couldn't finish. Null for every other status.
     * @nullable
     */
    error: string | null
    /**
     * The run this run's screenshots were compared with: the newest earlier passed run of the same journey at the same viewport. Null when there was none.
     * @nullable
     */
    baseline_run_id: string | null
    /**
     * ID of the user who started the run, if a user did.
     * @nullable
     */
    created_by_id: number | null
    /** When the run was created. */
    created_at: string
    /**
     * When a worker started the run.
     * @nullable
     */
    started_at: string | null
    /**
     * When the run ended.
     * @nullable
     */
    finished_at: string | null
    /**
     * The deploy that started the run. Null for a run a person started.
     * @nullable
     */
    deploy_id: string | null
    /**
     * Position of the first failed step, from 0. Null unless a step failed.
     * @nullable
     */
    failed_step_index: number | null
    /** Why the first failed step failed. Null unless a step failed.
     *
     * * `element_not_found` - Element not found
     * * `element_not_visible` - Element not visible
     * * `element_obscured` - Element covered by another element
     * * `element_outside_viewport_unreachable` - Element outside the viewport and can't be scrolled to
     * * `navigation_mismatch` - Page URL doesn't match
     * * `navigation_failed` - Page failed to load
     * * `navigation_blocked` - Navigation to a URL that isn't allowed
     * * `timeout` - Timed out */
    failure_reason: JourneyStepFailureReasonEnumApi | null
}

export interface PatchedUpdateJourneyInputApi {
    /**
     * Ordered steps a session must complete, from 2 to 20. Each step is a pageview or a click on an element.
     * @minItems 2
     * @maxItems 20
     */
    steps?: JourneyStepApi[]
    /**
     * Display name for the journey.
     * @maxLength 255
     */
    name?: string
    /** What the journey covers and why it matters. */
    description?: string
    /**
     * Minutes a session has to go from the first step to the last, from 1 to 1440.
     * @minimum 1
     * @maximum 1440
     */
    conversion_window_minutes?: number
    /** Where the journey was defined: `toolbar` for the toolbar, `manual` for the app or the API.
     *
     * * `toolbar` - Toolbar
     * * `manual` - Manual */
    source?: JourneySourceEnumApi
    /**
     * Full http or https URL where a journey run opens the browser. Leave it null to start at the first step, which then must be an exact pageview of a full URL. Its host must be one of the project's authorized URLs when a run starts. Send an empty string to remove the stored start URL.
     * @maxLength 2048
     */
    start_url?: string
}

export type BreakdownTypeApi = (typeof BreakdownTypeApi)[keyof typeof BreakdownTypeApi]

export const BreakdownTypeApi = {
    Cohort: 'cohort',
    Person: 'person',
    Event: 'event',
    EventMetadata: 'event_metadata',
    Element: 'element',
    Group: 'group',
    Session: 'session',
    Hogql: 'hogql',
    DataWarehouse: 'data_warehouse',
    DataWarehousePersonProperty: 'data_warehouse_person_property',
    RevenueAnalytics: 'revenue_analytics',
} as const

export type MultipleBreakdownTypeApi = (typeof MultipleBreakdownTypeApi)[keyof typeof MultipleBreakdownTypeApi]

export const MultipleBreakdownTypeApi = {
    Person: 'person',
    Event: 'event',
    EventMetadata: 'event_metadata',
    Element: 'element',
    Group: 'group',
    Session: 'session',
    Hogql: 'hogql',
    Cohort: 'cohort',
    RevenueAnalytics: 'revenue_analytics',
    DataWarehouse: 'data_warehouse',
    DataWarehousePersonProperty: 'data_warehouse_person_property',
} as const

export interface BreakdownApi {
    group_type_index?: number | null
    histogram_bin_count?: number | null
    normalize_url?: boolean | null
    property: string | number
    type?: MultipleBreakdownTypeApi | null
}

export interface BreakdownFilterApi {
    breakdown?: string | (string | number)[] | number | null
    breakdown_group_type_index?: number | null
    breakdown_hide_other_aggregation?: boolean | null
    breakdown_histogram_bin_count?: number | null
    breakdown_limit?: number | null
    breakdown_normalize_url?: boolean | null
    breakdown_path_cleaning?: boolean | null
    breakdown_type?: BreakdownTypeApi | null
    breakdowns?: BreakdownApi[] | null
}

export interface CompareFilterApi {
    /** Whether to compare the current date range to a previous date range. */
    compare?: boolean | null
    /** The date range to compare to. The value is a relative date. Examples of relative dates are: `-1y` for 1 year ago, `-14m` for 14 months ago, `-100w` for 100 weeks ago, `-14d` for 14 days ago, `-30h` for 30 hours ago. */
    compare_to?: string | null
}

export type DaysOfWeekEnumApi = (typeof DaysOfWeekEnumApi)[keyof typeof DaysOfWeekEnumApi]

export const DaysOfWeekEnumApi = {
    Number1: 1,
    Number2: 2,
    Number3: 3,
    Number4: 4,
    Number5: 5,
    Number6: 6,
    Number7: 7,
} as const

export interface DateRangeApi {
    /** Start of the date range. Accepts ISO 8601 timestamps (e.g., 2024-01-15T00:00:00Z) or relative formats: -7d (7 days ago), -2w (2 weeks ago), -1m (1 month ago),
     * -1h (1 hour ago), -1mStart (start of last month), -1yStart (start of last year). */
    date_from?: string | null
    /** End of the date range. Same format as date_from. Omit or null for "now". A calendar day without a time (2024-01-15) is inclusive: it rounds to the last moment of that day in the project timezone, unless explicitDate is set. */
    date_to?: string | null
    /** Restrict the query to events occurring on these ISO days of week (1=Monday to 7=Sunday), evaluated in the project timezone. Omit or empty for all days. Only applied by insight queries. */
    daysOfWeek?: DaysOfWeekEnumApi[] | null
    /** Exclude the current, still-collecting period by clipping date_to to the end of the last complete interval (evaluated in the project timezone). No-op when the range contains no complete interval. Only applied by insight queries. */
    excludeIncompletePeriods?: boolean | null
    /** Whether the date_from and date_to should be used verbatim. Disables rounding to the start and end of period. */
    explicitDate?: boolean | null
}

export type AnnotationScopeApi = (typeof AnnotationScopeApi)[keyof typeof AnnotationScopeApi]

export const AnnotationScopeApi = {
    DashboardItem: 'dashboard_item',
    Dashboard: 'dashboard',
    Project: 'project',
    Organization: 'organization',
} as const

export type BreakdownAttributionTypeApi = (typeof BreakdownAttributionTypeApi)[keyof typeof BreakdownAttributionTypeApi]

export const BreakdownAttributionTypeApi = {
    FirstTouch: 'first_touch',
    LastTouch: 'last_touch',
    AllEvents: 'all_events',
    Step: 'step',
} as const

export type CurveApi = (typeof CurveApi)[keyof typeof CurveApi]

export const CurveApi = {
    Linear: 'linear',
    Smooth: 'smooth',
} as const

export type SeriesColorModeApi = (typeof SeriesColorModeApi)[keyof typeof SeriesColorModeApi]

export const SeriesColorModeApi = {
    Palette: 'palette',
    Opacity: 'opacity',
} as const

export interface ChartStyleApi {
    /** Line interpolation: straight segments or a smoothed curve through the points. */
    curve?: CurveApi | null
    /** How series are told apart: one color per series, or one color at stepped opacities. */
    seriesColorMode?: SeriesColorModeApi | null
}

export type PropertyOperatorApi = (typeof PropertyOperatorApi)[keyof typeof PropertyOperatorApi]

export const PropertyOperatorApi = {
    Exact: 'exact',
    IsNot: 'is_not',
    Icontains: 'icontains',
    NotIcontains: 'not_icontains',
    StartsWith: 'starts_with',
    NotStartsWith: 'not_starts_with',
    EndsWith: 'ends_with',
    NotEndsWith: 'not_ends_with',
    Regex: 'regex',
    NotRegex: 'not_regex',
    Gt: 'gt',
    Gte: 'gte',
    Lt: 'lt',
    Lte: 'lte',
    IsSet: 'is_set',
    IsNotSet: 'is_not_set',
    IsDateExact: 'is_date_exact',
    IsDateBefore: 'is_date_before',
    IsDateAfter: 'is_date_after',
    Between: 'between',
    NotBetween: 'not_between',
    Min: 'min',
    Max: 'max',
    In: 'in',
    NotIn: 'not_in',
    IsCleanedPathExact: 'is_cleaned_path_exact',
    IsCleanedPathNotExact: 'is_cleaned_path_not_exact',
    FlagEvaluatesTo: 'flag_evaluates_to',
    SemverEq: 'semver_eq',
    SemverNeq: 'semver_neq',
    SemverGt: 'semver_gt',
    SemverGte: 'semver_gte',
    SemverLt: 'semver_lt',
    SemverLte: 'semver_lte',
    SemverTilde: 'semver_tilde',
    SemverCaret: 'semver_caret',
    SemverWildcard: 'semver_wildcard',
    IcontainsMulti: 'icontains_multi',
    NotIcontainsMulti: 'not_icontains_multi',
} as const

export interface EventPropertyFilterApi {
    key: string
    label?: string | null
    operator?: PropertyOperatorApi | null
    /** Event properties */
    type?: 'event'
    value?: (string | number | boolean)[] | string | number | boolean | null
}

export interface PersonPropertyFilterApi {
    key: string
    label?: string | null
    operator: PropertyOperatorApi
    /** Person properties */
    type?: 'person'
    value?: (string | number | boolean)[] | string | number | boolean | null
}

export interface PersonMetadataPropertyFilterApi {
    key: string
    label?: string | null
    operator: PropertyOperatorApi
    /** Top-level columns on the persons table (e.g. created_at), not properties JSON */
    type?: 'person_metadata'
    value?: (string | number | boolean)[] | string | number | boolean | null
}

export type Key10Api = (typeof Key10Api)[keyof typeof Key10Api]

export const Key10Api = {
    TagName: 'tag_name',
    Text: 'text',
    Href: 'href',
    Selector: 'selector',
} as const

export interface ElementPropertyFilterApi {
    key: Key10Api
    label?: string | null
    operator: PropertyOperatorApi
    type?: 'element'
    value?: (string | number | boolean)[] | string | number | boolean | null
}

export interface EventMetadataPropertyFilterApi {
    key: string
    label?: string | null
    operator: PropertyOperatorApi
    type?: 'event_metadata'
    value?: (string | number | boolean)[] | string | number | boolean | null
}

export interface SessionPropertyFilterApi {
    key: string
    label?: string | null
    operator: PropertyOperatorApi
    type?: 'session'
    value?: (string | number | boolean)[] | string | number | boolean | null
}

export interface CohortPropertyFilterApi {
    /** Set by the feature flag API when the cohort is deleted or does not exist. */
    cohort_deleted?: boolean | null
    /** Set by the feature flag API when the cohort does not exist, so it cannot be restored. */
    cohort_missing?: boolean | null
    cohort_name?: string | null
    key?: 'id'
    label?: string | null
    operator?: PropertyOperatorApi | null
    type?: 'cohort'
    value: number
}

export type DurationTypeApi = (typeof DurationTypeApi)[keyof typeof DurationTypeApi]

export const DurationTypeApi = {
    Duration: 'duration',
    ActiveSeconds: 'active_seconds',
    InactiveSeconds: 'inactive_seconds',
} as const

export interface RecordingPropertyFilterApi {
    key: DurationTypeApi | string
    label?: string | null
    operator: PropertyOperatorApi
    type?: 'recording'
    value?: (string | number | boolean)[] | string | number | boolean | null
}

export interface LogEntryPropertyFilterApi {
    key: string
    label?: string | null
    operator: PropertyOperatorApi
    type?: 'log_entry'
    value?: (string | number | boolean)[] | string | number | boolean | null
}

export type GroupPropertyFilterApiGroupKeyNames = { [key: string]: string } | null

export interface GroupPropertyFilterApi {
    group_key_names?: GroupPropertyFilterApiGroupKeyNames
    group_type_index?: number | null
    key: string
    label?: string | null
    operator: PropertyOperatorApi
    type?: 'group'
    value?: (string | number | boolean)[] | string | number | boolean | null
}

export interface FeaturePropertyFilterApi {
    key: string
    label?: string | null
    operator: PropertyOperatorApi
    /** Event property with "$feature/" prepended */
    type?: 'feature'
    value?: (string | number | boolean)[] | string | number | boolean | null
}

export interface FlagPropertyFilterApi {
    /** The key should be the flag ID */
    key: string
    label?: string | null
    /** Only flag_evaluates_to operator is allowed for flag dependencies */
    operator?: 'flag_evaluates_to'
    /** Feature flag dependency */
    type?: 'flag'
    /** The value can be true, false, or a variant name */
    value: boolean | string
}

export interface HogQLPropertyFilterApi {
    key: string
    label?: string | null
    type?: 'hogql'
    value?: (string | number | boolean)[] | string | number | boolean | null
}

export const EmptyPropertyFilterApiValue = {
    type: 'empty',
} as const
export type EmptyPropertyFilterApi = typeof EmptyPropertyFilterApiValue

export interface DataWarehousePropertyFilterApi {
    key: string
    label?: string | null
    operator: PropertyOperatorApi
    type?: 'data_warehouse'
    value?: (string | number | boolean)[] | string | number | boolean | null
}

export interface DataWarehousePersonPropertyFilterApi {
    key: string
    label?: string | null
    operator: PropertyOperatorApi
    type?: 'data_warehouse_person_property'
    value?: (string | number | boolean)[] | string | number | boolean | null
}

export interface ErrorTrackingIssueFilterApi {
    key: string
    label?: string | null
    operator: PropertyOperatorApi
    type?: 'error_tracking_issue'
    value?: (string | number | boolean)[] | string | number | boolean | null
}

export type LogPropertyFilterTypeApi = (typeof LogPropertyFilterTypeApi)[keyof typeof LogPropertyFilterTypeApi]

export const LogPropertyFilterTypeApi = {
    Log: 'log',
    LogAttribute: 'log_attribute',
    LogResourceAttribute: 'log_resource_attribute',
} as const

export interface LogPropertyFilterApi {
    key: string
    label?: string | null
    operator: PropertyOperatorApi
    type: LogPropertyFilterTypeApi
    value?: (string | number | boolean)[] | string | number | boolean | null
}

export interface MetricPropertyFilterApi {
    key: string
    label?: string | null
    operator: PropertyOperatorApi
    type?: 'metric_attribute'
    value?: (string | number | boolean)[] | string | number | boolean | null
}

export type SpanPropertyFilterTypeApi = (typeof SpanPropertyFilterTypeApi)[keyof typeof SpanPropertyFilterTypeApi]

export const SpanPropertyFilterTypeApi = {
    Span: 'span',
    SpanAttribute: 'span_attribute',
    SpanResourceAttribute: 'span_resource_attribute',
} as const

export interface SpanPropertyFilterApi {
    key: string
    label?: string | null
    operator: PropertyOperatorApi
    type: SpanPropertyFilterTypeApi
    value?: (string | number | boolean)[] | string | number | boolean | null
}

export interface RevenueAnalyticsPropertyFilterApi {
    key: string
    label?: string | null
    operator: PropertyOperatorApi
    type?: 'revenue_analytics'
    value?: (string | number | boolean)[] | string | number | boolean | null
}

export interface AccountCustomPropertyFilterApi {
    key: string
    label?: string | null
    operator: PropertyOperatorApi
    /** Customer analytics account custom property — the key is the property definition id */
    type?: 'account_custom_property'
    value?: (string | number | boolean)[] | string | number | boolean | null
}

export interface WorkflowVariablePropertyFilterApi {
    key: string
    label?: string | null
    operator: PropertyOperatorApi
    type?: 'workflow_variable'
    value?: (string | number | boolean)[] | string | number | boolean | null
}

export type BehavioralEventSourceApi = (typeof BehavioralEventSourceApi)[keyof typeof BehavioralEventSourceApi]

export const BehavioralEventSourceApi = {
    Events: 'events',
    Actions: 'actions',
} as const

export type TimeUnitTypeApi = (typeof TimeUnitTypeApi)[keyof typeof TimeUnitTypeApi]

export const TimeUnitTypeApi = {
    Day: 'day',
    Week: 'week',
    Month: 'month',
    Year: 'year',
} as const

export type InlineBehavioralTypeApi = (typeof InlineBehavioralTypeApi)[keyof typeof InlineBehavioralTypeApi]

export const InlineBehavioralTypeApi = {
    PerformedEvent: 'performed_event',
    PerformedEventMultiple: 'performed_event_multiple',
} as const

export interface BehavioralPropertyFilterApi {
    /** Extra property filters the matching events must satisfy. Deliberately excludes nested behavioral/cohort filters and groups */
    event_filters?:
        | (
              | EventPropertyFilterApi
              | PersonPropertyFilterApi
              | ElementPropertyFilterApi
              | FeaturePropertyFilterApi
              | HogQLPropertyFilterApi
          )[]
        | null
    event_type: BehavioralEventSourceApi
    /** Absolute or relative (e.g. -30d) lower date bound — alternative to time_value/time_interval */
    explicit_datetime?: string | null
    explicit_datetime_to?: string | null
    /** Event name, or action id when event_type is 'actions' */
    key: string
    label?: string | null
    /** Match persons who did NOT satisfy the criterion. Not the same as a low count — zero-occurrence persons never match count operators */
    negation?: boolean | null
    /** Count comparison for performed_event_multiple, defaults to exact */
    operator?: PropertyOperatorApi | null
    /** Count threshold for performed_event_multiple */
    operator_value?: number | null
    time_interval?: TimeUnitTypeApi | null
    /** Relative time window size, paired with time_interval */
    time_value?: number | null
    /** Person performed (or didn't perform) an event in a time window. ClickHouse-only — not evaluable by flags or CDP */
    type?: 'behavioral'
    value: InlineBehavioralTypeApi
}

export type BaseMathTypeApi = (typeof BaseMathTypeApi)[keyof typeof BaseMathTypeApi]

export const BaseMathTypeApi = {
    Total: 'total',
    Dau: 'dau',
    WeeklyActive: 'weekly_active',
    MonthlyActive: 'monthly_active',
    UniqueSession: 'unique_session',
    FirstTimeForUser: 'first_time_for_user',
    FirstMatchingEventForUser: 'first_matching_event_for_user',
} as const

export type FunnelMathTypeApi = (typeof FunnelMathTypeApi)[keyof typeof FunnelMathTypeApi]

export const FunnelMathTypeApi = {
    Total: 'total',
    FirstTimeForUser: 'first_time_for_user',
    FirstTimeForUserWithFilters: 'first_time_for_user_with_filters',
} as const

export type PropertyMathTypeApi = (typeof PropertyMathTypeApi)[keyof typeof PropertyMathTypeApi]

export const PropertyMathTypeApi = {
    Avg: 'avg',
    Sum: 'sum',
    Min: 'min',
    Max: 'max',
    Median: 'median',
    P75: 'p75',
    P90: 'p90',
    P95: 'p95',
    P99: 'p99',
} as const

export type CountPerActorMathTypeApi = (typeof CountPerActorMathTypeApi)[keyof typeof CountPerActorMathTypeApi]

export const CountPerActorMathTypeApi = {
    AvgCountPerActor: 'avg_count_per_actor',
    MinCountPerActor: 'min_count_per_actor',
    MaxCountPerActor: 'max_count_per_actor',
    MedianCountPerActor: 'median_count_per_actor',
    P75CountPerActor: 'p75_count_per_actor',
    P90CountPerActor: 'p90_count_per_actor',
    P95CountPerActor: 'p95_count_per_actor',
    P99CountPerActor: 'p99_count_per_actor',
} as const

export type GroupMathTypeApi = (typeof GroupMathTypeApi)[keyof typeof GroupMathTypeApi]

export const GroupMathTypeApi = {
    UniqueGroup: 'unique_group',
    FirstTimeForGroup: 'first_time_for_group',
    FirstMatchingEventForGroup: 'first_matching_event_for_group',
} as const

export type ExperimentMetricMathTypeApi = (typeof ExperimentMetricMathTypeApi)[keyof typeof ExperimentMetricMathTypeApi]

export const ExperimentMetricMathTypeApi = {
    Total: 'total',
    Sum: 'sum',
    UniqueSession: 'unique_session',
    Min: 'min',
    Max: 'max',
    Avg: 'avg',
    Dau: 'dau',
    UniqueGroup: 'unique_group',
    Hogql: 'hogql',
} as const

export type CalendarHeatmapMathTypeApi = (typeof CalendarHeatmapMathTypeApi)[keyof typeof CalendarHeatmapMathTypeApi]

export const CalendarHeatmapMathTypeApi = {
    Total: 'total',
    Dau: 'dau',
} as const

export type MathGroupTypeIndexApi = (typeof MathGroupTypeIndexApi)[keyof typeof MathGroupTypeIndexApi]

export const MathGroupTypeIndexApi = {
    Number0: 0,
    Number1: 1,
    Number2: 2,
    Number3: 3,
    Number4: 4,
} as const

export type CurrencyCodeApi = (typeof CurrencyCodeApi)[keyof typeof CurrencyCodeApi]

export const CurrencyCodeApi = {
    Aed: 'AED',
    Afn: 'AFN',
    All: 'ALL',
    Amd: 'AMD',
    Ang: 'ANG',
    Aoa: 'AOA',
    Ars: 'ARS',
    Aud: 'AUD',
    Awg: 'AWG',
    Azn: 'AZN',
    Bam: 'BAM',
    Bbd: 'BBD',
    Bdt: 'BDT',
    Bgn: 'BGN',
    Bhd: 'BHD',
    Bif: 'BIF',
    Bmd: 'BMD',
    Bnd: 'BND',
    Bob: 'BOB',
    Brl: 'BRL',
    Bsd: 'BSD',
    Btc: 'BTC',
    Btn: 'BTN',
    Bwp: 'BWP',
    Byn: 'BYN',
    Bzd: 'BZD',
    Cad: 'CAD',
    Cdf: 'CDF',
    Chf: 'CHF',
    Clp: 'CLP',
    Cny: 'CNY',
    Cop: 'COP',
    Crc: 'CRC',
    Cve: 'CVE',
    Czk: 'CZK',
    Djf: 'DJF',
    Dkk: 'DKK',
    Dop: 'DOP',
    Dzd: 'DZD',
    Egp: 'EGP',
    Ern: 'ERN',
    Etb: 'ETB',
    Eur: 'EUR',
    Fjd: 'FJD',
    Gbp: 'GBP',
    Gel: 'GEL',
    Ghs: 'GHS',
    Gip: 'GIP',
    Gmd: 'GMD',
    Gnf: 'GNF',
    Gtq: 'GTQ',
    Gyd: 'GYD',
    Hkd: 'HKD',
    Hnl: 'HNL',
    Hrk: 'HRK',
    Htg: 'HTG',
    Huf: 'HUF',
    Idr: 'IDR',
    Ils: 'ILS',
    Inr: 'INR',
    Iqd: 'IQD',
    Irr: 'IRR',
    Isk: 'ISK',
    Jmd: 'JMD',
    Jod: 'JOD',
    Jpy: 'JPY',
    Kes: 'KES',
    Kgs: 'KGS',
    Khr: 'KHR',
    Kmf: 'KMF',
    Krw: 'KRW',
    Kwd: 'KWD',
    Kyd: 'KYD',
    Kzt: 'KZT',
    Lak: 'LAK',
    Lbp: 'LBP',
    Lkr: 'LKR',
    Lrd: 'LRD',
    Ltl: 'LTL',
    Lvl: 'LVL',
    Lsl: 'LSL',
    Lyd: 'LYD',
    Mad: 'MAD',
    Mdl: 'MDL',
    Mga: 'MGA',
    Mkd: 'MKD',
    Mmk: 'MMK',
    Mnt: 'MNT',
    Mop: 'MOP',
    Mru: 'MRU',
    Mtl: 'MTL',
    Mur: 'MUR',
    Mvr: 'MVR',
    Mwk: 'MWK',
    Mxn: 'MXN',
    Myr: 'MYR',
    Mzn: 'MZN',
    Nad: 'NAD',
    Ngn: 'NGN',
    Nio: 'NIO',
    Nok: 'NOK',
    Npr: 'NPR',
    Nzd: 'NZD',
    Omr: 'OMR',
    Pab: 'PAB',
    Pen: 'PEN',
    Pgk: 'PGK',
    Php: 'PHP',
    Pkr: 'PKR',
    Pln: 'PLN',
    Pyg: 'PYG',
    Qar: 'QAR',
    Ron: 'RON',
    Rsd: 'RSD',
    Rub: 'RUB',
    Rwf: 'RWF',
    Sar: 'SAR',
    Sbd: 'SBD',
    Scr: 'SCR',
    Sdg: 'SDG',
    Sek: 'SEK',
    Sgd: 'SGD',
    Srd: 'SRD',
    Ssp: 'SSP',
    Stn: 'STN',
    Syp: 'SYP',
    Szl: 'SZL',
    Thb: 'THB',
    Tjs: 'TJS',
    Tmt: 'TMT',
    Tnd: 'TND',
    Top: 'TOP',
    Try: 'TRY',
    Ttd: 'TTD',
    Twd: 'TWD',
    Tzs: 'TZS',
    Uah: 'UAH',
    Ugx: 'UGX',
    Usd: 'USD',
    Uyu: 'UYU',
    Uzs: 'UZS',
    Ves: 'VES',
    Vnd: 'VND',
    Vuv: 'VUV',
    Wst: 'WST',
    Xaf: 'XAF',
    Xcd: 'XCD',
    Xof: 'XOF',
    Xpf: 'XPF',
    Yer: 'YER',
    Zar: 'ZAR',
    Zmw: 'ZMW',
} as const

export interface RevenueCurrencyPropertyConfigApi {
    property?: string | null
    static?: CurrencyCodeApi | null
}

export type FunnelExclusionEventsNodeApiResponse = { [key: string]: unknown } | null

export interface FunnelExclusionEventsNodeApi {
    custom_name?: string | null
    /** The event or `null` for all events. */
    event?: string | null
    /** Fixed properties in the query, can't be edited in the interface (e.g. scoping down by person) */
    fixedProperties?:
        | (
              | EventPropertyFilterApi
              | PersonPropertyFilterApi
              | PersonMetadataPropertyFilterApi
              | ElementPropertyFilterApi
              | EventMetadataPropertyFilterApi
              | SessionPropertyFilterApi
              | CohortPropertyFilterApi
              | RecordingPropertyFilterApi
              | LogEntryPropertyFilterApi
              | GroupPropertyFilterApi
              | FeaturePropertyFilterApi
              | FlagPropertyFilterApi
              | HogQLPropertyFilterApi
              | EmptyPropertyFilterApi
              | DataWarehousePropertyFilterApi
              | DataWarehousePersonPropertyFilterApi
              | ErrorTrackingIssueFilterApi
              | LogPropertyFilterApi
              | MetricPropertyFilterApi
              | SpanPropertyFilterApi
              | RevenueAnalyticsPropertyFilterApi
              | AccountCustomPropertyFilterApi
              | WorkflowVariablePropertyFilterApi
              | BehavioralPropertyFilterApi
          )[]
        | null
    funnelFromStep: number
    funnelToStep: number
    kind?: 'EventsNode'
    limit?: number | null
    math?:
        | BaseMathTypeApi
        | FunnelMathTypeApi
        | PropertyMathTypeApi
        | CountPerActorMathTypeApi
        | GroupMathTypeApi
        | ExperimentMetricMathTypeApi
        | CalendarHeatmapMathTypeApi
        | 'hogql'
        | null
    math_group_type_index?: MathGroupTypeIndexApi | null
    math_hogql?: string | null
    math_multiplier?: number | null
    math_property?: string | null
    math_property_revenue_currency?: RevenueCurrencyPropertyConfigApi | null
    math_property_type?: string | null
    name?: string | null
    optionalInFunnel?: boolean | null
    /** Columns to order by */
    orderBy?: string[] | null
    /** Properties configurable in the interface */
    properties?:
        | (
              | EventPropertyFilterApi
              | PersonPropertyFilterApi
              | PersonMetadataPropertyFilterApi
              | ElementPropertyFilterApi
              | EventMetadataPropertyFilterApi
              | SessionPropertyFilterApi
              | CohortPropertyFilterApi
              | RecordingPropertyFilterApi
              | LogEntryPropertyFilterApi
              | GroupPropertyFilterApi
              | FeaturePropertyFilterApi
              | FlagPropertyFilterApi
              | HogQLPropertyFilterApi
              | EmptyPropertyFilterApi
              | DataWarehousePropertyFilterApi
              | DataWarehousePersonPropertyFilterApi
              | ErrorTrackingIssueFilterApi
              | LogPropertyFilterApi
              | MetricPropertyFilterApi
              | SpanPropertyFilterApi
              | RevenueAnalyticsPropertyFilterApi
              | AccountCustomPropertyFilterApi
              | WorkflowVariablePropertyFilterApi
              | BehavioralPropertyFilterApi
          )[]
        | null
    response?: FunnelExclusionEventsNodeApiResponse
    /** version of the node, used for schema migrations */
    version?: number | null
}

export type FunnelExclusionActionsNodeApiResponse = { [key: string]: unknown } | null

export interface FunnelExclusionActionsNodeApi {
    custom_name?: string | null
    /** Fixed properties in the query, can't be edited in the interface (e.g. scoping down by person) */
    fixedProperties?:
        | (
              | EventPropertyFilterApi
              | PersonPropertyFilterApi
              | PersonMetadataPropertyFilterApi
              | ElementPropertyFilterApi
              | EventMetadataPropertyFilterApi
              | SessionPropertyFilterApi
              | CohortPropertyFilterApi
              | RecordingPropertyFilterApi
              | LogEntryPropertyFilterApi
              | GroupPropertyFilterApi
              | FeaturePropertyFilterApi
              | FlagPropertyFilterApi
              | HogQLPropertyFilterApi
              | EmptyPropertyFilterApi
              | DataWarehousePropertyFilterApi
              | DataWarehousePersonPropertyFilterApi
              | ErrorTrackingIssueFilterApi
              | LogPropertyFilterApi
              | MetricPropertyFilterApi
              | SpanPropertyFilterApi
              | RevenueAnalyticsPropertyFilterApi
              | AccountCustomPropertyFilterApi
              | WorkflowVariablePropertyFilterApi
              | BehavioralPropertyFilterApi
          )[]
        | null
    funnelFromStep: number
    funnelToStep: number
    id: number
    kind?: 'ActionsNode'
    math?:
        | BaseMathTypeApi
        | FunnelMathTypeApi
        | PropertyMathTypeApi
        | CountPerActorMathTypeApi
        | GroupMathTypeApi
        | ExperimentMetricMathTypeApi
        | CalendarHeatmapMathTypeApi
        | 'hogql'
        | null
    math_group_type_index?: MathGroupTypeIndexApi | null
    math_hogql?: string | null
    math_multiplier?: number | null
    math_property?: string | null
    math_property_revenue_currency?: RevenueCurrencyPropertyConfigApi | null
    math_property_type?: string | null
    name?: string | null
    optionalInFunnel?: boolean | null
    /** Properties configurable in the interface */
    properties?:
        | (
              | EventPropertyFilterApi
              | PersonPropertyFilterApi
              | PersonMetadataPropertyFilterApi
              | ElementPropertyFilterApi
              | EventMetadataPropertyFilterApi
              | SessionPropertyFilterApi
              | CohortPropertyFilterApi
              | RecordingPropertyFilterApi
              | LogEntryPropertyFilterApi
              | GroupPropertyFilterApi
              | FeaturePropertyFilterApi
              | FlagPropertyFilterApi
              | HogQLPropertyFilterApi
              | EmptyPropertyFilterApi
              | DataWarehousePropertyFilterApi
              | DataWarehousePersonPropertyFilterApi
              | ErrorTrackingIssueFilterApi
              | LogPropertyFilterApi
              | MetricPropertyFilterApi
              | SpanPropertyFilterApi
              | RevenueAnalyticsPropertyFilterApi
              | AccountCustomPropertyFilterApi
              | WorkflowVariablePropertyFilterApi
              | BehavioralPropertyFilterApi
          )[]
        | null
    response?: FunnelExclusionActionsNodeApiResponse
    /** version of the node, used for schema migrations */
    version?: number | null
}

export type StepOrderValueApi = (typeof StepOrderValueApi)[keyof typeof StepOrderValueApi]

export const StepOrderValueApi = {
    Strict: 'strict',
    Unordered: 'unordered',
    Ordered: 'ordered',
} as const

export type FunnelStepReferenceApi = (typeof FunnelStepReferenceApi)[keyof typeof FunnelStepReferenceApi]

export const FunnelStepReferenceApi = {
    Total: 'total',
    Previous: 'previous',
} as const

export type FunnelVizTypeApi = (typeof FunnelVizTypeApi)[keyof typeof FunnelVizTypeApi]

export const FunnelVizTypeApi = {
    Steps: 'steps',
    TimeToConvert: 'time_to_convert',
    Trends: 'trends',
    Flow: 'flow',
} as const

export type FunnelConversionWindowTimeUnitApi =
    (typeof FunnelConversionWindowTimeUnitApi)[keyof typeof FunnelConversionWindowTimeUnitApi]

export const FunnelConversionWindowTimeUnitApi = {
    Second: 'second',
    Minute: 'minute',
    Hour: 'hour',
    Day: 'day',
    Week: 'week',
    Month: 'month',
} as const

export type CalculationApi = (typeof CalculationApi)[keyof typeof CalculationApi]

export const CalculationApi = {
    Fixed: 'fixed',
    Mean: 'mean',
    Median: 'median',
    Min: 'min',
    Max: 'max',
} as const

export type PositionApi = (typeof PositionApi)[keyof typeof PositionApi]

export const PositionApi = {
    Start: 'start',
    End: 'end',
} as const

export type ScopeApi = (typeof ScopeApi)[keyof typeof ScopeApi]

export const ScopeApi = {
    All: 'all',
    Series: 'series',
} as const

export interface GoalLineApi {
    borderColor?: string | null
    /** Recalculate from returned chart marks. An absent calculation uses the fixed value. */
    calculation?: CalculationApi | null
    displayIfCrossed?: boolean | null
    displayLabel?: boolean | null
    label: string
    position?: PositionApi | null
    /** SQL chart calculations use the primary axis, across all series or separately per series. */
    scope?: ScopeApi | null
    value: number
}

export type FunnelLayoutApi = (typeof FunnelLayoutApi)[keyof typeof FunnelLayoutApi]

export const FunnelLayoutApi = {
    Horizontal: 'horizontal',
    Vertical: 'vertical',
} as const

export type LegendPositionApi = (typeof LegendPositionApi)[keyof typeof LegendPositionApi]

export const LegendPositionApi = {
    Top: 'top',
    Bottom: 'bottom',
    Left: 'left',
    Right: 'right',
} as const

export type DataColorTokenApi = (typeof DataColorTokenApi)[keyof typeof DataColorTokenApi]

export const DataColorTokenApi = {
    Preset1: 'preset-1',
    Preset2: 'preset-2',
    Preset3: 'preset-3',
    Preset4: 'preset-4',
    Preset5: 'preset-5',
    Preset6: 'preset-6',
    Preset7: 'preset-7',
    Preset8: 'preset-8',
    Preset9: 'preset-9',
    Preset10: 'preset-10',
    Preset11: 'preset-11',
    Preset12: 'preset-12',
    Preset13: 'preset-13',
    Preset14: 'preset-14',
    Preset15: 'preset-15',
} as const

export type YAxisPosition2Api = (typeof YAxisPosition2Api)[keyof typeof YAxisPosition2Api]

export const YAxisPosition2Api = {
    Auto: 'auto',
    Left: 'left',
    Right: 'right',
} as const

export interface ResultCustomizationByValueApi {
    assignmentBy?: 'value'
    color?: DataColorTokenApi | null
    customColor?: string | null
    hidden?: boolean | null
    label?: string | null
    yAxisPosition?: YAxisPosition2Api | null
}

/**
 * Customizations for the appearance of result datasets.
 */
export type FunnelsFilterApiResultCustomizations = { [key: string]: ResultCustomizationByValueApi } | null

export interface FunnelsFilterApi {
    /** Render only annotations with this scope. Only applies to historical-trends funnels. */
    annotationsScope?: AnnotationScopeApi | null
    binCount?: number | null
    breakdownAttributionType?: BreakdownAttributionTypeApi | null
    breakdownAttributionValue?: number | null
    /** Breakdown table sorting. Format: 'column_key' or '-column_key' (descending) */
    breakdownSorting?: string | null
    /** Chart rendering style overrides (line shape). Only applies to historical-trends funnels. */
    chartStyle?: ChartStyleApi | null
    /** For data warehouse based funnel insights when the aggregation target can't be mapped to persons or groups. */
    customAggregationTarget?: boolean | null
    exclusions?: (FunnelExclusionEventsNodeApi | FunnelExclusionActionsNodeApi)[] | null
    funnelAggregateByHogQL?: string | null
    funnelFromStep?: number | null
    funnelOrderType?: StepOrderValueApi | null
    funnelStepReference?: FunnelStepReferenceApi | null
    /** To select the range of steps for trends & time to convert funnels, 0-indexed */
    funnelToStep?: number | null
    funnelVizType?: FunnelVizTypeApi | null
    funnelWindowInterval?: number | null
    funnelWindowIntervalUnit?: FunnelConversionWindowTimeUnitApi | null
    /** Goal Lines */
    goalLines?: GoalLineApi[] | null
    hiddenLegendBreakdowns?: string[] | null
    /** Trends only: hide periods whose conversion window has not fully elapsed yet, so the recent tail of the trend isn't dragged down by entrants who still have time to convert. */
    hideIncompleteConversionWindowPeriods?: boolean | null
    layout?: FunnelLayoutApi | null
    /** Where the in-chart legend sits relative to the plot. Only applies to the in-chart legend. */
    legendPosition?: LegendPositionApi | null
    /** Customizations for the appearance of result datasets. */
    resultCustomizations?: FunnelsFilterApiResultCustomizations
    /** Whether to render annotations on the chart. Only applies to historical-trends funnels. */
    showAnnotations?: boolean | null
    /** Whether to show a legend describing the series. The legend only renders when the funnel has multiple series. Only applies to historical-trends funnels. */
    showLegend?: boolean | null
    showSummaryOnDashboards?: boolean | null
    /** Display linear regression trend lines on the chart (only for historical trends viz) */
    showTrendLines?: boolean | null
    showValuesOnSeries?: boolean | null
    useUdf?: boolean | null
}

export type IntervalTypeApi = (typeof IntervalTypeApi)[keyof typeof IntervalTypeApi]

export const IntervalTypeApi = {
    Second: 'second',
    Minute: 'minute',
    Hour: 'hour',
    Day: 'day',
    Week: 'week',
    Month: 'month',
    Quarter: 'quarter',
    Year: 'year',
} as const

export type BounceRatePageViewModeApi = (typeof BounceRatePageViewModeApi)[keyof typeof BounceRatePageViewModeApi]

export const BounceRatePageViewModeApi = {
    CountPageviews: 'count_pageviews',
    UniqUrls: 'uniq_urls',
    UniqPageScreenAutocaptures: 'uniq_page_screen_autocaptures',
} as const

export type FilterLogicalOperatorApi = (typeof FilterLogicalOperatorApi)[keyof typeof FilterLogicalOperatorApi]

export const FilterLogicalOperatorApi = {
    And: 'AND',
    Or: 'OR',
} as const

export type CustomBotFieldApi = (typeof CustomBotFieldApi)[keyof typeof CustomBotFieldApi]

export const CustomBotFieldApi = {
    RawUserAgent: '$raw_user_agent',
    Ip: '$ip',
    Lib: '$lib',
    Host: '$host',
    Pathname: '$pathname',
    CurrentUrl: '$current_url',
    Browser: '$browser',
    Os: '$os',
    BrowserLanguage: '$browser_language',
    ScreenWidth: '$screen_width',
    ScreenHeight: '$screen_height',
    GeoipCountryCode: '$geoip_country_code',
    Referrer: '$referrer',
    ReferringDomain: '$referring_domain',
} as const

export type CustomBotMatcherApi = (typeof CustomBotMatcherApi)[keyof typeof CustomBotMatcherApi]

export const CustomBotMatcherApi = {
    Contains: 'contains',
    Regex: 'regex',
    Exact: 'exact',
    Cidr: 'cidr',
} as const

export interface CustomBotConditionApi {
    id: string
    /** The event property this condition reads. */
    key: CustomBotFieldApi
    matcher: CustomBotMatcherApi
    /** Matched against the property named by `key`. */
    pattern: string
}

export interface CustomBotRuleApi {
    /** Reported by `$virt_traffic_category`. Defaults to `custom`. */
    category?: string | null
    /** Whether every condition must match (AND) or any one of them (OR). */
    combiner: FilterLogicalOperatorApi
    id: string
    items: CustomBotConditionApi[]
    /** Reported by `$virt_bot_name` and `$virt_bot_operator` when the rule matches. */
    name: string
}

export type CustomChannelFieldApi = (typeof CustomChannelFieldApi)[keyof typeof CustomChannelFieldApi]

export const CustomChannelFieldApi = {
    UtmSource: 'utm_source',
    UtmMedium: 'utm_medium',
    UtmCampaign: 'utm_campaign',
    ReferringDomain: 'referring_domain',
    Url: 'url',
    Pathname: 'pathname',
    Hostname: 'hostname',
} as const

export type CustomChannelOperatorApi = (typeof CustomChannelOperatorApi)[keyof typeof CustomChannelOperatorApi]

export const CustomChannelOperatorApi = {
    Exact: 'exact',
    IsNot: 'is_not',
    IsSet: 'is_set',
    IsNotSet: 'is_not_set',
    Icontains: 'icontains',
    NotIcontains: 'not_icontains',
    Regex: 'regex',
    NotRegex: 'not_regex',
} as const

export interface CustomChannelConditionApi {
    id: string
    key: CustomChannelFieldApi
    op: CustomChannelOperatorApi
    value?: string | string[] | null
}

export interface CustomChannelRuleApi {
    channel_type: string
    combiner: FilterLogicalOperatorApi
    id: string
    items: CustomChannelConditionApi[]
}

export interface DataWarehouseEventsModifierApi {
    distinct_id_field: string
    id_field: string
    table_name: string
    timestamp_field: string
}

export type InCohortViaApi = (typeof InCohortViaApi)[keyof typeof InCohortViaApi]

export const InCohortViaApi = {
    Auto: 'auto',
    Leftjoin: 'leftjoin',
    Subquery: 'subquery',
    LeftjoinConjoined: 'leftjoin_conjoined',
} as const

export type InlineCohortCalculationApi = (typeof InlineCohortCalculationApi)[keyof typeof InlineCohortCalculationApi]

export const InlineCohortCalculationApi = {
    Off: 'off',
    Auto: 'auto',
    Always: 'always',
} as const

export type MaterializationModeApi = (typeof MaterializationModeApi)[keyof typeof MaterializationModeApi]

export const MaterializationModeApi = {
    Auto: 'auto',
    LegacyNullAsString: 'legacy_null_as_string',
    LegacyNullAsNull: 'legacy_null_as_null',
    Disabled: 'disabled',
} as const

export type MaterializedColumnsOptimizationModeApi =
    (typeof MaterializedColumnsOptimizationModeApi)[keyof typeof MaterializedColumnsOptimizationModeApi]

export const MaterializedColumnsOptimizationModeApi = {
    Disabled: 'disabled',
    Optimized: 'optimized',
} as const

export type ParserModeApi = (typeof ParserModeApi)[keyof typeof ParserModeApi]

export const ParserModeApi = {
    CppOnly: 'cpp_only',
    CppWithRustShadow: 'cpp_with_rust_shadow',
    CppWithRustPyShadow: 'cpp_with_rust_py_shadow',
    RustWithCppShadow: 'rust_with_cpp_shadow',
    RustOnly: 'rust_only',
    RustPyOnly: 'rust_py_only',
    RustPyWithCppShadow: 'rust_py_with_cpp_shadow',
} as const

export type PersonsArgMaxVersionApi = (typeof PersonsArgMaxVersionApi)[keyof typeof PersonsArgMaxVersionApi]

export const PersonsArgMaxVersionApi = {
    Auto: 'auto',
    V1: 'v1',
    V2: 'v2',
} as const

export type PersonsJoinModeApi = (typeof PersonsJoinModeApi)[keyof typeof PersonsJoinModeApi]

export const PersonsJoinModeApi = {
    Inner: 'inner',
    Left: 'left',
} as const

export type PersonsOnEventsModeApi = (typeof PersonsOnEventsModeApi)[keyof typeof PersonsOnEventsModeApi]

export const PersonsOnEventsModeApi = {
    Disabled: 'disabled',
    PersonIdNoOverridePropertiesOnEvents: 'person_id_no_override_properties_on_events',
    PersonIdOverridePropertiesOnEvents: 'person_id_override_properties_on_events',
    PersonIdOverridePropertiesJoined: 'person_id_override_properties_joined',
} as const

export type PropertyGroupsModeApi = (typeof PropertyGroupsModeApi)[keyof typeof PropertyGroupsModeApi]

export const PropertyGroupsModeApi = {
    Enabled: 'enabled',
    Disabled: 'disabled',
    Optimized: 'optimized',
} as const

export type SessionTableVersionApi = (typeof SessionTableVersionApi)[keyof typeof SessionTableVersionApi]

export const SessionTableVersionApi = {
    Auto: 'auto',
    V1: 'v1',
    V2: 'v2',
    V3: 'v3',
} as const

export type SessionsV2JoinModeApi = (typeof SessionsV2JoinModeApi)[keyof typeof SessionsV2JoinModeApi]

export const SessionsV2JoinModeApi = {
    String: 'string',
    Uuid: 'uuid',
} as const

export interface HogQLQueryModifiersApi {
    bounceRateDurationSeconds?: number | null
    bounceRatePageViewMode?: BounceRatePageViewModeApi | null
    convertToProjectTimezone?: boolean | null
    /** Do not treat a missing user agent as automation on cookieless events. Positive bot signals and custom project rules still apply. Resolved server-side; not intended to be set by clients. */
    cookielessTrafficIsRegular?: boolean | null
    customBotDefinitions?: CustomBotRuleApi[] | null
    customChannelTypeRules?: CustomChannelRuleApi[] | null
    dataWarehouseEventsModifiers?: DataWarehouseEventsModifierApi[] | null
    debug?: boolean | null
    /** If these are provided, the query will fail if these skip indexes are not used */
    forceClickhouseDataSkippingIndexes?: string[] | null
    formatCsvAllowDoubleQuotes?: boolean | null
    inCohortVia?: InCohortViaApi | null
    inlineCohortCalculation?: InlineCohortCalculationApi | null
    materializationMode?: MaterializationModeApi | null
    /** Reuse eligible bounded event aggregates within one query execution. When unset, the server may enable it via the cloud feature flag. */
    materializeRepeatedCTEs?: boolean | null
    materializedColumnsOptimizationMode?: MaterializedColumnsOptimizationModeApi | null
    /** Merge sibling aggregating LEFT JOINs over federated Postgres tables into one UNION ALL join, so their scans overlap */
    mergeFederatedAggregateJoins?: boolean | null
    /** Replace negated person-property filters in the WHERE of an `events` query (such as `email not_icontains`) with `person_id NOT IN (SELECT id FROM persons WHERE <the filters fail>)`, so the query no longer joins every person. Applies only when every filtered person property has a materialized column, nothing else in the query reads that persons join, and the join would be a LEFT JOIN. */
    negatedPersonFiltersNotIn?: boolean | null
    /** Move eligible non-nullable equality filters from CROSS JOIN queries into ALL INNER JOIN constraints */
    optimizeCrossJoins?: boolean | null
    optimizeJoinedFilters?: boolean | null
    optimizeProjections?: boolean | null
    /** HogQL parser backend; absent → `rust_py_with_cpp_shadow` (rust-py is primary, cpp runs as a sampled shadow). `*_shadow` modes return the primary result and sample-compare against the other parser, reporting divergences without failing the request. The `rust_py_*` modes drive the same hand-rolled Rust parser as `rust_*` but build `posthog.hogql.ast` dataclass instances directly via PyO3, skipping the JSON round-trip. */
    parserMode?: ParserModeApi | null
    /** Push an `id IN (SELECT person_id FROM <left table> WHERE …)` predicate into the joined persons subquery, so the latest-version lookup only reads persons that the outer query's left-table filters can reach. Applies only to a persons join from the query's own FROM table. Unset, it applies to a persons join from `posthog.flag_evaluations` or from the union of events and flag_evaluations, and to no other join. */
    personIdPushdown?: boolean | null
    personsArgMaxVersion?: PersonsArgMaxVersionApi | null
    personsJoinMode?: PersonsJoinModeApi | null
    personsOnEventsMode?: PersonsOnEventsModeApi | null
    propertyGroupsMode?: PropertyGroupsModeApi | null
    pushDownPredicates?: boolean | null
    s3TableUseInvalidColumns?: boolean | null
    /** Filter the sessions join of an events query by its session property filters and run it as a `GLOBAL LEFT JOIN`, so the sessions are read once instead of once per events shard. Applies only when every session filter is an equality or `IN` against non-empty strings, which are false for an event with no matching session. */
    sessionFilterGlobalJoin?: boolean | null
    /** Push a `session_id_v7 IN (SELECT … FROM events WHERE …)` predicate into the raw_sessions subquery to limit aggregation to sessions that participate in the outer events filter. */
    sessionIdPushdown?: boolean | null
    /** Pre-filter raw_sessions aggregation by `session_id_v7 IN (cheap pre-aggregation that only materializes the columns referenced by the outer-WHERE session predicate)`. Useful when the breakdown/SELECT pulls in many session columns (e.g. `$channel_type`) but the filter only references one (e.g. `$entry_current_url`). */
    sessionPropertyPreAggregation?: boolean | null
    sessionTableVersion?: SessionTableVersionApi | null
    /** Padding, in minutes, on each side of the event time range when it filters the sessions table by session start. Defaults to 3 days. It can only narrow the range: values above the default are ignored. Lower it only for a query that keeps just the sessions that start inside its own time range. */
    sessionTimestampBufferMinutes?: number | null
    sessionsV2JoinMode?: SessionsV2JoinModeApi | null
    timings?: boolean | null
    /** Remove provably redundant casts and nullability wrappers (e.g. `toString(String)`, `assumeNotNull(non_nullable)`, dead `ifNull` fallbacks) using inferred expression types */
    typeAwareCastSimplification?: boolean | null
    useMaterializedViews?: boolean | null
    /** Read events from the native JSON events table (`true`) or the legacy events table (`false`). When unset, a staff person's tab switch or `ph_new_events_schema` cookie applies, then the project. A project reads the native table once PostHog has moved it there. Before that, it can opt in early by storing `true` here in its project settings. A stored `false` is ignored. */
    useNewEventsSchema?: boolean | null
    usePreaggregatedIntermediateResults?: boolean | null
    /** Try to automatically convert HogQL queries to use preaggregated tables at the AST level * */
    usePreaggregatedTableTransforms?: boolean | null
    useWebAnalyticsPreAggregatedTables?: boolean | null
    /** Serve filters on the stored session-entry attribution properties (`$channel_type`, `$entry_utm_*`, `$entry_referring_domain`) by recomputing the value from the session's first pageview. Resolved server-side; not intended to be set by clients. */
    webAnalyticsFirstPageviewFilters?: boolean | null
}

export interface PropertyGroupFilterValueApi {
    type: FilterLogicalOperatorApi
    values: (
        | PropertyGroupFilterValueApi
        | EventPropertyFilterApi
        | PersonPropertyFilterApi
        | PersonMetadataPropertyFilterApi
        | ElementPropertyFilterApi
        | EventMetadataPropertyFilterApi
        | SessionPropertyFilterApi
        | CohortPropertyFilterApi
        | RecordingPropertyFilterApi
        | LogEntryPropertyFilterApi
        | GroupPropertyFilterApi
        | FeaturePropertyFilterApi
        | FlagPropertyFilterApi
        | HogQLPropertyFilterApi
        | EmptyPropertyFilterApi
        | DataWarehousePropertyFilterApi
        | DataWarehousePersonPropertyFilterApi
        | ErrorTrackingIssueFilterApi
        | LogPropertyFilterApi
        | MetricPropertyFilterApi
        | SpanPropertyFilterApi
        | RevenueAnalyticsPropertyFilterApi
        | AccountCustomPropertyFilterApi
        | WorkflowVariablePropertyFilterApi
        | BehavioralPropertyFilterApi
    )[]
}

export interface PropertyGroupFilterApi {
    type: FilterLogicalOperatorApi
    values: PropertyGroupFilterValueApi[]
}

export interface ClickhouseQueryProgressApi {
    active_cpu_time: number
    bytes_read: number
    estimated_rows_total: number
    rows_read: number
    time_elapsed: number
}

export type QueryScanFixLocationApi = (typeof QueryScanFixLocationApi)[keyof typeof QueryScanFixLocationApi]

export const QueryScanFixLocationApi = {
    Query: 'query',
    Subquery: 'subquery',
    View: 'view',
    InsightDateRange: 'insight_date_range',
    DashboardDateFilter: 'dashboard_date_filter',
} as const

export type QueryScanFindingKindApi = (typeof QueryScanFindingKindApi)[keyof typeof QueryScanFindingKindApi]

export const QueryScanFindingKindApi = {
    NoEventFilter: 'no_event_filter',
    NoStartDate: 'no_start_date',
    PersonsJoin: 'persons_join',
    RepeatedCteExpansion: 'repeated_cte_expansion',
    CrossJoinEquality: 'cross_join_equality',
    DateArraysBeforeBreakdownLimit: 'date_arrays_before_breakdown_limit',
} as const

export interface QueryScanWarningApi {
    /** Whether the person can change the query so it reads less and still answers the same question. Surfaces show the full advice and "Fix with AI" only when a finding is actionable. */
    actionable: boolean
    /** True when the query reads this much on purpose, so reading less would change the answer. Absent means no. */
    by_design?: boolean | null
    /** A label for what in the query text kept the read wide, such as `in_or`. Only analytics and the assistant read it, and the labels can change. */
    cause?: string | null
    /** The one fact the finding rests on. */
    evidence?: string | null
    /** What "Fix with AI" and the assistant are told to do. */
    fix: string
    /** Where the change goes. Absent means the query itself. */
    fix_location?: QueryScanFixLocationApi | null
    kind: QueryScanFindingKindApi
    /** Shown to the person: what happened and what to do. */
    message: string
}

export interface QueryScanAnalysisApi {
    /** The message the Fix with AI button sends to the assistant. Absent when no finding can be fixed in the query. */
    assistant_prompt?: string | null
    /** Every finding, fixable or not. Empty when the analysis found none. */
    findings: QueryScanWarningApi[]
    /** How much of all the project's events the query read, 0 to 1. */
    project_share?: number | null
    /** How much of the project's events in the query's date range the query read, 0 to 1. */
    range_share?: number | null
}

export interface QueryScanSummaryApi {
    /** The stored analysis, put on the response when it is served. Absent while the analysis runs, and when none was requested. */
    analysis?: QueryScanAnalysisApi | null
    /** True when the run asked for an analysis, or found one stored. While `analysis` is absent, poll `GET /query/scan/{cache_key}` for it. */
    analysis_requested?: boolean | null
    /** ClickHouse time for the last fresh run, summed over its ClickHouse queries. */
    duration_ms: number
    /** True when ClickHouse stopped the run instead of finishing it. */
    killed?: boolean | null
    /** Rows ClickHouse read for the last fresh run, all tables included. */
    rows_read: number
}

export interface QueryStatusApi {
    budget_remaining_bytes?: number | null
    bytes_read?: number | null
    /** Cache key of the run that failed, so clients can ask for its query scan. */
    cache_key?: string | null
    /** Whether the query is still running. Will be true if the query is complete, even if it errored. Either result or error will be set. */
    complete?: boolean | null
    dashboard_id?: number | null
    /** When did the query execution task finish (whether successfully or not). */
    end_time?: string | null
    /** If the query failed, this will be set to true. More information can be found in the error_message field. */
    error?: boolean | null
    /** Stable machine-readable code for the error, when known: the DRF exception code, the ClickHouse error name, the HogQL error code, or `unhandled_<exception class>` for a failure that no handler classified. */
    error_code?: string | null
    error_message?: string | null
    expiration_time?: string | null
    id: string
    insight_id?: number | null
    labels?: string[] | null
    /** When was the query execution task picked up by a worker. */
    pickup_time?: string | null
    /** ONLY async queries use QueryStatus. */
    query_async?: true
    query_progress?: ClickhouseQueryProgressApi | null
    query_scan?: QueryScanSummaryApi | null
    results?: unknown
    /** When was query execution task enqueued. */
    start_time?: string | null
    task_id?: string | null
    team_id: number
}

export interface ResolvedDateRangeResponseApi {
    date_from: string
    date_to: string
    /** The earliest timestamp the query reads, when only its first interval depends on rows from before date_from. Lifecycle sets it to the start of the interval before the range. */
    read_from?: string | null
}

export interface QueryTimingApi {
    /** Key. Shortened to 'k' to save on data. */
    k: string
    /** Time in seconds. Shortened to 't' to save on data. */
    t: number
}

export interface DataWarehouseSourceUsageApi {
    /** ExternalDataSource id */
    id: string
    /** Connector type of the source (e.g. Stripe, Postgres), if known */
    source_type?: string | null
    /** Warehouse table name that was referenced */
    table_name: string
    /** Whether the query read a history table of this source */
    uses_history_table?: boolean | null
}

export type WarehouseSuggestionNoteKindApi =
    (typeof WarehouseSuggestionNoteKindApi)[keyof typeof WarehouseSuggestionNoteKindApi]

export const WarehouseSuggestionNoteKindApi = {
    Materialize: 'materialize',
    Unmaterialize: 'unmaterialize',
} as const

export interface WarehouseSuggestionNoteApi {
    /** Whether this user can edit the view, which accepting the suggestion needs. */
    can_act: boolean
    /** The suggestion id to pass to `warehouse-suggestions-get`, `-accept-prepare` or `-dismiss`. */
    id: string
    /** What the suggestion proposes. */
    kind: WarehouseSuggestionNoteKindApi
    /** Plain-language note for the person, with the next step. */
    message: string
    /** Absolute link to the view's page in Models. */
    url: string
    /** The view's current name. */
    view_name: string
}

export interface DataWarehouseSyncWarningApi {
    /** True when the last sync is still within the table's sync interval, so the data is current and the warning only says it will stop updating (a sync paused recently). False or absent when the data is out of date. */
    data_is_current?: boolean | null
    /** Human-readable warning shown to the user */
    message: string
    /** Name of the ExternalDataSchema responsible for syncing the table */
    schema_name: string
    /** ID of the ExternalDataSource, used to link to its management page. Null for self-managed tables. */
    source_id?: string | null
    /** Source type, e.g. "Stripe", "Hubspot" */
    source_type: string
    /** Sync status that triggered the warning, e.g. "Failed", "Paused", "BillingLimitReached" */
    status: string
    /** Name of the warehouse table the warning refers to */
    table_name: string
    /** Tells warning kinds apart in the shared `warnings` list */
    type?: 'warehouse_sync'
}

export interface AccessControlFilterWarningApi {
    /** Human-readable warning shown to the user */
    message: string
    /** Resource types the user has access restrictions on, referenced by the query, e.g. ["insight", "dashboard"] */
    resources: string[]
    /** Tells warning kinds apart in the shared `warnings` list */
    type?: 'access_control'
}

export interface BreakdownNotAppliedWarningApi {
    /** Human-readable warning shown to the user */
    message: string
    /** Tells warning kinds apart in the shared `warnings` list */
    type?: 'breakdown_not_applied'
}

export interface FunnelsQueryResponseApi {
    /** Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise. */
    error?: string | null
    /** Generated HogQL query. */
    hogql?: string | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    /** Query status indicates whether next to the provided data, a query is still running. */
    query_status?: QueryStatusApi | null
    /** The resolved previous/comparison period date range, when comparing against another period */
    resolved_compare_date_range?: ResolvedDateRangeResponseApi | null
    /** The date range used for the query */
    resolved_date_range?: ResolvedDateRangeResponseApi | null
    results: unknown
    /** Measured timings for different parts of the query generation process */
    timings?: QueryTimingApi[] | null
    /** Median total conversion time across all completers, computed breakdown-agnostically for the Steps viz header. */
    total_median_conversion_time?: number | null
    /** Connector-synced data warehouse sources referenced by this query, if any. */
    used_data_warehouse_sources?: DataWarehouseSourceUsageApi[] | null
    /** Open warehouse suggestions about views this query read. Set only on fresh runs for agent callers; absent when not evaluated, empty when evaluated and none apply. */
    warehouse_suggestions?: WarehouseSuggestionNoteApi[] | null
    /** Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. Also carries access control warnings when a system-table query filters out objects the user can't access, and a breakdown warning when the query ran without its requested breakdown. */
    warnings?: (DataWarehouseSyncWarningApi | AccessControlFilterWarningApi | BreakdownNotAppliedWarningApi)[] | null
}

export type EventsNodeApiResponse = { [key: string]: unknown } | null

export interface EventsNodeApi {
    custom_name?: string | null
    /** The event or `null` for all events. */
    event?: string | null
    /** Fixed properties in the query, can't be edited in the interface (e.g. scoping down by person) */
    fixedProperties?:
        | (
              | EventPropertyFilterApi
              | PersonPropertyFilterApi
              | PersonMetadataPropertyFilterApi
              | ElementPropertyFilterApi
              | EventMetadataPropertyFilterApi
              | SessionPropertyFilterApi
              | CohortPropertyFilterApi
              | RecordingPropertyFilterApi
              | LogEntryPropertyFilterApi
              | GroupPropertyFilterApi
              | FeaturePropertyFilterApi
              | FlagPropertyFilterApi
              | HogQLPropertyFilterApi
              | EmptyPropertyFilterApi
              | DataWarehousePropertyFilterApi
              | DataWarehousePersonPropertyFilterApi
              | ErrorTrackingIssueFilterApi
              | LogPropertyFilterApi
              | MetricPropertyFilterApi
              | SpanPropertyFilterApi
              | RevenueAnalyticsPropertyFilterApi
              | AccountCustomPropertyFilterApi
              | WorkflowVariablePropertyFilterApi
              | BehavioralPropertyFilterApi
          )[]
        | null
    kind?: 'EventsNode'
    limit?: number | null
    math?:
        | BaseMathTypeApi
        | FunnelMathTypeApi
        | PropertyMathTypeApi
        | CountPerActorMathTypeApi
        | GroupMathTypeApi
        | ExperimentMetricMathTypeApi
        | CalendarHeatmapMathTypeApi
        | 'hogql'
        | null
    math_group_type_index?: MathGroupTypeIndexApi | null
    math_hogql?: string | null
    math_multiplier?: number | null
    math_property?: string | null
    math_property_revenue_currency?: RevenueCurrencyPropertyConfigApi | null
    math_property_type?: string | null
    name?: string | null
    optionalInFunnel?: boolean | null
    /** Columns to order by */
    orderBy?: string[] | null
    /** Properties configurable in the interface */
    properties?:
        | (
              | EventPropertyFilterApi
              | PersonPropertyFilterApi
              | PersonMetadataPropertyFilterApi
              | ElementPropertyFilterApi
              | EventMetadataPropertyFilterApi
              | SessionPropertyFilterApi
              | CohortPropertyFilterApi
              | RecordingPropertyFilterApi
              | LogEntryPropertyFilterApi
              | GroupPropertyFilterApi
              | FeaturePropertyFilterApi
              | FlagPropertyFilterApi
              | HogQLPropertyFilterApi
              | EmptyPropertyFilterApi
              | DataWarehousePropertyFilterApi
              | DataWarehousePersonPropertyFilterApi
              | ErrorTrackingIssueFilterApi
              | LogPropertyFilterApi
              | MetricPropertyFilterApi
              | SpanPropertyFilterApi
              | RevenueAnalyticsPropertyFilterApi
              | AccountCustomPropertyFilterApi
              | WorkflowVariablePropertyFilterApi
              | BehavioralPropertyFilterApi
          )[]
        | null
    response?: EventsNodeApiResponse
    /** version of the node, used for schema migrations */
    version?: number | null
}

export type ActionsNodeApiResponse = { [key: string]: unknown } | null

export interface ActionsNodeApi {
    custom_name?: string | null
    /** Fixed properties in the query, can't be edited in the interface (e.g. scoping down by person) */
    fixedProperties?:
        | (
              | EventPropertyFilterApi
              | PersonPropertyFilterApi
              | PersonMetadataPropertyFilterApi
              | ElementPropertyFilterApi
              | EventMetadataPropertyFilterApi
              | SessionPropertyFilterApi
              | CohortPropertyFilterApi
              | RecordingPropertyFilterApi
              | LogEntryPropertyFilterApi
              | GroupPropertyFilterApi
              | FeaturePropertyFilterApi
              | FlagPropertyFilterApi
              | HogQLPropertyFilterApi
              | EmptyPropertyFilterApi
              | DataWarehousePropertyFilterApi
              | DataWarehousePersonPropertyFilterApi
              | ErrorTrackingIssueFilterApi
              | LogPropertyFilterApi
              | MetricPropertyFilterApi
              | SpanPropertyFilterApi
              | RevenueAnalyticsPropertyFilterApi
              | AccountCustomPropertyFilterApi
              | WorkflowVariablePropertyFilterApi
              | BehavioralPropertyFilterApi
          )[]
        | null
    id: number
    kind?: 'ActionsNode'
    math?:
        | BaseMathTypeApi
        | FunnelMathTypeApi
        | PropertyMathTypeApi
        | CountPerActorMathTypeApi
        | GroupMathTypeApi
        | ExperimentMetricMathTypeApi
        | CalendarHeatmapMathTypeApi
        | 'hogql'
        | null
    math_group_type_index?: MathGroupTypeIndexApi | null
    math_hogql?: string | null
    math_multiplier?: number | null
    math_property?: string | null
    math_property_revenue_currency?: RevenueCurrencyPropertyConfigApi | null
    math_property_type?: string | null
    name?: string | null
    optionalInFunnel?: boolean | null
    /** Properties configurable in the interface */
    properties?:
        | (
              | EventPropertyFilterApi
              | PersonPropertyFilterApi
              | PersonMetadataPropertyFilterApi
              | ElementPropertyFilterApi
              | EventMetadataPropertyFilterApi
              | SessionPropertyFilterApi
              | CohortPropertyFilterApi
              | RecordingPropertyFilterApi
              | LogEntryPropertyFilterApi
              | GroupPropertyFilterApi
              | FeaturePropertyFilterApi
              | FlagPropertyFilterApi
              | HogQLPropertyFilterApi
              | EmptyPropertyFilterApi
              | DataWarehousePropertyFilterApi
              | DataWarehousePersonPropertyFilterApi
              | ErrorTrackingIssueFilterApi
              | LogPropertyFilterApi
              | MetricPropertyFilterApi
              | SpanPropertyFilterApi
              | RevenueAnalyticsPropertyFilterApi
              | AccountCustomPropertyFilterApi
              | WorkflowVariablePropertyFilterApi
              | BehavioralPropertyFilterApi
          )[]
        | null
    response?: ActionsNodeApiResponse
    /** version of the node, used for schema migrations */
    version?: number | null
}

export type FunnelsDataWarehouseNodeApiResponse = { [key: string]: unknown } | null

export interface FunnelsDataWarehouseNodeApi {
    aggregation_target_field: string
    custom_name?: string | null
    dw_source_type?: string | null
    /** Fixed properties in the query, can't be edited in the interface (e.g. scoping down by person) */
    fixedProperties?:
        | (
              | EventPropertyFilterApi
              | PersonPropertyFilterApi
              | PersonMetadataPropertyFilterApi
              | ElementPropertyFilterApi
              | EventMetadataPropertyFilterApi
              | SessionPropertyFilterApi
              | CohortPropertyFilterApi
              | RecordingPropertyFilterApi
              | LogEntryPropertyFilterApi
              | GroupPropertyFilterApi
              | FeaturePropertyFilterApi
              | FlagPropertyFilterApi
              | HogQLPropertyFilterApi
              | EmptyPropertyFilterApi
              | DataWarehousePropertyFilterApi
              | DataWarehousePersonPropertyFilterApi
              | ErrorTrackingIssueFilterApi
              | LogPropertyFilterApi
              | MetricPropertyFilterApi
              | SpanPropertyFilterApi
              | RevenueAnalyticsPropertyFilterApi
              | AccountCustomPropertyFilterApi
              | WorkflowVariablePropertyFilterApi
              | BehavioralPropertyFilterApi
          )[]
        | null
    id: string
    id_field: string
    kind?: 'FunnelsDataWarehouseNode'
    math?:
        | BaseMathTypeApi
        | FunnelMathTypeApi
        | PropertyMathTypeApi
        | CountPerActorMathTypeApi
        | GroupMathTypeApi
        | ExperimentMetricMathTypeApi
        | CalendarHeatmapMathTypeApi
        | 'hogql'
        | null
    math_group_type_index?: MathGroupTypeIndexApi | null
    math_hogql?: string | null
    math_multiplier?: number | null
    math_property?: string | null
    math_property_revenue_currency?: RevenueCurrencyPropertyConfigApi | null
    math_property_type?: string | null
    name?: string | null
    optionalInFunnel?: boolean | null
    /** Properties configurable in the interface */
    properties?:
        | (
              | EventPropertyFilterApi
              | PersonPropertyFilterApi
              | PersonMetadataPropertyFilterApi
              | ElementPropertyFilterApi
              | EventMetadataPropertyFilterApi
              | SessionPropertyFilterApi
              | CohortPropertyFilterApi
              | RecordingPropertyFilterApi
              | LogEntryPropertyFilterApi
              | GroupPropertyFilterApi
              | FeaturePropertyFilterApi
              | FlagPropertyFilterApi
              | HogQLPropertyFilterApi
              | EmptyPropertyFilterApi
              | DataWarehousePropertyFilterApi
              | DataWarehousePersonPropertyFilterApi
              | ErrorTrackingIssueFilterApi
              | LogPropertyFilterApi
              | MetricPropertyFilterApi
              | SpanPropertyFilterApi
              | RevenueAnalyticsPropertyFilterApi
              | AccountCustomPropertyFilterApi
              | WorkflowVariablePropertyFilterApi
              | BehavioralPropertyFilterApi
          )[]
        | null
    response?: FunnelsDataWarehouseNodeApiResponse
    table_name: string
    timestamp_field: string
    /** version of the node, used for schema migrations */
    version?: number | null
}

export type DataWarehouseNodeApiResponse = { [key: string]: unknown } | null

export interface DataWarehouseNodeApi {
    custom_name?: string | null
    distinct_id_field: string
    dw_source_type?: string | null
    /** Fixed properties in the query, can't be edited in the interface (e.g. scoping down by person) */
    fixedProperties?:
        | (
              | EventPropertyFilterApi
              | PersonPropertyFilterApi
              | PersonMetadataPropertyFilterApi
              | ElementPropertyFilterApi
              | EventMetadataPropertyFilterApi
              | SessionPropertyFilterApi
              | CohortPropertyFilterApi
              | RecordingPropertyFilterApi
              | LogEntryPropertyFilterApi
              | GroupPropertyFilterApi
              | FeaturePropertyFilterApi
              | FlagPropertyFilterApi
              | HogQLPropertyFilterApi
              | EmptyPropertyFilterApi
              | DataWarehousePropertyFilterApi
              | DataWarehousePersonPropertyFilterApi
              | ErrorTrackingIssueFilterApi
              | LogPropertyFilterApi
              | MetricPropertyFilterApi
              | SpanPropertyFilterApi
              | RevenueAnalyticsPropertyFilterApi
              | AccountCustomPropertyFilterApi
              | WorkflowVariablePropertyFilterApi
              | BehavioralPropertyFilterApi
          )[]
        | null
    id: string
    id_field: string
    kind?: 'DataWarehouseNode'
    math?:
        | BaseMathTypeApi
        | FunnelMathTypeApi
        | PropertyMathTypeApi
        | CountPerActorMathTypeApi
        | GroupMathTypeApi
        | ExperimentMetricMathTypeApi
        | CalendarHeatmapMathTypeApi
        | 'hogql'
        | null
    math_group_type_index?: MathGroupTypeIndexApi | null
    math_hogql?: string | null
    math_multiplier?: number | null
    math_property?: string | null
    math_property_revenue_currency?: RevenueCurrencyPropertyConfigApi | null
    math_property_type?: string | null
    name?: string | null
    optionalInFunnel?: boolean | null
    /** Properties configurable in the interface */
    properties?:
        | (
              | EventPropertyFilterApi
              | PersonPropertyFilterApi
              | PersonMetadataPropertyFilterApi
              | ElementPropertyFilterApi
              | EventMetadataPropertyFilterApi
              | SessionPropertyFilterApi
              | CohortPropertyFilterApi
              | RecordingPropertyFilterApi
              | LogEntryPropertyFilterApi
              | GroupPropertyFilterApi
              | FeaturePropertyFilterApi
              | FlagPropertyFilterApi
              | HogQLPropertyFilterApi
              | EmptyPropertyFilterApi
              | DataWarehousePropertyFilterApi
              | DataWarehousePersonPropertyFilterApi
              | ErrorTrackingIssueFilterApi
              | LogPropertyFilterApi
              | MetricPropertyFilterApi
              | SpanPropertyFilterApi
              | RevenueAnalyticsPropertyFilterApi
              | AccountCustomPropertyFilterApi
              | WorkflowVariablePropertyFilterApi
              | BehavioralPropertyFilterApi
          )[]
        | null
    response?: DataWarehouseNodeApiResponse
    table_name: string
    timestamp_field: string
    /** version of the node, used for schema migrations */
    version?: number | null
}

export type GroupNodeApiResponse = { [key: string]: unknown } | null

export interface GroupNodeApi {
    custom_name?: string | null
    /** Fixed properties in the query, can't be edited in the interface (e.g. scoping down by person) */
    fixedProperties?:
        | (
              | EventPropertyFilterApi
              | PersonPropertyFilterApi
              | PersonMetadataPropertyFilterApi
              | ElementPropertyFilterApi
              | EventMetadataPropertyFilterApi
              | SessionPropertyFilterApi
              | CohortPropertyFilterApi
              | RecordingPropertyFilterApi
              | LogEntryPropertyFilterApi
              | GroupPropertyFilterApi
              | FeaturePropertyFilterApi
              | FlagPropertyFilterApi
              | HogQLPropertyFilterApi
              | EmptyPropertyFilterApi
              | DataWarehousePropertyFilterApi
              | DataWarehousePersonPropertyFilterApi
              | ErrorTrackingIssueFilterApi
              | LogPropertyFilterApi
              | MetricPropertyFilterApi
              | SpanPropertyFilterApi
              | RevenueAnalyticsPropertyFilterApi
              | AccountCustomPropertyFilterApi
              | WorkflowVariablePropertyFilterApi
              | BehavioralPropertyFilterApi
          )[]
        | null
    kind?: 'GroupNode'
    limit?: number | null
    math?:
        | BaseMathTypeApi
        | FunnelMathTypeApi
        | PropertyMathTypeApi
        | CountPerActorMathTypeApi
        | GroupMathTypeApi
        | ExperimentMetricMathTypeApi
        | CalendarHeatmapMathTypeApi
        | 'hogql'
        | null
    math_group_type_index?: MathGroupTypeIndexApi | null
    math_hogql?: string | null
    math_multiplier?: number | null
    math_property?: string | null
    math_property_revenue_currency?: RevenueCurrencyPropertyConfigApi | null
    math_property_type?: string | null
    name?: string | null
    /** Entities to combine in this group */
    nodes: (EventsNodeApi | ActionsNodeApi | DataWarehouseNodeApi)[]
    /** Group of entities combined with AND/OR operator */
    operator: FilterLogicalOperatorApi
    optionalInFunnel?: boolean | null
    /** Columns to order by */
    orderBy?: string[] | null
    /** Properties configurable in the interface */
    properties?:
        | (
              | EventPropertyFilterApi
              | PersonPropertyFilterApi
              | PersonMetadataPropertyFilterApi
              | ElementPropertyFilterApi
              | EventMetadataPropertyFilterApi
              | SessionPropertyFilterApi
              | CohortPropertyFilterApi
              | RecordingPropertyFilterApi
              | LogEntryPropertyFilterApi
              | GroupPropertyFilterApi
              | FeaturePropertyFilterApi
              | FlagPropertyFilterApi
              | HogQLPropertyFilterApi
              | EmptyPropertyFilterApi
              | DataWarehousePropertyFilterApi
              | DataWarehousePersonPropertyFilterApi
              | ErrorTrackingIssueFilterApi
              | LogPropertyFilterApi
              | MetricPropertyFilterApi
              | SpanPropertyFilterApi
              | RevenueAnalyticsPropertyFilterApi
              | AccountCustomPropertyFilterApi
              | WorkflowVariablePropertyFilterApi
              | BehavioralPropertyFilterApi
          )[]
        | null
    response?: GroupNodeApiResponse
    /** version of the node, used for schema migrations */
    version?: number | null
}

export interface QueryLogTagsApi {
    /** Name of the query, preferably unique. For example web_analytics_vitals */
    name?: string | null
    /** Short id of the saved Web analytics filter preset this query was run under, if any. */
    presetId?: string | null
    /** Product responsible for this query. Use string, there's no need to churn the Schema when we add a new product * */
    productKey?: string | null
    /** Scene where this query is shown in the UI. Use string, there's no need to churn the Schema when we add a new Scene * */
    scene?: string | null
}

export interface FunnelsQueryApi {
    /** Groups aggregation */
    aggregation_group_type_index?: number | null
    /** Breakdown of the events and actions */
    breakdownFilter?: BreakdownFilterApi | null
    /** Compare to date range */
    compareFilter?: CompareFilterApi | null
    /** Colors used in the insight's visualization */
    dataColorTheme?: number | null
    /** Date range for the query */
    dateRange?: DateRangeApi | null
    /** Exclude internal and test users by applying the respective filters */
    filterTestAccounts?: boolean | null
    /** Properties specific to the funnels insight */
    funnelsFilter?: FunnelsFilterApi | null
    /** Granularity of the response. Can be one of `hour`, `day`, `week` or `month` */
    interval?: IntervalTypeApi | null
    kind?: 'FunnelsQuery'
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    /** Property filters for all series */
    properties?:
        | (
              | EventPropertyFilterApi
              | PersonPropertyFilterApi
              | PersonMetadataPropertyFilterApi
              | ElementPropertyFilterApi
              | EventMetadataPropertyFilterApi
              | SessionPropertyFilterApi
              | CohortPropertyFilterApi
              | RecordingPropertyFilterApi
              | LogEntryPropertyFilterApi
              | GroupPropertyFilterApi
              | FeaturePropertyFilterApi
              | FlagPropertyFilterApi
              | HogQLPropertyFilterApi
              | EmptyPropertyFilterApi
              | DataWarehousePropertyFilterApi
              | DataWarehousePersonPropertyFilterApi
              | ErrorTrackingIssueFilterApi
              | LogPropertyFilterApi
              | MetricPropertyFilterApi
              | SpanPropertyFilterApi
              | RevenueAnalyticsPropertyFilterApi
              | AccountCustomPropertyFilterApi
              | WorkflowVariablePropertyFilterApi
              | BehavioralPropertyFilterApi
          )[]
        | PropertyGroupFilterApi
        | null
    response?: FunnelsQueryResponseApi | null
    /** Sampling rate */
    samplingFactor?: number | null
    /** Events and actions to include */
    series: (EventsNodeApi | ActionsNodeApi | FunnelsDataWarehouseNodeApi | GroupNodeApi)[]
    /** Tags that will be added to the Query log comment */
    tags?: QueryLogTagsApi | null
    /** version of the node, used for schema migrations */
    version?: number | null
}

export interface JourneyFunnelQueryApi {
    /** Ordered funnel that counts the sessions that complete the journey's steps in order, within the journey's conversion window. Send it to the query endpoint to get per-step conversion. */
    readonly query: FunnelsQueryApi
}

/**
 * * `pending` - Pending
 * * `running` - Running
 * * `passed` - Passed
 * * `failed` - Failed
 * * `errored` - Errored
 * * `no_runs` - No runs
 */
export type JourneyDeployStatusEnumApi = (typeof JourneyDeployStatusEnumApi)[keyof typeof JourneyDeployStatusEnumApi]

export const JourneyDeployStatusEnumApi = {
    Pending: 'pending',
    Running: 'running',
    Passed: 'passed',
    Failed: 'failed',
    Errored: 'errored',
    NoRuns: 'no_runs',
} as const

export interface JourneyDeployApi {
    /** Unique identifier of the deploy. */
    id: string
    /** Project the deploy belongs to. */
    team_id: number
    /** Commit that was deployed. */
    commit_sha: string
    /**
     * Branch that was deployed, when CI sent one.
     * @nullable
     */
    branch: string | null
    /**
     * Origin of the build the runs opened, for example a preview deployment. Null when each journey opened its own start URL.
     * @nullable
     */
    base_url: string | null
    /**
     * Short name for the deploy, when CI sent one.
     * @nullable
     */
    label: string | null
    /**
     * Link to the commit or the CI run, when CI sent one.
     * @nullable
     */
    url: string | null
    /** When the build was deployed. Defaults to when PostHog recorded the deploy. */
    deployed_at: string
    /** When PostHog recorded the deploy. */
    created_at: string
    /**
     * ID of the user whose key recorded the deploy. Null for a project secret API key.
     * @nullable
     */
    created_by_id: number | null
    /** Verdict on the deploy's runs. `pending` while no run has started and `running` while any run is unfinished. `failed` as soon as any run fails, even while others are unfinished. Otherwise, once every run has ended, `errored` when any run couldn't finish and `passed` when every run passed. `no_runs` when the deploy started no run. Every status except `pending` and `running` is final.
     *
     * * `pending` - Pending
     * * `running` - Running
     * * `passed` - Passed
     * * `failed` - Failed
     * * `errored` - Errored
     * * `no_runs` - No runs */
    status: JourneyDeployStatusEnumApi
    /** Number of runs the deploy started. */
    run_count: number
    /** Journeys that didn't run because the project has more than 50. The oldest journeys run first. */
    journeys_over_limit: number
}

export interface PaginatedJourneyDeployListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: JourneyDeployApi[]
}

export interface CreateJourneyDeployApi {
    /**
     * Commit that was deployed.
     * @maxLength 64
     */
    commit_sha: string
    /**
     * Branch that was deployed.
     * @maxLength 255
     * @nullable
     */
    branch?: string | null
    /**
     * Run against this deployment, for example a preview. Only the origin (scheme, host and port) is used: it replaces the origin of every URL each journey opens and checks. Its host must be one of the project's authorized URLs. Leave it out to run each journey against its own start URL.
     * @maxLength 2048
     * @nullable
     */
    base_url?: string | null
    /**
     * When the build was deployed, in ISO 8601. Defaults to now.
     * @nullable
     */
    deployed_at?: string | null
    /**
     * Short name for the deploy, for example a release tag.
     * @maxLength 255
     * @nullable
     */
    label?: string | null
    /**
     * Link to the commit or the CI run, starting with http:// or https://.
     * @maxLength 2048
     * @nullable
     */
    url?: string | null
    /**
     * Journeys to run, at most 50. Leave it out to run every journey of the project, the oldest 50 first. Send an empty list to record the deploy without running any journey. A retry with the same `commit_sha` and `base_url` within 10 minutes returns the first deploy and starts no runs.
     * @maxItems 50
     * @nullable
     */
    journey_ids?: string[] | null
}

export interface JourneyDeployRunApi {
    /** Journey the run replayed. */
    journey_id: string
    /** Name of the journey. */
    journey_name: string
    /** The run. Get it from the journey's runs to see each step and its screenshots. */
    run_id: string
    /** Status of the run: `pending`, `running`, `passed`, `failed` or `errored`.
     *
     * * `pending` - Pending
     * * `running` - Running
     * * `passed` - Passed
     * * `failed` - Failed
     * * `errored` - Errored */
    status: JourneyRunStatusEnumApi
    /**
     * When the run ended. Null while it is unfinished.
     * @nullable
     */
    finished_at: string | null
    /**
     * Position of the first failed step, from 0. Null unless a step failed.
     * @nullable
     */
    failed_step_index: number | null
    /** Why the first failed step failed. Null unless a step failed.
     *
     * * `element_not_found` - Element not found
     * * `element_not_visible` - Element not visible
     * * `element_obscured` - Element covered by another element
     * * `element_outside_viewport_unreachable` - Element outside the viewport and can't be scrolled to
     * * `navigation_mismatch` - Page URL doesn't match
     * * `navigation_failed` - Page failed to load
     * * `navigation_blocked` - Navigation to a URL that isn't allowed
     * * `timeout` - Timed out */
    failure_reason: JourneyStepFailureReasonEnumApi | null
    /** What went wrong: the failed step's message, or why an errored run couldn't finish. */
    message: string
}

/**
 * * `journey_not_found` - Journey not found
 * * `not_runnable` - Journey can't run
 * * `target_not_allowed` - Start page isn't allowed
 * * `run_in_progress` - Run already in progress
 */
export type JourneyDeploySkipReasonEnumApi =
    (typeof JourneyDeploySkipReasonEnumApi)[keyof typeof JourneyDeploySkipReasonEnumApi]

export const JourneyDeploySkipReasonEnumApi = {
    JourneyNotFound: 'journey_not_found',
    NotRunnable: 'not_runnable',
    TargetNotAllowed: 'target_not_allowed',
    RunInProgress: 'run_in_progress',
} as const

export interface JourneyDeploySkipApi {
    /** Journey that didn't run. */
    journey_id: string
    /**
     * Name of the journey. Null when the project has no journey with this ID.
     * @nullable
     */
    journey_name: string | null
    /** Why the journey didn't run: `journey_not_found`, `not_runnable` when it has no page to start from, `target_not_allowed` when its start page isn't one of the project's authorized URLs, or `run_in_progress` when an earlier run of it hasn't finished.
     *
     * * `journey_not_found` - Journey not found
     * * `not_runnable` - Journey can't run
     * * `target_not_allowed` - Start page isn't allowed
     * * `run_in_progress` - Run already in progress */
    reason: JourneyDeploySkipReasonEnumApi
    /** What to change so that the journey runs next time. */
    message: string
}

export interface JourneyDeployDetailApi {
    /** One summary for each run the deploy started. */
    runs: JourneyDeployRunApi[]
    /** Each selected journey that didn't run, and why. */
    skipped: JourneyDeploySkipApi[]
    /** Unique identifier of the deploy. */
    id: string
    /** Project the deploy belongs to. */
    team_id: number
    /** Commit that was deployed. */
    commit_sha: string
    /**
     * Branch that was deployed, when CI sent one.
     * @nullable
     */
    branch: string | null
    /**
     * Origin of the build the runs opened, for example a preview deployment. Null when each journey opened its own start URL.
     * @nullable
     */
    base_url: string | null
    /**
     * Short name for the deploy, when CI sent one.
     * @nullable
     */
    label: string | null
    /**
     * Link to the commit or the CI run, when CI sent one.
     * @nullable
     */
    url: string | null
    /** When the build was deployed. Defaults to when PostHog recorded the deploy. */
    deployed_at: string
    /** When PostHog recorded the deploy. */
    created_at: string
    /**
     * ID of the user whose key recorded the deploy. Null for a project secret API key.
     * @nullable
     */
    created_by_id: number | null
    /** Verdict on the deploy's runs. `pending` while no run has started and `running` while any run is unfinished. `failed` as soon as any run fails, even while others are unfinished. Otherwise, once every run has ended, `errored` when any run couldn't finish and `passed` when every run passed. `no_runs` when the deploy started no run. Every status except `pending` and `running` is final.
     *
     * * `pending` - Pending
     * * `running` - Running
     * * `passed` - Passed
     * * `failed` - Failed
     * * `errored` - Errored
     * * `no_runs` - No runs */
    status: JourneyDeployStatusEnumApi
    /** Number of runs the deploy started. */
    run_count: number
    /** Journeys that didn't run because the project has more than 50. The oldest journeys run first. */
    journeys_over_limit: number
}

export interface ElementPathNodeApi {
    /** The journey step this node stands for, in the shape that journey `steps` accept. Send it as is to save the path as a journey. */
    step: JourneyStepApi
    /** Display name of the node: the page path, or the text, link or tag of the element. */
    label: string
    /** True for the clicked element that the request asked about. */
    is_anchor: boolean
    /** True when `step` matches exactly the events this node counts. False when it is a best-effort match: an element step names only the innermost tag or id of the clicked element, and a pageview step built from a cleaned path also matches other paths that clean to the same value. */
    step_is_exact: boolean
}

export interface ElementPathApi {
    /** Steps of the path in time order. */
    nodes: ElementPathNodeApi[]
    /** Number of analyzed sessions that took this path. */
    session_count: number
    /** `session_count` divided by `analyzed_session_count`, from 0 to 1. */
    share_of_anchor_sessions: number
    /** Zero-based position of the clicked element in `nodes`. */
    anchor_index: number
}

export interface ElementPathsResultApi {
    /** Most common paths, most sessions first. Only paths that at least two sessions took are included, so an element with clicks can have no paths. */
    paths: ElementPathApi[]
    /** Start of the date range that the query used. */
    date_from: string
    /** End of the date range that the query used. */
    date_to: string
    /** Autocaptured clicks on the element in the date range. Zero means nobody clicked it. */
    anchor_click_count: number
    /** Sessions with at least one click on the element. */
    anchor_session_count: number
    /** Sessions that the paths come from. Less than `anchor_session_count` when the query takes a sample of the sessions to limit its cost. */
    analyzed_session_count: number
}

export type UserJourneysListParams = {
    /**
     * Number of results to return per page.
     * @maximum 1000
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type UserJourneysRunsListParams = {
    /**
     * Number of results to return per page.
     * @maximum 1000
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type UserJourneysDeploysListParams = {
    /**
     * Number of results to return per page.
     * @maximum 1000
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type UserJourneysElementPathsRetrieveParams = {
    /**
     * Start of the date range, as a relative date such as `-7d` or an ISO date. The range can be at most 31 days.
     * @minLength 1
     */
    date_from?: string
    /**
     * End of the date range, as a relative or ISO date. Leave out for now.
     * @minLength 1
     */
    date_to?: string
    /**
     * Leave out clicks by the project's test accounts.
     */
    filter_test_accounts?: boolean
    /**
     * Exact link target of the clicked element. Leave out to match any link.
     * @minLength 1
     * @maxLength 2048
     */
    href?: string
    /**
     * Most paths to return.
     * @minimum 1
     * @maximum 25
     */
    limit?: number
    /**
     * CSS selector of the clicked element, for example `button.signup`.
     * @minLength 1
     * @maxLength 1024
     */
    selector: string
    /**
     * Most steps to show after the click.
     * @minimum 0
     * @maximum 4
     */
    steps_after?: number
    /**
     * Most steps to show before the click.
     * @minimum 0
     * @maximum 4
     */
    steps_before?: number
    /**
     * Exact text of the clicked element. Leave out to match any text.
     * @minLength 1
     * @maxLength 400
     */
    text?: string
    /**
     * URL of the page the click happens on. Leave out to match the click on any page.
     * @minLength 1
     * @maxLength 2048
     */
    url?: string
    /**
     * How `url` is compared with the page URL: `exact`, `contains` (case-insensitive) or `regex`.
     *
     * * `exact` - Exact
     * * `contains` - Contains
     * * `regex` - Regex
     * @minLength 1
     */
    url_matching?: UserJourneysElementPathsRetrieveUrlMatching
}

export type UserJourneysElementPathsRetrieveUrlMatching =
    (typeof UserJourneysElementPathsRetrieveUrlMatching)[keyof typeof UserJourneysElementPathsRetrieveUrlMatching]

export const UserJourneysElementPathsRetrieveUrlMatching = {
    Exact: 'exact',
    Contains: 'contains',
    Regex: 'regex',
} as const
