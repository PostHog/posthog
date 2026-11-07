/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
export type SidebarIconApi = (typeof SidebarIconApi)[keyof typeof SidebarIconApi]

export const SidebarIconApi = {
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

export type SidebarPageApi = (typeof SidebarPageApi)[keyof typeof SidebarPageApi]

export const SidebarPageApi = {
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
export interface SidebarPageTargetApi {
    kind: 'page'
    page: SidebarPageApi
}

export interface SidebarInsightTargetApi {
    kind: 'insight'
    /**
     * The insight's short ID, as in /insights/<short_id>.
     * @pattern ^[A-Za-z0-9]{1,12}$
     */
    short_id: string
}

export interface SidebarDashboardTargetApi {
    kind: 'dashboard'
    /**
     * The dashboard's numeric ID.
     * @minimum 1
     */
    id: number
}

export interface SidebarNotebookTargetApi {
    kind: 'notebook'
    /**
     * The notebook's short ID, as in /notebooks/<short_id>.
     * @pattern ^[A-Za-z0-9]{1,12}$
     */
    short_id: string
}

/**
 * A row that opens a page or an object.
 */
export interface SidebarLinkApi {
    type: 'link'
    /** What the item opens. Only pages and objects of this project. */
    to: SidebarPageTargetApi | SidebarInsightTargetApi | SidebarDashboardTargetApi | SidebarNotebookTargetApi
    /** Text of the row. Leave it out for a page to use the page's name. Required otherwise. */
    label?: string | null
    /** Icon of the row. A page has its own icon. */
    icon?: SidebarIconApi | null
}

export type SidebarButtonVariantApi = (typeof SidebarButtonVariantApi)[keyof typeof SidebarButtonVariantApi]

export const SidebarButtonVariantApi = {
    Default: 'default',
    Primary: 'primary',
    Outline: 'outline',
} as const

/**
 * A button that opens a page or an object. Use it for an action, such as a new insight.
 */
export interface SidebarButtonApi {
    type: 'button'
    /** What the item opens. Only pages and objects of this project. */
    to: SidebarPageTargetApi | SidebarInsightTargetApi | SidebarDashboardTargetApi | SidebarNotebookTargetApi
    /**
     * @minLength 1
     * @maxLength 60
     * @pattern ^[^\x00]*$
     */
    label: string
    icon?: SidebarIconApi | null
    variant?: SidebarButtonVariantApi
}

/**
 * The latest value of a trends insight, with a sparkline of its first series. Opens the insight.
 */
export interface SidebarMetricApi {
    type: 'metric'
    /**
     * Short ID of a trends insight.
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

export type SidebarListSourceApi = (typeof SidebarListSourceApi)[keyof typeof SidebarListSourceApi]

export const SidebarListSourceApi = {
    Pinned: 'pinned',
    Recents: 'recents',
    ByPosthog: 'by_posthog',
} as const

/**
 * A list that PostHog fills, such as the items the person pinned.
 */
export interface SidebarListApi {
    type: 'list'
    source: SidebarListSourceApi
}

export interface SidebarSectionApi {
    /**
     * Stable ID in lowercase kebab case, unique in the layout. The section's open or closed state is kept by this ID.
     * @minLength 1
     * @maxLength 32
     * @pattern ^[a-z0-9]+(?:-[a-z0-9]+)*$
     */
    id: string
    /** Heading of the section. A section with a heading can be closed. Without one, its items show at the top. */
    title?: string | null
    /** Icon before the heading. */
    icon?: SidebarIconApi | null
    /**
     * @minItems 1
     * @maxItems 12
     */
    items: (SidebarLinkApi | SidebarButtonApi | SidebarMetricApi | SidebarListApi)[]
}

/**
 * The sections of the Analytics pane, from top to bottom. A section with no items to show is hidden.
 */
export interface AnalyticsSidebarLayoutApi {
    version?: 1
    /**
     * @minItems 1
     * @maxItems 10
     */
    sections: SidebarSectionApi[]
}

export interface AnalyticsSidebarApi {
    /** The sections of the Analytics pane, from top to bottom. Each section holds links, buttons, metrics and lists. Links and buttons open PostHog pages or this project's insights, dashboards and notebooks, never other sites. A section whose items show nothing, such as an empty pinned list, is hidden. */
    layout: AnalyticsSidebarLayoutApi
    /** True when the person saved their own layout. False for the default layout. */
    customized: boolean
}

export interface AnalyticsSidebarRequestApi {
    /** The sections of the Analytics pane, from top to bottom. Each section holds links, buttons, metrics and lists. Links and buttons open PostHog pages or this project's insights, dashboards and notebooks, never other sites. A section whose items show nothing, such as an empty pinned list, is hidden. The layout replaces the whole sidebar, so send every section to keep. */
    layout: AnalyticsSidebarLayoutApi
}
