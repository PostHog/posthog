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
 * Data for the template's Liquid placeholders, available as `variables`. For example `{"reset_link": "https://..."}` fills `{{ variables.reset_link }}`.
 */
export type SendEmailApiMessageData = { [key: string]: unknown }

export interface TransactionalEmailIdentifiersApi {
    /**
     * Distinct ID of the recipient's person. The email's engagement events (sent, delivered, opened, clicked, bounced) and the send itself are recorded against that person. Defaults to the recipient's email address. The template can't read the person's properties, so pass everything it needs in `message_data`.
     * @maxLength 400
     * @nullable
     */
    distinct_id?: string | null
}

export interface TemplateReferenceApi {
    /** Key of the template, as uploaded with `PUT /api/projects/@current/messaging_templates/by_key/{key}/`. Give either `key` or `id`. */
    key?: string
    /** Content hash of the template you hold, as `v1:` and 64 hex characters. When PostHog never published that content, the send answers `template_outdated` and sends nothing. Only with `key`. */
    hash?: string
    /** ID of the template, for templates made in PostHog. Give either `key` or `id`. */
    id?: string
}

export interface SendEmailApi {
    /** Email address of the recipient. */
    to: string
    /** Who the email is for, used to attribute engagement events. */
    identifiers?: TransactionalEmailIdentifiersApi
    /** Data for the template's Liquid placeholders, available as `variables`. For example `{"reset_link": "https://..."}` fills `{{ variables.reset_link }}`. */
    message_data?: SendEmailApiMessageData
    /** The template to send, by key or by id. */
    template: TemplateReferenceApi
}

export interface SendEmailWarningApi {
    /** Stable warning code to branch on, such as `template_superseded`. */
    code: string
    /** What happened. */
    detail: string
    /** What you can change, if the warning is not what you want. */
    fix: string
}

export interface SendEmailResponseApi {
    /** ID of the queued send. Delivery and engagement are reported against the template asynchronously. */
    message_id: string
    /** Things to know about the queued email. Empty in the normal case. */
    warnings: SendEmailWarningApi[]
}

export interface TemplateErrorApi {
    /** Error class, such as `invalid_request`. */
    type: string
    /** Stable error code to branch on, such as `invalid_template_key`. */
    code: string
    /** What went wrong. */
    detail: string
    /**
     * The request field the error is about, if any.
     * @nullable
     */
    attr: string | null
    /** Why PostHog refuses the request. */
    why?: string
    /** What to change before you retry. */
    fix?: string
    /** Documentation for this error code. */
    docs_url?: string
}

/**
 * * `marketing` - Marketing
 * * `transactional` - Transactional
 */
export type MessageCategoryTypeEnumApi = (typeof MessageCategoryTypeEnumApi)[keyof typeof MessageCategoryTypeEnumApi]

export const MessageCategoryTypeEnumApi = {
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
    category_type?: MessageCategoryTypeEnumApi
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
    category_type?: MessageCategoryTypeEnumApi
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
 * * `COMPLAINT` - Complaint
 */
export type SuppressionSourceEnumApi = (typeof SuppressionSourceEnumApi)[keyof typeof SuppressionSourceEnumApi]

export const SuppressionSourceEnumApi = {
    Bounce: 'BOUNCE',
    Manual: 'MANUAL',
    Complaint: 'COMPLAINT',
} as const

export interface MessageSuppressionApi {
    /** Server-assigned UUID for this suppression entry. */
    readonly id: string
    /** Normalized recipient email address. Suppression is keyed on this value, per team. */
    readonly identifier: string
    /** How the entry landed on the list: `BOUNCE` for automatic (bounce-driven), `COMPLAINT` for automatic (the recipient reported a message as spam), `MANUAL` for user-added via the UI/API.
     *
     * * `BOUNCE` - Bounce
     * * `MANUAL` - Manual
     * * `COMPLAINT` - Complaint */
    readonly source: SuppressionSourceEnumApi
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
    /** Inbox preview text shown after the subject. Supports Liquid templating. */
    preheader?: string
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

/**
 * * `gui` - GUI
 * * `code` - Code
 */
export type TemplateManagedByEnumApi = (typeof TemplateManagedByEnumApi)[keyof typeof TemplateManagedByEnumApi]

export const TemplateManagedByEnumApi = {
    Gui: 'gui',
    Code: 'code',
} as const

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
    /**
     * The workflow that sends this template over the transactional email API. Null until the template is made transactional. Each content save writes a new version of it.
     * @nullable
     */
    readonly transactional_hog_flow_id: string | null
    /**
     * Stable identifier code uses to upload and send this template, unique within the project. Null for templates that have no key. Set once, by the first upload or by a PATCH whose only field is `key`.
     * @nullable
     */
    readonly key: string | null
    /** Who owns the content. `code` when it was uploaded from a repository: PostHog then refuses edits, and the template changes through its next upload. To edit it in PostHog, send a PATCH whose only field is `managed_by` set to `gui`. `gui` or null when it is edited in PostHog.
     *
     * * `gui` - GUI
     * * `code` - Code */
    readonly managed_by: TemplateManagedByEnumApi | null
    /**
     * Repository the template was last uploaded from, such as `github.com/example/app`.
     * @nullable
     */
    readonly source_repository: string | null
    /**
     * Path of the template file in the source repository.
     * @nullable
     */
    readonly source_path: string | null
    /**
     * Commit or branch the template was last uploaded from.
     * @nullable
     */
    readonly source_ref: string | null
    /**
     * Hash of the published subject, preheader, HTML and text, as `v1:` and 64 hex characters. Changes with every save that changes them.
     * @nullable
     */
    readonly content_hash: string | null
}

export interface PaginatedMessageTemplateListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: MessageTemplateApi[]
}

