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
 * * `marketing` - Marketing
 * * `transactional` - Transactional
 */
export type CategoryTypeEnumApi = (typeof CategoryTypeEnumApi)[keyof typeof CategoryTypeEnumApi]

export const CategoryTypeEnumApi = {
    Marketing: 'marketing',
    Transactional: 'transactional',
} as const

export interface MessageCategoryApi {
    readonly id: string
    /** @maxLength 64 */
    key: string
    /** @maxLength 128 */
    name: string
    description?: string
    public_description?: string
    category_type?: CategoryTypeEnumApi
    readonly created_at: string
    readonly updated_at: string
    /** @nullable */
    readonly created_by: number | null
    deleted?: boolean
}

export interface PaginatedMessageCategoryListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: MessageCategoryApi[]
}

export interface PatchedMessageCategoryApi {
    readonly id?: string
    /** @maxLength 64 */
    key?: string
    /** @maxLength 128 */
    name?: string
    description?: string
    public_description?: string
    category_type?: CategoryTypeEnumApi
    readonly created_at?: string
    readonly updated_at?: string
    /** @nullable */
    readonly created_by?: number | null
    deleted?: boolean
}

export interface AddOptOutRequestApi {
    /**
     * The recipient identifier to opt out (e.g. email address).
     * @maxLength 512
     */
    identifier: string
    /** Optional message category key. If omitted, the recipient is opted out of all marketing messages. */
    category_key?: string
}

export interface MessagePreferencesApi {
    /** Server-assigned UUID for this recipient's preference record. */
    readonly id: string
    /** The recipient identifier (e.g. email address). */
    identifier: string
    /** When the preference was last updated. */
    updated_at: string
    /** Map of category ID to preference status (`OPTED_IN`, `OPTED_OUT` or `NO_PREFERENCE`). The reserved `$all` key covers every marketing message. */
    preferences: unknown
}

export interface BulkOptOutEntryApi {
    /**
     * The recipient identifier to opt out (e.g. email address).
     * @maxLength 512
     */
    identifier: string
    /** Message category key for this recipient. Overrides the request-level category_key. */
    category_key?: string
}

export interface BulkAddOptOutsRequestApi {
    /** Recipients to opt out, at most 1000 per request. */
    opt_outs: BulkOptOutEntryApi[]
    /** Message category key applied to entries without their own. If omitted, recipients are opted out of all marketing messages. */
    category_key?: string
}

export interface BulkAddOptOutsResultApi {
    /** Number of opt-out entries received. */
    total: number
    /** Number of recipient and category pairs recorded as opted out. */
    opted_out: number
    /** Number of entries skipped because their category_key doesn't exist. */
    skipped: number
    /** The first few entry-level problems, so the caller can fix their list. */
    errors: string[]
}

export interface MessagingErrorApi {
    /** Human-readable description of what went wrong. */
    error: string
}

export interface GenerateLinkRequestApi {
    /**
     * Recipient to generate the link for. Defaults to the requesting user's own email address.
     * @maxLength 512
     */
    recipient?: string
}

export interface PreferencesLinkApi {
    /** Token-gated URL where the recipient can manage their preferences. */
    preferences_url: string
}

/**
 * OpenAPI shape for the paginated opt-outs response, so the generated clients get the
 * {count, next, previous, results} envelope instead of an untyped object.
 */
export interface PaginatedOptOutsApi {
    /** Total number of opted-out recipients for the category. */
    count: number
    /**
     * URL for the next page, or null on the last page.
     * @nullable
     */
    next: string | null
    /**
     * URL for the previous page, or null on the first page.
     * @nullable
     */
    previous: string | null
    results: MessagePreferencesApi[]
}

export interface RemoveOptOutRequestApi {
    /**
     * The recipient identifier to opt back in (e.g. email address).
     * @maxLength 512
     */
    identifier: string
    /** Optional message category key. If omitted, the recipient is opted back in to all marketing messages. */
    category_key?: string
}

export interface WebhookUrlApi {
    /** URL to register in Customer.io so it posts subscription changes to PostHog. */
    url: string
}

export interface AddSuppressionRequestApi {
    /**
     * The email address to suppress. Will not receive any messages until removed.
     * @maxLength 512
     */
    identifier: string
}

/**
 * * `BOUNCE` - Bounce
 * * `MANUAL` - Manual
 */
export type MessageSuppressionSourceEnumApi =
    (typeof MessageSuppressionSourceEnumApi)[keyof typeof MessageSuppressionSourceEnumApi]

export const MessageSuppressionSourceEnumApi = {
    Bounce: 'BOUNCE',
    Manual: 'MANUAL',
} as const

