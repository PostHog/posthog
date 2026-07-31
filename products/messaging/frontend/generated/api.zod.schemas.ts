/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import { z as zod } from 'zod'

export const CategoryTypeEnumApi = zod
    .enum(['marketing', 'transactional'])
    .describe('\* `marketing` - Marketing\n\* `transactional` - Transactional')

export type CategoryTypeEnumApi = zod.input<typeof CategoryTypeEnumApi>
export type CategoryTypeEnumApiOutput = zod.output<typeof CategoryTypeEnumApi>

export const messageCategoryApiKeyMax = 64

export const messageCategoryApiNameMax = 128

export const MessageCategoryApi = zod.object({
    id: zod.uuid(),
    key: zod.string().max(messageCategoryApiKeyMax),
    name: zod.string().max(messageCategoryApiNameMax),
    description: zod.string().optional(),
    public_description: zod.string().optional(),
    category_type: CategoryTypeEnumApi.optional(),
    created_at: zod.iso.datetime({ offset: true }),
    updated_at: zod.iso.datetime({ offset: true }),
    created_by: zod.number().nullable(),
    deleted: zod.boolean().optional(),
})

export type MessageCategoryApi = zod.input<typeof MessageCategoryApi>
export type MessageCategoryApiOutput = zod.output<typeof MessageCategoryApi>

export const PaginatedMessageCategoryListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(MessageCategoryApi),
})

export type PaginatedMessageCategoryListApi = zod.input<typeof PaginatedMessageCategoryListApi>
export type PaginatedMessageCategoryListApiOutput = zod.output<typeof PaginatedMessageCategoryListApi>

export const patchedMessageCategoryApiKeyMax = 64

export const patchedMessageCategoryApiNameMax = 128

export const PatchedMessageCategoryApi = zod.object({
    id: zod.uuid().optional(),
    key: zod.string().max(patchedMessageCategoryApiKeyMax).optional(),
    name: zod.string().max(patchedMessageCategoryApiNameMax).optional(),
    description: zod.string().optional(),
    public_description: zod.string().optional(),
    category_type: CategoryTypeEnumApi.optional(),
    created_at: zod.iso.datetime({ offset: true }).optional(),
    updated_at: zod.iso.datetime({ offset: true }).optional(),
    created_by: zod.number().nullish(),
    deleted: zod.boolean().optional(),
})

export type PatchedMessageCategoryApi = zod.input<typeof PatchedMessageCategoryApi>
export type PatchedMessageCategoryApiOutput = zod.output<typeof PatchedMessageCategoryApi>

export const addOptOutRequestApiIdentifierMax = 512

export const AddOptOutRequestApi = zod.object({
    identifier: zod
        .string()
        .max(addOptOutRequestApiIdentifierMax)
        .describe('The recipient identifier to opt out (e.g. email address).'),
    category_key: zod
        .string()
        .optional()
        .describe('Optional message category key. If omitted, the recipient is opted out of all marketing messages.'),
})

export type AddOptOutRequestApi = zod.input<typeof AddOptOutRequestApi>
export type AddOptOutRequestApiOutput = zod.output<typeof AddOptOutRequestApi>

export const MessagePreferencesApi = zod.object({
    id: zod.uuid(),
    identifier: zod.string().describe('The recipient identifier (e.g. email address).'),
    updated_at: zod.iso.datetime({ offset: true }).describe('When the preference was last updated.'),
    preferences: zod.unknown().describe('Map of category ID to preference status.'),
})

export type MessagePreferencesApi = zod.input<typeof MessagePreferencesApi>
export type MessagePreferencesApiOutput = zod.output<typeof MessagePreferencesApi>

export const addSuppressionRequestApiIdentifierMax = 512

export const AddSuppressionRequestApi = zod.object({
    identifier: zod
        .string()
        .max(addSuppressionRequestApiIdentifierMax)
        .describe('The email address to suppress. Will not receive any messages until removed.'),
})

export type AddSuppressionRequestApi = zod.input<typeof AddSuppressionRequestApi>
export type AddSuppressionRequestApiOutput = zod.output<typeof AddSuppressionRequestApi>

export const MessageSuppressionSourceEnumApi = zod
    .enum(['BOUNCE', 'MANUAL'])
    .describe('\* `BOUNCE` - Bounce\n\* `MANUAL` - Manual')

export type MessageSuppressionSourceEnumApi = zod.input<typeof MessageSuppressionSourceEnumApi>
export type MessageSuppressionSourceEnumApiOutput = zod.output<typeof MessageSuppressionSourceEnumApi>

