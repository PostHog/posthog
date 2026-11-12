/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 7 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * Send one transactional email to one recipient. Name a template made transactional in `template_id`, and `message_data` fills its `{{ variables.* }}` placeholders. Or send content your code rendered with a `template_key`, a `subject` and `html` or `text`: PostHog sends it as is, and its metrics and run history group under the key. Transactional emails skip opt-outs and frequency caps. Send an `Idempotency-Key` header to retry safely without sending the email twice. Needs the `transactional_email:write` scope. A key with `hog_flow:write` also works, but that scope reaches the rest of Workflows too.
 * @summary Send a transactional email
 */
export const MessagingSendEmailCreateParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const MessagingSendEmailCreateHeader = () => zod.object({
    'Idempotency-Key': zod
        .string()
        .optional()
        .describe(
            "A unique key for this email, 1 to 255 visible ASCII characters. Retrying with the same key and the same request within 24 hours sends nothing new and returns the first send's `message_id`. Reusing a key for a different request returns a 422."
        ),
})

export const messagingSendEmailCreateBodyTemplateKeyMax = 256

export const messagingSendEmailCreateBodyTemplateKeyRegExp = new RegExp('^[a-zA-Z0-9_-]+$')
export const messagingSendEmailCreateBodyDistinctIdMax = 400

export const messagingSendEmailCreateBodyReplyToMax = 10

export const messagingSendEmailCreateBodyFromMax = 1024

export const MessagingSendEmailCreateBody = () => zod.strictObject({
    to: zod.email().describe('Email address of the recipient.'),
    template_key: zod
        .string()
        .max(messagingSendEmailCreateBodyTemplateKeyMax)
        .regex(messagingSendEmailCreateBodyTemplateKeyRegExp)
        .optional()
        .describe(
            'Names an email whose content your code rendered, such as `order-shipped`, so its metrics, logs and status group under it. Letters, numbers, hyphens (-) and underscores (_) only, at most 256 characters. Send it with `subject` and `html` or `text`. PostHog sends the content as is and never stores it as a template.'
        ),
    distinct_id: zod
        .string()
        .max(messagingSendEmailCreateBodyDistinctIdMax)
        .nullish()
        .describe(
            "Distinct ID of the recipient's person. The email's engagement events (sent, delivered, opened, clicked, bounced) and the send itself are recorded against that person. Defaults to the recipient's email address. The template can't read the person's properties, so pass everything it needs in `message_data`."
        ),
    subject: zod.string().optional().describe('Subject of the email your code rendered.'),
    html: zod.string().optional().describe('HTML body of the email your code rendered, at most 5 MiB as UTF-8.'),
    text: zod
        .string()
        .optional()
        .describe(
            'Plain text body of the email your code rendered, at most 5 MiB as UTF-8. Without it, PostHog derives the text from `html`.'
        ),
    reply_to: zod
        .array(zod.email())
        .max(messagingSendEmailCreateBodyReplyToMax)
        .optional()
        .describe('Addresses replies to the email your code rendered go to.'),
    scheduled_at: zod.iso
        .datetime({ offset: true })
        .nullish()
        .describe(
            'When to send the email, in ISO 8601 with a timezone offset, such as `2026-11-20T09:00:00Z` or `2026-11-20T10:00:00+01:00`. PostHog keeps the time to the millisecond and holds the email until then, at most 30 days after the request. A time that already passed sends it now. Leave it out or send null to send now.'
        ),
    capture_engagement: zod
        .boolean()
        .optional()
        .describe(
            "Deprecated: use `tracking.engagement`. Whether the engagement events (sent, delivered, opened, clicked, bounced) of the email your code rendered are captured as analytics events of the recipient. Defaults to true. A send with `tracking` can't also carry this field. A project whose admin turned engagement capture off captures nothing, whatever the send says."
        ),
    tracking: zod
        .union([
            zod.boolean(),
            zod.strictObject({
                opens: zod
                    .boolean()
                    .optional()
                    .describe('Whether PostHog adds its open pixel to the email. Defaults to true.'),
                clicks: zod
                    .boolean()
                    .optional()
                    .describe(
                        "Whether the email's links go through a redirect that counts clicks. Defaults to true when the email isn't sensitive and false when it is. Needs `opens`. A link with `data-ph-no-track` keeps its own address."
                    ),
                engagement: zod
                    .boolean()
                    .optional()
                    .describe(
                        "Whether the email's engagement events (sent, delivered, opened, clicked, bounced) are captured as analytics events of the recipient. Defaults to true."
                    ),
            }),
        ])
        .optional()
        .describe(
            "What PostHog tracks for the email your code rendered. `true` tracks opens and clicks and captures engagement events. `false` turns off all of it, now and for any kind of tracking added later. An object sets each kind on its own, and a kind it leaves out keeps its default. Without this field, PostHog tracks opens and captures engagement events, and tracks clicks only when the email isn't sensitive (see `sensitive`). Turn on `clicks` for a sensitive email only when its links are safe to send through a redirect. A link with `data-ph-no-track` keeps its own address either way. Click tracking needs open tracking. A project whose admin turned engagement capture off captures nothing, whatever the send says. The object form needs a JSON body."
        ),
    sensitive: zod
        .boolean()
        .optional()
        .describe(
            "Mark the email as sensitive when it carries login links, reset tokens, or codes. Sensitive emails keep their links unchanged unless `tracking` turns clicks on, leave the subject off engagement events, and keep the content out of logs. Defaults to the matched template's setting, or true when no template matches. It can't be false when the matched template is sensitive."
        ),
    from: zod
        .string()
        .max(messagingSendEmailCreateBodyFromMax)
        .optional()
        .describe(
            "Sender of the email your code rendered, as `security@example.com` or `Example <security@example.com>`, on a verified domain of the project. Without it, the email goes out from the project's default sender, or from its only verified sender when it has no default."
        ),
})

