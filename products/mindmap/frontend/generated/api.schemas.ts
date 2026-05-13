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
 * * `yellow` - Yellow
 * `pink` - Pink
 * `blue` - Blue
 * `green` - Green
 * `purple` - Purple
 * `orange` - Orange
 * `gray` - Gray
 */
export type ColorEnumApi = (typeof ColorEnumApi)[keyof typeof ColorEnumApi]

export const ColorEnumApi = {
    Yellow: 'yellow',
    Pink: 'pink',
    Blue: 'blue',
    Green: 'green',
    Purple: 'purple',
    Orange: 'orange',
    Gray: 'gray',
} as const

export interface MindMapPostItApi {
    /** Unique short id used as the post-it's API key */
    readonly short_id: string
    /**
     * Short title shown on the post-it
     * @maxLength 256
     */
    title: string
    /** Longer optional body text */
    body?: string
    /** Sticky-note background color

  * `yellow` - Yellow
  * `pink` - Pink
  * `blue` - Blue
  * `green` - Green
  * `purple` - Purple
  * `orange` - Orange
  * `gray` - Gray */
    color?: ColorEnumApi
    /**
     * Optional single emoji
     * @maxLength 8
     */
    emoji?: string
    /** X coordinate on the canvas */
    position_x?: number
    /** Y coordinate on the canvas */
    position_y?: number
    /**
     * Notebook short_id this post-it links to (clicking opens it)
     * @maxLength 12
     * @nullable
     */
    notebook_short_id?: string | null
    readonly created_at: string
    readonly last_modified_at: string
}

export interface _MindMapEdgeRefApi {
    /** Source post-it short_id */
    source: string
    /** Target post-it short_id */
    target: string
}

export interface _MindMapStateApi {
    /** All non-deleted post-its on the team's canvas */
    postits: MindMapPostItApi[]
    /** All directed edges on the canvas */
    edges: _MindMapEdgeRefApi[]
    /** Opaque version hash. Pass via If-None-Match for 304 short-circuit. */
    version: string
}

export interface MindMapEdgeApi {
    /** Edge UUID */
    readonly id: string
    /**
     * Source post-it short_id
     * @maxLength 12
     */
    source: string
    /**
     * Target post-it short_id
     * @maxLength 12
     */
    target: string
    /** When the edge was created */
    readonly created_at: string
}

export interface PaginatedMindMapEdgeListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: MindMapEdgeApi[]
}

export interface PaginatedMindMapPostItListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: MindMapPostItApi[]
}

export interface PatchedMindMapPostItApi {
    /** Unique short id used as the post-it's API key */
    readonly short_id?: string
    /**
     * Short title shown on the post-it
     * @maxLength 256
     */
    title?: string
    /** Longer optional body text */
    body?: string
    /** Sticky-note background color

  * `yellow` - Yellow
  * `pink` - Pink
  * `blue` - Blue
  * `green` - Green
  * `purple` - Purple
  * `orange` - Orange
  * `gray` - Gray */
    color?: ColorEnumApi
    /**
     * Optional single emoji
     * @maxLength 8
     */
    emoji?: string
    /** X coordinate on the canvas */
    position_x?: number
    /** Y coordinate on the canvas */
    position_y?: number
    /**
     * Notebook short_id this post-it links to (clicking opens it)
     * @maxLength 12
     * @nullable
     */
    notebook_short_id?: string | null
    readonly created_at?: string
    readonly last_modified_at?: string
}

export interface _BulkPositionItemApi {
    /**
     * Post-it short_id
     * @maxLength 12
     */
    short_id: string
    /** New X coordinate */
    position_x: number
    /** New Y coordinate */
    position_y: number
}

export interface _BulkPositionRequestApi {
    updates: _BulkPositionItemApi[]
}

export interface _BulkPositionResponseApi {
    /** Number of post-its actually updated */
    updated: number
}

export type MindmapEdgesListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type MindmapPostitsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}