export interface MessageSuppressionApi {
    /** Server-assigned UUID for this suppression entry. */
    readonly id: string
    /** Normalized recipient email address. Suppression is keyed on this value, per team. */
    readonly identifier: string
    /** How the entry landed on the list: `BOUNCE` for automatic (bounce-driven), `MANUAL` for user-added via the UI/API.
     *
     * * `BOUNCE` - Bounce
     * * `MANUAL` - Manual */
    readonly source: MessageSuppressionSourceEnumApi
    /**
     * Human-readable reason for the suppression (e.g. 'Auto-suppressed after 5 consecutive soft bounces').
     * @nullable
     */
    readonly reason: string | null
    /** Rolling count of consecutive soft bounces with no successful delivery in between. Reset to 0 on any successful delivery. Ignored for MANUAL entries. */
    readonly transient_bounce_count: number
    /**
     * Timestamp of the most recent bounce, if any.
     * @nullable
     */
    readonly last_bounce_at: string | null
    /**
     * SMTP diagnostic string from the most recent bounce (e.g. '550 5.1.1 user unknown'), kept for visibility.
     * @nullable
     */
    readonly last_bounce_diagnostic: string | null
    /** Whether the address is actively suppressed. A BOUNCE row can exist while still only counting bounces (suppressed=false) before it crosses the threshold. */
    readonly suppressed: boolean
    /**
     * Timestamp when the address was first suppressed.
     * @nullable
     */
    readonly suppressed_at: string | null
    /** When the row was first created (first bounce or manual add). */
    readonly created_at: string
    /** When the row was last touched by any write. */
    readonly updated_at: string
}

/**
 * OpenAPI shape for the paginated suppressions response. Declared so drf-spectacular emits
 * the {count, next, previous, results} envelope on the generated client, rather than a bare
 * array — which the frontend actually receives at runtime.
 */
export interface PaginatedMessageSuppressionApi {
    /** Total number of suppressed recipients for the team. */
    count: number
    /**
     * URL for the next page, or null on the last page.
     * @nullable
     */
    next: string | null
    /**
     * URL for the previous page, or null on the first page.
     * @nullable
     */
    previous: string | null
    results: MessageSuppressionApi[]
}

/**
 * * `liquid` - liquid
 */
export type MessageTemplateContentTemplatingEnumApi =
    (typeof MessageTemplateContentTemplatingEnumApi)[keyof typeof MessageTemplateContentTemplatingEnumApi]

export const MessageTemplateContentTemplatingEnumApi = {
    Liquid: 'liquid',
} as const

/**
 * Highest htmlID suffix per element type, e.g. {"u_row": 1, "u_content_text": 2}.
 */
export type EmailTemplateApiDesignCounters = { [key: string]: unknown }

export type EmailTemplateApiDesignBodyRowsItem = { [key: string]: unknown }

export type EmailTemplateApiDesignBodyHeadersItem = { [key: string]: unknown }

export type EmailTemplateApiDesignBodyFootersItem = { [key: string]: unknown }

/**
 * Body-level settings: backgroundColor, contentWidth ('600px'), fontFamily, textColor.
 */
export type EmailTemplateApiDesignBodyValues = { [key: string]: unknown }

export type EmailTemplateApiDesignBody = {
    /** Any unique string. */
    id?: string
    /** Rows of {id, cells, columns[{id, contents[{id, type, values}], values}], values}. */
    rows: EmailTemplateApiDesignBodyRowsItem[]
    headers?: EmailTemplateApiDesignBodyHeadersItem[]
    footers?: EmailTemplateApiDesignBodyFootersItem[]
    /** Body-level settings: backgroundColor, contentWidth ('600px'), fontFamily, textColor. */
    values?: EmailTemplateApiDesignBodyValues
}

/**
 * Design JSON for PostHog's visual email editor — the authoring surface and source of truth. The server renders the sent email from it, and it opens as editable blocks in the editor. Full schema in the designing-email-templates skill.
 */
export type EmailTemplateApiDesign = {
    /** Highest htmlID suffix per element type, e.g. {"u_row": 1, "u_content_text": 2}. */
    counters?: EmailTemplateApiDesignCounters
    /** Design schema version, e.g. 16. */
    schemaVersion: number
    body: EmailTemplateApiDesignBody
}

export interface EmailTemplateApi {
    /** Email subject line. Supports Liquid templating. Required for email-type templates. */
    subject?: string
    /** Plain-text fallback body for clients that can't render the email. */
    text?: string
    /** Rendered email body — derived from the design at save time. The visual editor's save path supplies it directly; omit it otherwise. */
    html?: string
    /** Design JSON for PostHog's visual email editor — the authoring surface and source of truth. The server renders the sent email from it, and it opens as editable blocks in the editor. Full schema in the designing-email-templates skill. */
    design?: EmailTemplateApiDesign
}

export interface MessageTemplateContentApi {
    /** Templating language for the email content. Always 'liquid' — Liquid tags pass through verbatim.
     *
     * * `liquid` - liquid */
    templating?: MessageTemplateContentTemplatingEnumApi
    /** Email message content. Replaced as a whole on update — send the complete object. */
    email?: EmailTemplateApi | null
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

export interface MessageTemplateApi {
    readonly id: string
    /**
     * Human-readable template name shown in the library.
     * @maxLength 400
     */
    name: string
    /** What the template is for and when to use it. */
    description?: string
    readonly created_at: string
    readonly updated_at: string
    /** Template content keyed by channel. Replaced as a whole on update, not merged. */
    content?: MessageTemplateContentApi
    readonly created_by: UserBasicApi
    /**
     * Message channel of the template. Currently 'email'.
     * @maxLength 24
     */
    type?: string
    /**
     * Message category ID to file the template under. Must belong to the same project.
     * @nullable
     */
    message_category?: string | null
    /** Soft-delete flag. Set true to remove the template from the library. */
    deleted?: boolean
}

export interface PaginatedMessageTemplateListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: MessageTemplateApi[]
}

