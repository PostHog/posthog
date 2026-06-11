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
 * * `pending` - Pending
 * * `acknowledged` - Acknowledged
 * * `resolved` - Resolved
 * * `dismissed` - Dismissed
 */
export type AnnotationStatusEnumApi = (typeof AnnotationStatusEnumApi)[keyof typeof AnnotationStatusEnumApi]

export const AnnotationStatusEnumApi = {
    Pending: 'pending',
    Acknowledged: 'acknowledged',
    Resolved: 'resolved',
    Dismissed: 'dismissed',
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
 * Structured element metadata (inferred selectors, attributes, component hints).
 */
export type ToolbarAnnotationApiElementContext = { [key: string]: unknown }

/**
 * Viewport size when the annotation was made, as {width, height}.
 * @nullable
 */
export type ToolbarAnnotationApiViewport = {
    /** Viewport width in pixels. */
    width?: number
    /** Viewport height in pixels. */
    height?: number
} | null

export interface ToolbarAnnotationApi {
    readonly id: string
    /**
     * The annotation note the user wrote about the element.
     * @maxLength 5000
     */
    comment: string
    /** Lifecycle of the annotation: pending, acknowledged, resolved, or dismissed. Ignored on create.
     *
     * * `pending` - Pending
     * * `acknowledged` - Acknowledged
     * * `resolved` - Resolved
     * * `dismissed` - Dismissed */
    annotation_status?: AnnotationStatusEnumApi
    /**
     * Optional note left by the agent when acknowledging, resolving, or dismissing the annotation.
     * @nullable
     */
    resolution?: string | null
    /**
     * Full URL of the page the annotation was made on.
     * @maxLength 2048
     */
    url: string
    /**
     * Hostname of the page, used to scope annotations to a site.
     * @maxLength 255
     */
    host: string
    /**
     * Path portion of the URL.
     * @maxLength 2048
     * @nullable
     */
    pathname?: string | null
    /**
     * CSS selector that locates the annotated element on the page.
     * @maxLength 4096
     */
    selector: string
    /**
     * Visible text of the annotated element, if any.
     * @maxLength 2048
     * @nullable
     */
    element_text?: string | null
    /**
     * Serialized autocapture-style element chain from the element up to the document root.
     * @maxLength 20000
     * @nullable
     */
    element_chain?: string | null
    /** Structured element metadata (inferred selectors, attributes, component hints). */
    element_context?: ToolbarAnnotationApiElementContext
    /**
     * Viewport size when the annotation was made, as {width, height}.
     * @nullable
     */
    viewport?: ToolbarAnnotationApiViewport
    /**
     * URL of an uploaded screenshot captured with the annotation.
     * @maxLength 2048
     * @nullable
     */
    screenshot_url?: string | null
    readonly created_at: string
    /** @nullable */
    readonly updated_at: string | null
    readonly created_by: UserBasicApi
}

export interface PaginatedToolbarAnnotationListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: ToolbarAnnotationApi[]
}

/**
 * Structured element metadata (inferred selectors, attributes, component hints).
 */
export type PatchedToolbarAnnotationApiElementContext = { [key: string]: unknown }

/**
 * Viewport size when the annotation was made, as {width, height}.
 * @nullable
 */
export type PatchedToolbarAnnotationApiViewport = {
    /** Viewport width in pixels. */
    width?: number
    /** Viewport height in pixels. */
    height?: number
} | null

export interface PatchedToolbarAnnotationApi {
    readonly id?: string
    /**
     * The annotation note the user wrote about the element.
     * @maxLength 5000
     */
    comment?: string
    /** Lifecycle of the annotation: pending, acknowledged, resolved, or dismissed. Ignored on create.
     *
     * * `pending` - Pending
     * * `acknowledged` - Acknowledged
     * * `resolved` - Resolved
     * * `dismissed` - Dismissed */
    annotation_status?: AnnotationStatusEnumApi
    /**
     * Optional note left by the agent when acknowledging, resolving, or dismissing the annotation.
     * @nullable
     */
    resolution?: string | null
    /**
     * Full URL of the page the annotation was made on.
     * @maxLength 2048
     */
    url?: string
    /**
     * Hostname of the page, used to scope annotations to a site.
     * @maxLength 255
     */
    host?: string
    /**
     * Path portion of the URL.
     * @maxLength 2048
     * @nullable
     */
    pathname?: string | null
    /**
     * CSS selector that locates the annotated element on the page.
     * @maxLength 4096
     */
    selector?: string
    /**
     * Visible text of the annotated element, if any.
     * @maxLength 2048
     * @nullable
     */
    element_text?: string | null
    /**
     * Serialized autocapture-style element chain from the element up to the document root.
     * @maxLength 20000
     * @nullable
     */
    element_chain?: string | null
    /** Structured element metadata (inferred selectors, attributes, component hints). */
    element_context?: PatchedToolbarAnnotationApiElementContext
    /**
     * Viewport size when the annotation was made, as {width, height}.
     * @nullable
     */
    viewport?: PatchedToolbarAnnotationApiViewport
    /**
     * URL of an uploaded screenshot captured with the annotation.
     * @maxLength 2048
     * @nullable
     */
    screenshot_url?: string | null
    readonly created_at?: string
    /** @nullable */
    readonly updated_at?: string | null
    readonly created_by?: UserBasicApi
}

export type ToolbarAnnotationsListParams = {
    /**
     * Filter to annotations in this lifecycle state (e.g. `pending` for unaddressed feedback).
     */
    annotation_status?: ToolbarAnnotationsListAnnotationStatus
    /**
     * Filter to annotations made on this hostname (e.g. `app.example.com`).
     */
    host?: string
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type ToolbarAnnotationsListAnnotationStatus =
    (typeof ToolbarAnnotationsListAnnotationStatus)[keyof typeof ToolbarAnnotationsListAnnotationStatus]

export const ToolbarAnnotationsListAnnotationStatus = {
    Acknowledged: 'acknowledged',
    Dismissed: 'dismissed',
    Pending: 'pending',
    Resolved: 'resolved',
} as const