export const MessageSuppressionApi = zod.object({
    id: zod.uuid().describe('Server-assigned UUID for this suppression entry.'),
    identifier: zod
        .string()
        .describe('Normalized recipient email address. Suppression is keyed on this value, per team.'),
    source: MessageSuppressionSourceEnumApi.describe(
        'How the entry landed on the list: `BOUNCE` for automatic (bounce-driven), `MANUAL` for user-added via the UI\/API.\n\n\* `BOUNCE` - Bounce\n\* `MANUAL` - Manual'
    ),
    reason: zod
        .string()
        .nullable()
        .describe(
            "Human-readable reason for the suppression (e.g. 'Auto-suppressed after 5 consecutive soft bounces')."
        ),
    transient_bounce_count: zod
        .number()
        .describe(
            'Rolling count of consecutive soft bounces with no successful delivery in between. Reset to 0 on any successful delivery. Ignored for MANUAL entries.'
        ),
    last_bounce_at: zod.iso
        .datetime({ offset: true })
        .nullable()
        .describe('Timestamp of the most recent bounce, if any.'),
    last_bounce_diagnostic: zod
        .string()
        .nullable()
        .describe(
            "SMTP diagnostic string from the most recent bounce (e.g. '550 5.1.1 user unknown'), kept for visibility."
        ),
    suppressed: zod
        .boolean()
        .describe(
            'Whether the address is actively suppressed. A BOUNCE row can exist while still only counting bounces (suppressed=false) before it crosses the threshold.'
        ),
    suppressed_at: zod.iso
        .datetime({ offset: true })
        .nullable()
        .describe('Timestamp when the address was first suppressed.'),
    created_at: zod.iso
        .datetime({ offset: true })
        .describe('When the row was first created (first bounce or manual add).'),
    updated_at: zod.iso.datetime({ offset: true }).describe('When the row was last touched by any write.'),
})

export type MessageSuppressionApi = zod.input<typeof MessageSuppressionApi>
export type MessageSuppressionApiOutput = zod.output<typeof MessageSuppressionApi>

export const PaginatedMessageSuppressionApi = zod
    .object({
        count: zod.number().describe('Total number of suppressed recipients for the team.'),
        next: zod.url().nullable().describe('URL for the next page, or null on the last page.'),
        previous: zod.url().nullable().describe('URL for the previous page, or null on the first page.'),
        results: zod.array(MessageSuppressionApi),
    })
    .describe(
        'OpenAPI shape for the paginated suppressions response. Declared so drf-spectacular emits\nthe {count, next, previous, results} envelope on the generated client, rather than a bare\narray — which the frontend actually receives at runtime.'
    )

export type PaginatedMessageSuppressionApi = zod.input<typeof PaginatedMessageSuppressionApi>
export type PaginatedMessageSuppressionApiOutput = zod.output<typeof PaginatedMessageSuppressionApi>

export const MessageTemplateContentTemplatingEnumApi = zod.enum(['liquid']).describe('\* `liquid` - liquid')

export type MessageTemplateContentTemplatingEnumApi = zod.input<typeof MessageTemplateContentTemplatingEnumApi>
export type MessageTemplateContentTemplatingEnumApiOutput = zod.output<typeof MessageTemplateContentTemplatingEnumApi>

export const EmailTemplateApi = zod.object({
    subject: zod
        .string()
        .optional()
        .describe('Email subject line. Supports Liquid templating. Required for email-type templates.'),
    text: zod.string().optional().describe("Plain-text fallback body for clients that can't render the email."),
    html: zod
        .string()
        .optional()
        .describe(
            "Rendered email body — derived from the design at save time. The visual editor's save path supplies it directly; omit it otherwise."
        ),
    design: zod
        .object({
            counters: zod
                .looseObject({})
                .optional()
                .describe('Highest htmlID suffix per element type, e.g. {\"u_row\": 1, \"u_content_text\": 2}.'),
            schemaVersion: zod.number().describe('Design schema version, e.g. 16.'),
            body: zod.object({
                id: zod.string().optional().describe('Any unique string.'),
                rows: zod
                    .array(zod.looseObject({}))
                    .describe('Rows of {id, cells, columns[{id, contents[{id, type, values}], values}], values}.'),
                headers: zod.array(zod.looseObject({})).optional(),
                footers: zod.array(zod.looseObject({})).optional(),
                values: zod
                    .looseObject({})
                    .optional()
                    .describe("Body-level settings: backgroundColor, contentWidth ('600px'), fontFamily, textColor."),
            }),
        })
        .optional()
        .describe(
            "Design JSON for PostHog's visual email editor — the authoring surface and source of truth. The server renders the sent email from it, and it opens as editable blocks in the editor. Full schema in the designing-email-templates skill."
        ),
})