export interface PatchedMessageTemplateApi {
    readonly id?: string
    /**
     * Human-readable template name shown in the library.
     * @maxLength 400
     */
    name?: string
    /** What the template is for and when to use it. */
    description?: string
    readonly created_at?: string
    readonly updated_at?: string
    /** Template content keyed by channel. Replaced as a whole on update, not merged. */
    content?: MessageTemplateContentApi
    readonly created_by?: UserBasicApi
    /**
     * Message channel of the template. Currently 'email'.
     * @maxLength 24
     */
    type?: string
    /**
     * Message category ID to file the template under. Must belong to the same project.
     * @nullable
     */
    message_category?: string | null
    /** Soft-delete flag. Set true to remove the template from the library. */
    deleted?: boolean
}

/**
 * * `update_content` - update_content
 * * `update_column` - update_column
 * * `update_row` - update_row
 * * `update_body` - update_body
 * * `add_content` - add_content
 * * `remove_content` - remove_content
 * * `move_content` - move_content
 * * `add_row` - add_row
 * * `remove_row` - remove_row
 */
export type EmailTemplateDesignOperationEnumApi =
    (typeof EmailTemplateDesignOperationEnumApi)[keyof typeof EmailTemplateDesignOperationEnumApi]

export const EmailTemplateDesignOperationEnumApi = {
    UpdateContent: 'update_content',
    UpdateColumn: 'update_column',
    UpdateRow: 'update_row',
    UpdateBody: 'update_body',
    AddContent: 'add_content',
    RemoveContent: 'remove_content',
    MoveContent: 'move_content',
    AddRow: 'add_row',
    RemoveRow: 'remove_row',
} as const

export interface DesignOperationApi {
    /** Design edit. update_content {id, patch}: deep-merge patch into the content block's fields (a null leaf deletes that key) — the surgical path, e.g. change just values.text. update_row / update_column {id, patch} and update_body {patch}: same deep-merge for row/column/body-level settings. add_content {column_id, content, index?}: insert a content block into a column (id and Unlayer numbering are filled in for you). remove_content {id} / move_content {id, column_id, index?}: delete or relocate a block. add_row {row, index?} / remove_row {id}: add or delete a row.
     *
     * * `update_content` - update_content
     * * `update_column` - update_column
     * * `update_row` - update_row
     * * `update_body` - update_body
     * * `add_content` - add_content
     * * `remove_content` - remove_content
     * * `move_content` - move_content
     * * `add_row` - add_row
     * * `remove_row` - remove_row */
    op: EmailTemplateDesignOperationEnumApi
    /** Target node id. Required for update_content/column/row, remove_content, remove_row, move_content. */
    id?: string
    /** Target column id. Required for add_content and move_content. */
    column_id?: string
    /** update_* only. Partial fields deep-merged into the existing node; a null leaf deletes that key. e.g. {values: {text: '<p>Hi</p>'}} changes only the block's text. */
    patch?: unknown
    /** add_content only. A content block {type, values: {...}}; omit id and values._meta — they're assigned server-side. type is one of text, heading, button, image, divider, html, etc. */
    content?: unknown
    /** add_row only. A full row {cells, columns: [{contents: [...], values}], values}; ids and Unlayer numbering are assigned server-side for the row and everything nested in it. */
    row?: unknown
    /** add_*\/move_content only. 0-based insert position; omit to append to the end. */
    index?: number
}

export interface PatchedDesignPatchApi {
    /** Ordered edits applied atomically to a template's Unlayer design: the stored design is read, the ops are applied in order, the result is validated and re-rendered to HTML, and it's saved only if valid — otherwise the template is unchanged. Reference blocks by id so you never resend the whole design. */
    operations?: DesignOperationApi[]
}

export type MessagingCategoriesListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type MessagingPreferencesExportOptOutsCsvRetrieveParams = {
    /**
     * Message category key to export. If omitted, exports recipients opted out of all marketing messages.
     */
    category_key?: string
}

export type MessagingPreferencesOptOutsRetrieveParams = {
    /**
     * Message category key to list opt-outs for. If omitted, lists recipients opted out of all marketing messages.
     */
    category_key?: string
    page?: number
    page_size?: number
    /**
     * Case-insensitive substring match on the recipient identifier.
     * @maxLength 512
     */
    search?: string
}

export type MessagingSuppressionsSuppressionsRetrieveParams = {
    page?: number
    page_size?: number
    /**
     * Case-insensitive substring match on the recipient email address.
     * @maxLength 512
     */
    search?: string
}

export type MessagingTemplatesListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}