export const MessagingTemplatesListParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const messagingTemplatesListQueryBasicDefault = false

export const MessagingTemplatesListQueryParams = () => zod.object({
    basic: zod
        .boolean()
        .default(messagingTemplatesListQueryBasicDefault)
        .describe(
            'With true, leave out `content` and `draft_content` from each template, for lists that show names and metadata only. `has_draft` still says whether a draft exists.'
        ),
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
    transactional: zod
        .boolean()
        .nullish()
        .describe(
            'With true, list only templates sent over the transactional email API. With false, only the others. Leave out to list all templates.'
        ),
})

export const MessagingTemplatesCreateParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const messagingTemplatesCreateBodyNameMax = 400

export const messagingTemplatesCreateBodyTagsItemMax = 255

export const messagingTemplatesCreateBodyTagsMax = 10

export const messagingTemplatesCreateBodyContentOneTemplatingDefault = `liquid`
export const messagingTemplatesCreateBodyContentOneEmailOneFromOneEmailMax = 254

export const messagingTemplatesCreateBodyTypeMax = 24

export const MessagingTemplatesCreateBody = () => zod.strictObject({
    name: zod
        .string()
        .max(messagingTemplatesCreateBodyNameMax)
        .describe('Human-readable template name shown in the library.'),
    description: zod.string().optional().describe('What the template is for and when to use it.'),
    tags: zod
        .array(zod.string().max(messagingTemplatesCreateBodyTagsItemMax))
        .max(messagingTemplatesCreateBodyTagsMax)
        .optional()
        .describe(
            'Tags for organizing templates, for example by team or use case. Tags are shared with the rest of the project. Omit to keep the current tags, send an empty list to remove them all.'
        ),
    content: zod
        .strictObject({
            templating: zod
                .enum(['liquid'])
                .describe('\* `liquid` - liquid')
                .default(messagingTemplatesCreateBodyContentOneTemplatingDefault)
                .describe(
                    "Templating language for the email content. Always 'liquid' — Liquid tags pass through verbatim.\n\n\* `liquid` - liquid"
                ),
            email: zod
                .union([
                    zod.strictObject({
                        subject: zod
                            .string()
                            .optional()
                            .describe(
                                'Email subject line. Supports Liquid templating. Required in `content` for email-type templates. A `draft_content` may leave it blank until it is published.'
                            ),
                        text: zod
                            .string()
                            .optional()
                            .describe("Plain-text fallback body for clients that can't render the email."),
                        preheader: zod
                            .string()
                            .optional()
                            .describe(
                                'Preview text that most inboxes show after the subject. Supports Liquid templating.'
                            ),
                        design: zod
                            .looseObject({
                                counters: zod
                                    .looseObject({})
                                    .optional()
                                    .describe(
                                        'Highest htmlID suffix per element type, e.g. {\"u_row\": 1, \"u_content_text\": 2}.'
                                    ),
                                schemaVersion: zod.number().describe('Design schema version, e.g. 16.'),
                                body: zod.looseObject({
                                    id: zod.string().optional().describe('Any unique string.'),
                                    rows: zod
                                        .array(zod.looseObject({}))
                                        .describe(
                                            'Rows of {id, cells, columns[{id, contents[{id, type, values}], values}], values}.'
                                        ),
                                    headers: zod.array(zod.looseObject({})).optional(),
                                    footers: zod.array(zod.looseObject({})).optional(),
                                    values: zod
                                        .looseObject({})
                                        .optional()
                                        .describe(
                                            "Body-level settings: backgroundColor, contentWidth ('600px'), fontFamily, textColor."
                                        ),
                                }),
                            })
                            .optional()
                            .describe(
                                "Design JSON for PostHog's visual email editor — the authoring surface and source of truth. The server renders the sent email from it, and it opens as editable blocks in the editor. Full schema in the designing-email-templates skill."
                            ),
                        from: zod
                            .strictObject({
                                email: zod
                                    .string()
                                    .max(messagingTemplatesCreateBodyContentOneEmailOneFromOneEmailMax)
                                    .optional()
                                    .describe(
                                        "Address to send from instead of the sender's own. Must be on the sender's verified domain. Supports Liquid templating. Leave out or empty to use the sender's address."
                                    ),
                                name: zod
                                    .string()
                                    .optional()
                                    .describe(
                                        "Sender name shown in the inbox instead of the sender's own. Supports Liquid templating. Leave out or empty to use the sender's name."
                                    ),
                                integrationId: zod
                                    .number()
                                    .describe(
                                        "ID of the project's email sender integration that sends this email. Transactional sends need a verified sender."
                                    ),
                            })
                            .optional()
                            .describe(
                                'The sender a transactional template sends from. A template made transactional without one gets the sender it was made transactional with.'
                            ),
                        replyTo: zod
                            .string()
                            .optional()
                            .describe(
                                "Reply-to address for a transactional template. Separate several addresses with commas. Supports Liquid templating. Leave empty to use the sender's default reply-to."
                            ),
                    }),
                    zod.null(),
                ])
                .optional()
                .describe('Email message content. Replaced as a whole on update — send the complete object.'),
        })
        .optional()
        .describe('Template content keyed by channel. Replaced as a whole on update, not merged.'),
    type: zod
        .string()
        .max(messagingTemplatesCreateBodyTypeMax)
        .optional()
        .describe("Message channel of the template. Currently 'email'."),
    message_category: zod
        .string()
        .nullish()
        .describe('Message category ID to file the template under. Must belong to the same project.'),
    deleted: zod.boolean().optional().describe('Soft-delete flag. Set true to remove the template from the library.'),
    sensitive: zod
        .boolean()
        .optional()
        .describe(
            "For emails that carry login codes, reset links or other secrets. PostHog keeps no copy of each sent email's body or filled-in subject, and clicked links keep only the site address. Can change at any time."
        ),
})