export type EmailTemplateApi = zod.input<typeof EmailTemplateApi>
export type EmailTemplateApiOutput = zod.output<typeof EmailTemplateApi>

export const messageTemplateContentApiTemplatingDefault = `liquid`

export const MessageTemplateContentApi = zod.object({
    templating: MessageTemplateContentTemplatingEnumApi.default(messageTemplateContentApiTemplatingDefault).describe(
        "Templating language for the email content. Always 'liquid' — Liquid tags pass through verbatim.\n\n\* `liquid` - liquid"
    ),
    email: zod
        .union([EmailTemplateApi, zod.null()])
        .optional()
        .describe('Email message content. Replaced as a whole on update — send the complete object.'),
})

export type MessageTemplateContentApi = zod.input<typeof MessageTemplateContentApi>
export type MessageTemplateContentApiOutput = zod.output<typeof MessageTemplateContentApi>

export const RoleAtOrganizationEnumApi = zod
    .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
    .describe(
        '\* `engineering` - Engineering\n\* `data` - Data\n\* `product` - Product Management\n\* `founder` - Founder\n\* `leadership` - Leadership\n\* `marketing` - Marketing\n\* `sales` - Sales \/ Success\n\* `other` - Other'
    )

export type RoleAtOrganizationEnumApi = zod.input<typeof RoleAtOrganizationEnumApi>
export type RoleAtOrganizationEnumApiOutput = zod.output<typeof RoleAtOrganizationEnumApi>

export const BlankEnumApi = zod.enum([''])

export type BlankEnumApi = zod.input<typeof BlankEnumApi>
export type BlankEnumApiOutput = zod.output<typeof BlankEnumApi>

export const userBasicApiDistinctIdMax = 200

export const userBasicApiFirstNameMax = 150

export const userBasicApiLastNameMax = 150

export const userBasicApiEmailMax = 254

export const UserBasicApi = zod.object({
    id: zod.number(),
    uuid: zod.uuid(),
    distinct_id: zod.string().max(userBasicApiDistinctIdMax).nullish(),
    first_name: zod.string().max(userBasicApiFirstNameMax).optional(),
    last_name: zod.string().max(userBasicApiLastNameMax).optional(),
    email: zod.email().max(userBasicApiEmailMax),
    is_email_verified: zod.boolean().nullish(),
    hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
    role_at_organization: zod.union([RoleAtOrganizationEnumApi, BlankEnumApi, zod.null()]).optional(),
})

export type UserBasicApi = zod.input<typeof UserBasicApi>
export type UserBasicApiOutput = zod.output<typeof UserBasicApi>

export const messageTemplateApiNameMax = 400

export const messageTemplateApiTypeMax = 24

export const MessageTemplateApi = zod.object({
    id: zod.uuid(),
    name: zod.string().max(messageTemplateApiNameMax).describe('Human-readable template name shown in the library.'),
    description: zod.string().optional().describe('What the template is for and when to use it.'),
    created_at: zod.iso.datetime({ offset: true }),
    updated_at: zod.iso.datetime({ offset: true }),
    content: MessageTemplateContentApi.optional().describe(
        'Template content keyed by channel. Replaced as a whole on update, not merged.'
    ),
    created_by: UserBasicApi,
    type: zod
        .string()
        .max(messageTemplateApiTypeMax)
        .optional()
        .describe("Message channel of the template. Currently 'email'."),
    message_category: zod
        .uuid()
        .nullish()
        .describe('Message category ID to file the template under. Must belong to the same project.'),
    deleted: zod.boolean().optional().describe('Soft-delete flag. Set true to remove the template from the library.'),
})

export type MessageTemplateApi = zod.input<typeof MessageTemplateApi>
export type MessageTemplateApiOutput = zod.output<typeof MessageTemplateApi>

export const PaginatedMessageTemplateListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(MessageTemplateApi),
})

export type PaginatedMessageTemplateListApi = zod.input<typeof PaginatedMessageTemplateListApi>
export type PaginatedMessageTemplateListApiOutput = zod.output<typeof PaginatedMessageTemplateListApi>

export const patchedMessageTemplateApiNameMax = 400

export const patchedMessageTemplateApiTypeMax = 24