export interface PatchedMessageTemplateUpdateApi {
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
    /**
     * The workflow that sends this template over the transactional email API. Null until the template is made transactional. Each content save writes a new version of it.
     * @nullable
     */
    readonly transactional_hog_flow_id?: string | null
    /**
     * Give a template that has no key one, so code can take it over: the next upload under this key updates this template and keeps its id, workflow and sender. Send it as the only field of the PATCH. Letters, digits, hyphens (-) and underscores (_). Set once: a template that has a key keeps it.
     * @maxLength 400
     */
    key?: string
    /** Who owns the content. `code` when it was uploaded from a repository: PostHog then refuses edits, and the template changes through its next upload. To edit it in PostHog, send a PATCH whose only field is `managed_by` set to `gui`. `gui` or null when it is edited in PostHog.
     *
     * * `gui` - GUI
     * * `code` - Code */
    readonly managed_by?: TemplateManagedByEnumApi | null
    /**
     * Repository the template was last uploaded from, such as `github.com/example/app`.
     * @nullable
     */
    readonly source_repository?: string | null
    /**
     * Path of the template file in the source repository.
     * @nullable
     */
    readonly source_path?: string | null
    /**
     * Commit or branch the template was last uploaded from.
     * @nullable
     */
    readonly source_ref?: string | null
    /**
     * Hash of the published subject, preheader, HTML and text, as `v1:` and 64 hex characters. Changes with every save that changes them.
     * @nullable
     */
    readonly content_hash?: string | null
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

export interface MakeTransactionalApi {
    /**
     * ID of the verified email sender integration the email is sent from. Defaults to the project's default sender.
     * @nullable
     */
    from_integration_id?: number | null
}

/**
 * Data for the template's Liquid placeholders, available as `variables`. For example `{"reset_link": "https://..."}` fills `{{ variables.reset_link }}`.
 */
export type SendTransactionalEmailApiMessageData = { [key: string]: unknown }

export interface SendTransactionalEmailApi {
    /** Email address of the recipient. */
    to: string
    /** Who the email is for, used to attribute engagement events. */
    identifiers?: TransactionalEmailIdentifiersApi
    /** Data for the template's Liquid placeholders, available as `variables`. For example `{"reset_link": "https://..."}` fills `{{ variables.reset_link }}`. */
    message_data?: SendTransactionalEmailApiMessageData
}

export interface SendTransactionalEmailResponseApi {
    /** ID of the queued send. Delivery and engagement are reported against the template asynchronously. */
    message_id: string
}

export interface TemplateSourceApi {
    /**
     * Host and path of the repository the file is in, such as `github.com/example/app`.
     * @maxLength 400
     * @nullable
     */
    repository?: string | null
    /**
     * Path of the template file in the repository, such as `emails/welcome.html`.
     * @maxLength 400
     * @nullable
     */
    path?: string | null
    /**
     * Commit or branch the file was uploaded from.
     * @maxLength 400
     * @nullable
     */
    ref?: string | null
}

export interface UploadTemplateApi {
    /**
     * Template name shown in the template library.
     * @maxLength 400
     */
    name: string
    /** Email subject line. Supports Liquid, such as `{{ variables.first_name }}`. */
    subject: string
    /** Email body as HTML, stored as sent. Supports Liquid, such as `{{ variables.first_name }}`. */
    html: string
    /** Plain-text body for email clients that can't show HTML. Leaving it out removes the stored one. */
    text?: string
    /** Inbox preview text shown after the subject. Leaving it out removes the stored one. */
    preheader?: string
    /** Where the template file lives, so people in PostHog can find it. Leaving it out, or a part of it, keeps what is stored. */
    source?: TemplateSourceApi
    /** Set it on uploads a program makes on its own, such as after a send answered `template_outdated`. When newer content already replaced this content, the upload changes nothing and answers `superseded`. Leave it out to publish the content in any case, such as to roll back to earlier content. */
    if_not_superseded?: boolean
}

/**
 * * `created` - Created
 * * `updated` - Updated
 * * `unchanged` - Unchanged
 * * `superseded` - Superseded
 */
export type TemplateUploadResultEnumApi = (typeof TemplateUploadResultEnumApi)[keyof typeof TemplateUploadResultEnumApi]

export const TemplateUploadResultEnumApi = {
    Created: 'created',
    Updated: 'updated',
    Unchanged: 'unchanged',
    Superseded: 'superseded',
} as const

export interface UploadTemplateResponseApi {
    /** ID of the template. */
    id: string
    /** Key of the template. */
    key: string
    /** `created`: the upload made a new template. `updated`: it published the uploaded content. `unchanged`: the template already had this content, so nothing was published. `superseded`: the upload set `if_not_superseded` and newer content already replaced this content, so nothing was published.
     *
     * * `created` - Created
     * * `updated` - Updated
     * * `unchanged` - Unchanged
     * * `superseded` - Superseded */
    result: TemplateUploadResultEnumApi
    /** Hash of the published content, as `v1:` and 64 hex characters. Send it with an email to check PostHog holds the content you hold. After `superseded` it is the hash of the newer content. */
    content_hash: string
    /** `code` after every upload except `superseded`, which changes nothing.
     *
     * * `gui` - GUI
     * * `code` - Code */
    managed_by: TemplateManagedByEnumApi
    /** Where the template file lives, as stored after the upload. */
    source: TemplateSourceApi
    /** The workflow that sends this template. Each upload that changes the content writes a new version of it. */
    transactional_hog_flow_id: string
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
