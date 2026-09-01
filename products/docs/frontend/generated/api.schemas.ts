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
 * Who did something, as much of a person as a doc surface needs.
 */
export interface DocPersonApi {
    /** Numeric id of the person. */
    id: number
    /** Stable id of the person. */
    uuid: string
    /** First name. */
    first_name: string
    /** Last name. */
    last_name: string
    /** Email address. */
    email: string
}

/**
 * A number the space watches. The value is read from the insight, not stored here.
 */
export interface SpaceKpiApi {
    /** Unique id of the number. */
    id: string
    /** The space (channel) that watches this number. */
    channel_id: string
    /** Label shown above the number. */
    name: string
    /** Short id of the saved insight the value comes from. */
    insight_short_id: string
    /** Order in the space's number grid, lowest first. */
    position: number
    /** The person who added the number. */
    created_by: DocPersonApi | null
    /** When it was added. */
    created_at: string
}

/**
 * What a new number needs.
 */
export interface SpaceKpiCreateApi {
    /** The space (channel) that watches this number. */
    channel: string
    /**
     * Label shown above the number.
     * @maxLength 200
     */
    name: string
    /**
     * Short id of the saved insight the value comes from.
     * @maxLength 32
     */
    insight_short_id: string
}

/**
 * * `draft` - draft
 * * `active` - active
 * * `done` - done
 */
export type DocStatusEnumApi = (typeof DocStatusEnumApi)[keyof typeof DocStatusEnumApi]

export const DocStatusEnumApi = {
    Draft: 'draft',
    Active: 'active',
    Done: 'done',
} as const

/**
 * A doc without its body. Used for the tab row and the space home list.
 */
export interface DocSummaryApi {
    /** Unique id of the doc. */
    id: string
    /** The space (channel) the doc belongs to. */
    channel_id: string
    /** Title of the doc, shown on its tab. */
    title: string
    /** Where the doc is in its life: draft while it is being written, active once the space works from it, done when it is finished.
     *
     * * `draft` - draft
     * * `active` - active
     * * `done` - done */
    status: DocStatusEnumApi
    /** Order of the doc in the space's tab row, lowest first. */
    position: number
    /** Collab version of the stored body. Increases by one for every accepted step. */
    version: number
    /** The person who created the doc. */
    created_by: DocPersonApi | null
    /** When the doc was created. */
    created_at: string
    /** When the doc was last written to. */
    updated_at: string
}

/**
 * * `blank` - blank
 * * `notes` - notes
 */
export type TemplateEnumApi = (typeof TemplateEnumApi)[keyof typeof TemplateEnumApi]

export const TemplateEnumApi = {
    Blank: 'blank',
    Notes: 'notes',
} as const

/**
 * What a new doc needs.
 */
export interface DocCreateApi {
    /** The space (channel) the doc belongs to. */
    channel: string
    /**
     * Title of the doc. Defaults to the template name.
     * @maxLength 400
     */
    title?: string
    /** Starting content: 'blank' is an empty page, 'notes' has headings for notes from a call.
     *
     * * `blank` - blank
     * * `notes` - notes */
    template?: TemplateEnumApi
}

/**
 * The doc body as a ProseMirror document.
 * @nullable
 */
export type DocApiContent = { [key: string]: unknown } | null

/**
 * A doc with its body.
 */
export interface DocApi {
    /** Unique id of the doc. */
    id: string
    /** The space (channel) the doc belongs to. */
    channel_id: string
    /** Title of the doc, shown on its tab. */
    title: string
    /** Where the doc is in its life: draft while it is being written, active once the space works from it, done when it is finished.
     *
     * * `draft` - draft
     * * `active` - active
     * * `done` - done */
    status: DocStatusEnumApi
    /** Order of the doc in the space's tab row, lowest first. */
    position: number
    /** Collab version of the stored body. Increases by one for every accepted step. */
    version: number
    /** The person who created the doc. */
    created_by: DocPersonApi | null
    /** When the doc was created. */
    created_at: string
    /** When the doc was last written to. */
    updated_at: string
    /**
     * The doc body as a ProseMirror document.
     * @nullable
     */
    content: DocApiContent
    /** Plain-text mirror of the body, written on every save. */
    text_content: string
}

/**
 * The parts of a doc a person can change outside the editor.
 */
export interface PatchedDocUpdateApi {
    /**
     * New title for the doc.
     * @maxLength 400
     */
    title?: string
    /** Where the doc is in its life: draft while it is being written, active once the space works from it, done when it is finished.
     *
     * * `draft` - draft
     * * `active` - active
     * * `done` - done */
    status?: DocStatusEnumApi
}

/**
 * A caret ping, broadcast to everyone else in the doc.
 */