export const PatchedMessageTemplateApi = zod.object({
    id: zod.uuid().optional(),
    name: zod
        .string()
        .max(patchedMessageTemplateApiNameMax)
        .optional()
        .describe('Human-readable template name shown in the library.'),
    description: zod.string().optional().describe('What the template is for and when to use it.'),
    created_at: zod.iso.datetime({ offset: true }).optional(),
    updated_at: zod.iso.datetime({ offset: true }).optional(),
    content: MessageTemplateContentApi.optional().describe(
        'Template content keyed by channel. Replaced as a whole on update, not merged.'
    ),
    created_by: UserBasicApi.optional(),
    type: zod
        .string()
        .max(patchedMessageTemplateApiTypeMax)
        .optional()
        .describe("Message channel of the template. Currently 'email'."),
    message_category: zod
        .uuid()
        .nullish()
        .describe('Message category ID to file the template under. Must belong to the same project.'),
    deleted: zod.boolean().optional().describe('Soft-delete flag. Set true to remove the template from the library.'),
})

export type PatchedMessageTemplateApi = zod.input<typeof PatchedMessageTemplateApi>
export type PatchedMessageTemplateApiOutput = zod.output<typeof PatchedMessageTemplateApi>

export const EmailTemplateDesignOperationEnumApi = zod
    .enum([
        'update_content',
        'update_column',
        'update_row',
        'update_body',
        'add_content',
        'remove_content',
        'move_content',
        'add_row',
        'remove_row',
    ])
    .describe(
        '\* `update_content` - update_content\n\* `update_column` - update_column\n\* `update_row` - update_row\n\* `update_body` - update_body\n\* `add_content` - add_content\n\* `remove_content` - remove_content\n\* `move_content` - move_content\n\* `add_row` - add_row\n\* `remove_row` - remove_row'
    )

export type EmailTemplateDesignOperationEnumApi = zod.input<typeof EmailTemplateDesignOperationEnumApi>
export type EmailTemplateDesignOperationEnumApiOutput = zod.output<typeof EmailTemplateDesignOperationEnumApi>

export const DesignOperationApi = zod.object({
    op: EmailTemplateDesignOperationEnumApi.describe(
        "Design edit. update_content {id, patch}: deep-merge patch into the content block's fields (a null leaf deletes that key) — the surgical path, e.g. change just values.text. update_row \/ update_column {id, patch} and update_body {patch}: same deep-merge for row\/column\/body-level settings. add_content {column_id, content, index?}: insert a content block into a column (id and Unlayer numbering are filled in for you). remove_content {id} \/ move_content {id, column_id, index?}: delete or relocate a block. add_row {row, index?} \/ remove_row {id}: add or delete a row.\n\n\* `update_content` - update_content\n\* `update_column` - update_column\n\* `update_row` - update_row\n\* `update_body` - update_body\n\* `add_content` - add_content\n\* `remove_content` - remove_content\n\* `move_content` - move_content\n\* `add_row` - add_row\n\* `remove_row` - remove_row"
    ),
    id: zod
        .string()
        .optional()
        .describe(
            'Target node id. Required for update_content\/column\/row, remove_content, remove_row, move_content.'
        ),
    column_id: zod.string().optional().describe('Target column id. Required for add_content and move_content.'),
    patch: zod
        .unknown()
        .optional()
        .describe(
            "update_\* only. Partial fields deep-merged into the existing node; a null leaf deletes that key. e.g. {values: {text: '<p>Hi<\/p>'}} changes only the block's text."
        ),
    content: zod
        .unknown()
        .optional()
        .describe(
            "add_content only. A content block {type, values: {...}}; omit id and values._meta — they're assigned server-side. type is one of text, heading, button, image, divider, html, etc."
        ),
    row: zod
        .unknown()
        .optional()
        .describe(
            'add_row only. A full row {cells, columns: [{contents: [...], values}], values}; ids and Unlayer numbering are assigned server-side for the row and everything nested in it.'
        ),
    index: zod
        .number()
        .optional()
        .describe('add_\*\/move_content only. 0-based insert position; omit to append to the end.'),
})

export type DesignOperationApi = zod.input<typeof DesignOperationApi>
export type DesignOperationApiOutput = zod.output<typeof DesignOperationApi>

export const PatchedDesignPatchApi = zod.object({
    operations: zod
        .array(DesignOperationApi)
        .optional()
        .describe(
            "Ordered edits applied atomically to a template's Unlayer design: the stored design is read, the ops are applied in order, the result is validated and re-rendered to HTML, and it's saved only if valid — otherwise the template is unchanged. Reference blocks by id so you never resend the whole design."
        ),
})

export type PatchedDesignPatchApi = zod.input<typeof PatchedDesignPatchApi>
export type PatchedDesignPatchApiOutput = zod.output<typeof PatchedDesignPatchApi>