export const MessagingTemplatesRetrieveParams = () => zod.object({
    id: zod.string().describe('A UUID string identifying this message template.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const MessagingTemplatesPartialUpdateParams = () => zod.object({
    id: zod.string().describe('A UUID string identifying this message template.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const messagingTemplatesPartialUpdateBodyNameMax = 400

export const messagingTemplatesPartialUpdateBodyTagsItemMax = 255

export const messagingTemplatesPartialUpdateBodyTagsMax = 10

export const messagingTemplatesPartialUpdateBodyContentOneTemplatingDefault = `liquid`
export const messagingTemplatesPartialUpdateBodyContentOneEmailOneFromOneEmailMax = 254

export const messagingTemplatesPartialUpdateBodyTypeMax = 24

export const MessagingTemplatesPartialUpdateBody = () => zod.strictObject({
    name: zod
        .string()
        .max(messagingTemplatesPartialUpdateBodyNameMax)
        .optional()
        .describe('Human-readable template name shown in the library.'),
    description: zod.string().optional().describe('What the template is for and when to use it.'),
    tags: zod
        .array(zod.string().max(messagingTemplatesPartialUpdateBodyTagsItemMax))
        .max(messagingTemplatesPartialUpdateBodyTagsMax)
        .optional()
        .describe(
            'Tags for organizing templates, for example by team or use case. Tags are shared with the rest of the project. Omit to keep the current tags, send an empty list to remove them all.'
        ),
    content: zod
        .strictObject({
            templating: zod
                .enum(['liquid'])
                .describe('\* `liquid` - liquid')
                .default(messagingTemplatesPartialUpdateBodyContentOneTemplatingDefault)
                .describe(
                    "Templating language for the email content. Always 'liquid' — Liquid tags pass through verbatim.\n\n\* `liquid` - liquid"
                ),
            email: zod
                .union([
                    zod.strictObject({
                        subject: zod
                            .string()
                            .optional()
                            .describe(
                                'Email subject line. Supports Liquid templating. Required in `content` for email-type templates. A `draft_content` may leave it blank until it is published.'
                            ),
                        text: zod
                            .string()
                            .optional()
                            .describe("Plain-text fallback body for clients that can't render the email."),
                        preheader: zod
                            .string()
                            .optional()
                            .describe(
                                'Preview text that most inboxes show after the subject. Supports Liquid templating.'
                            ),
                        design: zod
                            .looseObject({
                                counters: zod
                                    .looseObject({})
                                    .optional()
                                    .describe(
                                        'Highest htmlID suffix per element type, e.g. {\"u_row\": 1, \"u_content_text\": 2}.'
                                    ),
                                schemaVersion: zod.number().describe('Design schema version, e.g. 16.'),
                                body: zod.looseObject({
                                    id: zod.string().optional().describe('Any unique string.'),
                                    rows: zod
                                        .array(zod.looseObject({}))
                                        .describe(
                                            'Rows of {id, cells, columns[{id, contents[{id, type, values}], values}], values}.'
                                        ),
                                    headers: zod.array(zod.looseObject({})).optional(),
                                    footers: zod.array(zod.looseObject({})).optional(),
                                    values: zod
                                        .looseObject({})
                                        .optional()
                                        .describe(
                                            "Body-level settings: backgroundColor, contentWidth ('600px'), fontFamily, textColor."
                                        ),
                                }),
                            })
                            .optional()
                            .describe(
                                "Design JSON for PostHog's visual email editor — the authoring surface and source of truth. The server renders the sent email from it, and it opens as editable blocks in the editor. Full schema in the designing-email-templates skill."
                            ),
                        from: zod
                            .strictObject({
                                email: zod
                                    .string()
                                    .max(messagingTemplatesPartialUpdateBodyContentOneEmailOneFromOneEmailMax)
                                    .optional()
                                    .describe(
                                        "Address to send from instead of the sender's own. Must be on the sender's verified domain. Supports Liquid templating. Leave out or empty to use the sender's address."
                                    ),
                                name: zod
                                    .string()
                                    .optional()
                                    .describe(
                                        "Sender name shown in the inbox instead of the sender's own. Supports Liquid templating. Leave out or empty to use the sender's name."
                                    ),
                                integrationId: zod
                                    .number()
                                    .describe(
                                        "ID of the project's email sender integration that sends this email. Transactional sends need a verified sender."
                                    ),
                            })
                            .optional()
                            .describe(
                                'The sender a transactional template sends from. A template made transactional without one gets the sender it was made transactional with.'
                            ),
                        replyTo: zod
                            .string()
                            .optional()
                            .describe(
                                "Reply-to address for a transactional template. Separate several addresses with commas. Supports Liquid templating. Leave empty to use the sender's default reply-to."
                            ),
                    }),
                    zod.null(),
                ])
                .optional()
                .describe('Email message content. Replaced as a whole on update — send the complete object.'),
        })
        .optional()
        .describe('Template content keyed by channel. Replaced as a whole on update, not merged.'),
    type: zod
        .string()
        .max(messagingTemplatesPartialUpdateBodyTypeMax)
        .optional()
        .describe("Message channel of the template. Currently 'email'."),
    message_category: zod
        .string()
        .nullish()
        .describe('Message category ID to file the template under. Must belong to the same project.'),
    deleted: zod.boolean().optional().describe('Soft-delete flag. Set true to remove the template from the library.'),
    sensitive: zod
        .boolean()
        .optional()
        .describe(
            "For emails that carry login codes, reset links or other secrets. PostHog keeps no copy of each sent email's body or filled-in subject, and clicked links keep only the site address. Can change at any time."
        ),
})

export const MessagingTemplatesDesignPartialUpdateParams = () => zod.object({
    id: zod.string().describe('A UUID string identifying this message template.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const MessagingTemplatesDesignPartialUpdateBody = () => zod.strictObject({
    operations: zod
        .array(
            zod.strictObject({
                op: zod
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
                    .describe(
                        "Design edit. update_content {id, patch}: deep-merge patch into the content block's fields (a null leaf deletes that key) — the surgical path, e.g. change just values.text. update_row \/ update_column {id, patch} and update_body {patch}: same deep-merge for row\/column\/body-level settings. add_content {column_id, content, index?}: insert a content block into a column (id and Unlayer numbering are filled in for you). remove_content {id} \/ move_content {id, column_id, index?}: delete or relocate a block. add_row {row, index?} \/ remove_row {id}: add or delete a row.\n\n\* `update_content` - update_content\n\* `update_column` - update_column\n\* `update_row` - update_row\n\* `update_body` - update_body\n\* `add_content` - add_content\n\* `remove_content` - remove_content\n\* `move_content` - move_content\n\* `add_row` - add_row\n\* `remove_row` - remove_row"
                    ),
                id: zod
                    .string()
                    .optional()
                    .describe(
                        'Target node id. Required for update_content\/column\/row, remove_content, remove_row, move_content.'
                    ),
                column_id: zod
                    .string()
                    .optional()
                    .describe('Target column id. Required for add_content and move_content.'),
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
        )
        .optional()
        .describe(
            "Ordered edits applied atomically to a template's Unlayer design: the stored design is read, the ops are applied in order, the result is validated and re-rendered to HTML, and it's saved only if valid — otherwise the template is unchanged. Reference blocks by id so you never resend the whole design."
        ),
})

/**
 * Make this template sendable over the transactional email API. This creates the workflow that sends it, with its own metrics, run history and versions. This can't be undone: the template stays transactional. Transactional sends ignore marketing opt-outs. Calling it again on a transactional template changes nothing. Needs the `transactional_email:write` scope, the same scope as sending. A key with `hog_flow:write` also works, but that scope reaches the rest of Workflows too. Without `hog_flow:read`, the response leaves out `content` and `draft_content`.
 * @summary Make a template transactional
 */
export const MessagingTemplatesMakeTransactionalCreateParams = () => zod.object({
    id: zod.string().describe('A UUID string identifying this message template.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const MessagingTemplatesMakeTransactionalCreateBody = () => zod.strictObject({
    from_integration_id: zod
        .number()
        .nullish()
        .describe(
            "ID of the verified email sender integration the email is sent from. Defaults to the project's default sender."
        ),
})
