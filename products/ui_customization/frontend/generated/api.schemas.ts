/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
export type FragmentIconApi = (typeof FragmentIconApi)[keyof typeof FragmentIconApi]

export const FragmentIconApi = {
    List: 'list',
    Person: 'person',
    People: 'people',
    Box: 'box',
    Bell: 'bell',
    Notification: 'notification',
    Posthog: 'posthog',
    Chart: 'chart',
    Dashboard: 'dashboard',
    Notebook: 'notebook',
    Sql: 'sql',
    Star: 'star',
    Rocket: 'rocket',
    Target: 'target',
    Trending: 'trending',
    Globe: 'globe',
    Sparkle: 'sparkle',
    Bolt: 'bolt',
    Flag: 'flag',
    Warning: 'warning',
} as const

export type AnalyticsPageApi = (typeof AnalyticsPageApi)[keyof typeof AnalyticsPageApi]

export const AnalyticsPageApi = {
    AnalyticsAll: 'analytics_all',
    AnalyticsMine: 'analytics_mine',
    Collections: 'collections',
    Alerts: 'alerts',
    Subscriptions: 'subscriptions',
    ProductAnalytics: 'product_analytics',
    WebAnalytics: 'web_analytics',
    SqlEditor: 'sql_editor',
    NewInsight: 'new_insight',
} as const

/**
 * A PostHog page. It has its own label and icon.
 */
export interface AnalyticsPageTargetApi {
    kind: 'page'
    page: AnalyticsPageApi
}

export interface AnalyticsInsightTargetApi {
    kind: 'insight'
    /**
     * The insight's short ID, as in /insights/<short_id>.
     * @pattern ^[A-Za-z0-9]{1,12}$
     */
    short_id: string
}

export interface AnalyticsDashboardTargetApi {
    kind: 'dashboard'
    /**
     * The dashboard's numeric ID.
     * @minimum 1
     */
    id: number
}

export interface AnalyticsNotebookTargetApi {
    kind: 'notebook'
    /**
     * The notebook's short ID, as in /notebooks/<short_id>.
     * @pattern ^[A-Za-z0-9]{1,12}$
     */
    short_id: string
}

/**
 * A link to an Analytics page or a project object. Object links require a label. A page link shows the page's own label and icon unless you set them.
 */
export interface AnalyticsFragmentLinkApi {
    type: 'link'
    /** What the item opens. Only pages, and insights, dashboards and notebooks that exist in this project. */
    to: AnalyticsPageTargetApi | AnalyticsInsightTargetApi | AnalyticsDashboardTargetApi | AnalyticsNotebookTargetApi
    label?: string | null
    icon?: FragmentIconApi | null
}

export type FragmentButtonVariantApi = (typeof FragmentButtonVariantApi)[keyof typeof FragmentButtonVariantApi]

export const FragmentButtonVariantApi = {
    Default: 'default',
    Primary: 'primary',
    Outline: 'outline',
} as const

/**
 * A button that opens an Analytics page or a project object.
 */
export interface AnalyticsFragmentButtonApi {
    type: 'button'
    /** What the item opens. Only pages, and insights, dashboards and notebooks that exist in this project. */
    to: AnalyticsPageTargetApi | AnalyticsInsightTargetApi | AnalyticsDashboardTargetApi | AnalyticsNotebookTargetApi
    /**
     * @minLength 1
     * @maxLength 60
     * @pattern ^[^\x00]*$
     */
    label: string
    icon?: FragmentIconApi | null
    variant?: FragmentButtonVariantApi
}

/**
 * The latest value of a trends insight, with a sparkline of its first series. Opens the insight.
 */
export interface AnalyticsFragmentMetricApi {
    type: 'metric'
    /**
     * Short ID of a trends insight, one whose query source kind is TrendsQuery. Link to other insights.
     * @pattern ^[A-Za-z0-9]{1,12}$
     */
    insight: string
    /**
     * Short name of the number, such as Signups.
     * @minLength 1
     * @maxLength 60
     * @pattern ^[^\x00]*$
     */
    label: string
}

export type AnalyticsListSourceApi = (typeof AnalyticsListSourceApi)[keyof typeof AnalyticsListSourceApi]

export const AnalyticsListSourceApi = {
    Pinned: 'pinned',
    Recents: 'recents',
    ByPosthog: 'by_posthog',
} as const

/**
 * A list of pinned, recent, or built-in Analytics items.
 */
export interface AnalyticsFragmentListApi {
    type: 'list'
    source: AnalyticsListSourceApi
}

export interface AnalyticsFragmentSectionApi {
    /**
     * Stable ID in lowercase kebab case, unique in the layout. The section's open or closed state is kept by this ID, so keep the ID of an existing section when you move or rename it.
     * @minLength 1
     * @maxLength 32
     * @pattern ^[a-z0-9]+(?:-[a-z0-9]+)*$
     */
    id: string
    /** Heading of the section. A section with a heading can be closed. A section without one shows its items in its place in the layout, with no heading. */
    title?: string | null
    /** Icon before the heading. */
    icon?: FragmentIconApi | null
    /**
     * @minItems 1
     * @maxItems 12
     */
    items: (
        | AnalyticsFragmentLinkApi
        | AnalyticsFragmentButtonApi
        | AnalyticsFragmentMetricApi
        | AnalyticsFragmentListApi
    )[]
}

/**
 * The Analytics context's fragment. A section with no items to show is hidden.
 */
export interface AnalyticsFragmentLayoutApi {
    version?: 1
    /**
     * Use at most 30 items across all sections, including at most 4 metrics. Each built-in list counts as one item. Section IDs must be unique. Each list source can appear only once in the layout.
     * @minItems 1
     * @maxItems 10
     */
    sections: AnalyticsFragmentSectionApi[]
}

export interface CustomizationApi {
    /** The layout for the selected context. For analytics_sidebar, the sections of the Analytics pane, from top to bottom. Each section holds links, buttons, metrics and lists. Links and buttons open PostHog pages or this project's insights, dashboards and notebooks, never other sites. A section whose items show nothing, such as an empty pinned list, is hidden. */
    layout: AnalyticsFragmentLayoutApi
    /** True when the person saved their own layout. False for the default layout. */
    customized: boolean
}

export interface CustomizationRequestApi {
    /** The layout for the selected context. For analytics_sidebar, the sections of the Analytics pane, from top to bottom. Each section holds links, buttons, metrics and lists. Links and buttons open PostHog pages or this project's insights, dashboards and notebooks, never other sites. A section whose items show nothing, such as an empty pinned list, is hidden. The layout replaces the whole fragment, so send every section to keep. */
    layout: AnalyticsFragmentLayoutApi
}

/**
 * JSON Schema for the layout, generated from the save validator. Read descriptions for additional rules enforced by the server.
 */
export type CustomizationDescriptionApiLayoutSchema = { [key: string]: unknown }

/**
 * * `analytics_sidebar` - Analytics sidebar
 */
export type CustomizationContextEnumApi = (typeof CustomizationContextEnumApi)[keyof typeof CustomizationContextEnumApi]

export const CustomizationContextEnumApi = {
    AnalyticsSidebar: 'analytics_sidebar',
} as const

export interface CustomizationDescriptionApi {
    /** The UI customization context.
     *
     * * `analytics_sidebar` - Analytics sidebar */
    context: CustomizationContextEnumApi
    /** JSON Schema for the layout, generated from the save validator. Read descriptions for additional rules enforced by the server. */
    layout_schema: CustomizationDescriptionApiLayoutSchema
    /** The context's default layout, usable as a starting point. */
    default_layout: AnalyticsFragmentLayoutApi
}