export interface DocPresenceApi {
    /**
     * Id of the editing client, unique per open tab.
     * @maxLength 64
     */
    client_id: string
    /** The collab version the caret position is relative to. */
    version: number
    /** Caret position as {'anchor': int, 'head': int}. */
    cursor: unknown
}

/**
 * The whole document after the steps are applied.
 */
export type DocCollabSaveApiContent = { [key: string]: unknown }

/**
 * One batch of prosemirror-collab steps, with the document they produce.
 */
export interface DocCollabSaveApi {
    /**
     * Id of the editing client, unique per open tab.
     * @maxLength 64
     */
    client_id: string
    /** The steps to append, in order. */
    steps: unknown[]
    /** The collab version the submitted steps are based on. */
    version: number
    /** The whole document after the steps are applied. */
    content: DocCollabSaveApiContent
    /** Plain-text mirror of the body. */
    text_content?: string
    /**
     * Title to store with this save.
     * @maxLength 400
     */
    title?: string
    /**
     * The caller's caret position, broadcast with the steps.
     * @nullable
     */
    cursor_head?: number | null
}

/**
 * * `conflict` - conflict
 * * `stale` - stale
 */
export type DocCollabConflictCodeEnumApi =
    (typeof DocCollabConflictCodeEnumApi)[keyof typeof DocCollabConflictCodeEnumApi]

export const DocCollabConflictCodeEnumApi = {
    Conflict: 'conflict',
    Stale: 'stale',
} as const

/**
 * The save was rejected because other steps landed first.
 */
export interface DocCollabConflictApi {
    /** 'conflict' means the missed steps are included. 'stale' means the client must reload the doc.
     *
     * * `conflict` - conflict
     * * `stale` - stale */
    code: DocCollabConflictCodeEnumApi
    /** The steps the client missed, in order. */
    steps?: unknown[]
    /** Authors of the missed steps, index-aligned with 'steps'. */
    client_ids?: string[]
    /** The current collab version of the doc. */
    version: number
}

/**
 * One message in a discussion.
 */
export interface DiscussionPostApi {
    /** Unique id of the message. */
    id: string
    /** What the person wrote. */
    content: string
    /** The person who wrote it. */
    created_by: DocPersonApi | null
    /** When it was written. */
    created_at: string
}

/**
 * A discussion anchored to a phrase in the doc, with its replies.
 */
export interface DiscussionThreadApi {
    /** Unique id of the message. */
    id: string
    /** What the person wrote. */
    content: string
    /** The person who wrote it. */
    created_by: DocPersonApi | null
    /** When it was written. */
    created_at: string
    /** Key that ties this thread to a mark in the doc body. */
    anchor_key: string
    /** The phrase the thread was started from. */
    anchor_text: string
    /** Whether the thread is marked as handled. */
    resolved: boolean
    /** Replies, oldest first. */
    replies: DiscussionPostApi[]
}

/**
 * What a new discussion needs.
 */
export interface DiscussionCreateApi {
    /** The first message. */
    content: string
    /**
     * Key the client also writes onto the mark around the selected phrase.
     * @maxLength 64
     */
    anchor_key: string
    /**
     * The selected phrase, quoted in the panel.
     * @maxLength 280
     */
    anchor_text: string
}

/**
 * A reply to an existing discussion.
 */
export interface DiscussionReplyApi {
    /** What to add to the thread. */
    content: string
}

/**
 * Mark a discussion handled, or bring it back.
 */
export interface DiscussionResolveApi {
    /** True marks the thread handled, false reopens it. */
    resolved: boolean
}

/**
 * Everything the space home view renders in one call.
 */
export interface SpaceHomeApi {
    /** Docs in this space, in tab order. */
    docs: DocSummaryApi[]
    /** Numbers this space watches, in grid order. */
    kpis: SpaceKpiApi[]
}

/**
 * The new left-to-right order of a space's tabs.
 */
export interface DocReorderApi {
    /** The space (channel) whose docs are being reordered. */
    channel: string
    /** Doc ids in their new order. Ids that are not in this space are ignored. */
    doc_ids: string[]
}

export interface DocsSearchRequestApi {
    /** Natural-language description of what to find in the PostHog documentation. Inkeep performs hybrid (semantic + full-text) RAG, so phrase the query the way a user would ask the question. */
    query: string
}

export interface DocsSearchResponseApi {
    /** Markdown-formatted documentation results. Each block has a title, URL and excerpt; an empty result set returns guidance to navigate to https://posthog.com/docs. */
    content: string
}

export type DocKpisListParams = {
    /**
     * Only return rows in this space (channel).
     */
    channel?: string
}

export type DocsListParams = {
    /**
     * Only return rows in this space (channel).
     */
    channel?: string
}

export type DocsHomeRetrieveParams = {
    /**
     * Only return rows in this space (channel).
     */
    channel?: string
}
