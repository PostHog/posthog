/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 8 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * Send one transactional email to one recipient, in one of two forms. A template named by its key or id: `message_data` fills its `{{ variables.* }}` placeholders. With `template.hash`, PostHog checks that it holds the content you hold: a key or content it doesn't hold sends nothing and answers `template_outdated`, and content that newer content replaced sends the current content with a `template_superseded` warning. Or content your code rendered, named by `template_key`: PostHog sends it as is and never stores it. Transactional emails skip opt-outs and frequency caps. Send an `Idempotency-Key` header to retry safely without sending the email twice.
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
            "A unique key for this email, 1 to 255 visible ASCII characters. Retrying with the same key and the same request within 24 hours sends nothing new and returns the first send's `message_id`. Reusing a key for a different request, or on the other send route, returns a 422."
        ),
})

export const messagingSendEmailCreateBodyIdentifiersOneDistinctIdMax = 400

export const messagingSendEmailCreateBodyReplyToMax = 10

export const messagingSendEmailCreateBodyCcMax = 10

export const messagingSendEmailCreateBodyBccMax = 10

export const messagingSendEmailCreateBodyTagsItemNameMax = 256

export const messagingSendEmailCreateBodyTagsItemValueMax = 256

export const messagingSendEmailCreateBodyTagsMax = 10

export const MessagingSendEmailCreateBody = () => zod.object({
    to: zod.email().describe('Email address of the recipient.'),
    identifiers: zod
        .object({
            distinct_id: zod
                .string()
                .max(messagingSendEmailCreateBodyIdentifiersOneDistinctIdMax)
                .nullish()
                .describe(
                    "Distinct ID of the recipient's person. The email's engagement events (sent, delivered, opened, clicked, bounced) and the send itself are recorded against that person. Defaults to the recipient's email address. The template can't read the person's properties, so pass everything it needs in `message_data`."
                ),
        })
        .optional()
        .describe('Who the email is for, used to attribute engagement events.'),
    message_data: zod
        .record(zod.string(), zod.unknown())
        .optional()
        .describe(
            'Data for the template\'s Liquid placeholders, available as `variables`. For example `{\"reset_link\": \"https:\/\/...\"}` fills `{{ variables.reset_link }}`.'
        ),
    template: zod
        .object({
            key: zod
                .string()
                .optional()
                .describe(
                    'Key of the template, as uploaded with `PUT \/api\/projects\/@current\/messaging_templates\/by_key\/{key}\/`. Give either `key` or `id`.'
                ),
            hash: zod
                .string()
                .optional()
                .describe(
                    'Content hash of the template you hold, as `v1:` and 64 hex characters. When PostHog never published that content, the send answers `template_outdated` and sends nothing. Only with `key`.'
                ),
            id: zod
                .string()
                .optional()
                .describe('ID of the template, for templates made in PostHog. Give either `key` or `id`.'),
        })
        .optional()
        .describe(
            'The template to send, by key or by id. Leave it out to send content your code rendered, with `template_key`.'
        ),
    template_key: zod
        .string()
        .optional()
        .describe(
            'Names an email whose content your code rendered, such as `password-reset`, so its metrics, logs and status group under it. Send it with `subject` and `html` or `text`, instead of `template`. PostHog sends the content as is and never stores it as a template.'
        ),
    subject: zod.string().optional().describe('Subject of the rendered email. Only with `template_key`.'),
    html: zod.string().optional().describe('HTML body of the rendered email. Only with `template_key`.'),
    text: zod
        .string()
        .optional()
        .describe(
            'Plain text body of the rendered email. Only with `template_key`. Without it, PostHog derives the text from `html`.'
        ),
    reply_to: zod
        .array(zod.email())
        .max(messagingSendEmailCreateBodyReplyToMax)
        .optional()
        .describe('Addresses replies go to. Not with `template.id`.'),
    cc: zod
        .array(zod.email())
        .max(messagingSendEmailCreateBodyCcMax)
        .optional()
        .describe(
            'Addresses that get a visible copy, at most 10. Each one is checked against the suppression list, and one suppressed address stops the send. Not with `template.id`.'
        ),
    bcc: zod
        .array(zod.email())
        .max(messagingSendEmailCreateBodyBccMax)
        .optional()
        .describe(
            'Addresses that get a hidden copy, at most 10. Each one is checked against the suppression list, and one suppressed address stops the send. Not with `template.id`.'
        ),
    headers: zod
        .record(zod.string(), zod.string())
        .optional()
        .describe(
            'Extra email headers by name, such as `X-Entity-Ref-ID` or `List-Unsubscribe`, at most 10. Values are printable ASCII up to 870 characters. Headers PostHog sets itself, such as `From`, `Subject` and `Content-Type`, are refused. Not with `template.id`.'
        ),
    tags: zod
        .array(
            zod.object({
                name: zod
                    .string()
                    .max(messagingSendEmailCreateBodyTagsItemNameMax)
                    .describe(
                        "Tag name: ASCII letters, numbers, `_` and `-`. Names starting with `ph_` are PostHog's."
                    ),
                value: zod
                    .string()
                    .max(messagingSendEmailCreateBodyTagsItemValueMax)
                    .describe('Tag value: ASCII letters, numbers, `_` and `-`.'),
            })
        )
        .max(messagingSendEmailCreateBodyTagsMax)
        .optional()
        .describe(
            "Name and value pairs, at most 10, that PostHog adds to the email's engagement events as `$email_tags`. Not with `template.id`."
        ),
    capture_engagement: zod
        .boolean()
        .optional()
        .describe(
            "Whether the email's engagement events (sent, delivered, opened, clicked, bounced) are captured as analytics events of the recipient. They count as analytics events. Defaults to on for `template_key` and `template.key` sends, and to the project's setting for `template.id` sends."
        ),
    from: zod
        .string()
        .optional()
        .describe(
            "Sender, as `security@example.com` or `Example <security@example.com>`, on a verified domain of the project. Without it, rendered content goes out from the project's default sender, and a template from its own sender. Not with `template.id`."
        ),
})

/**
 * What every route of the transactional email API shares: the flag, workflow access and the send.
 */
export const MessagingTemplatesListParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const MessagingTemplatesListQueryParams = () => zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

/**
 * What every route of the transactional email API shares: the flag, workflow access and the send.
 */
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

export const MessagingTemplatesCreateBody = () => zod.object({
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
        .object({
            templating: zod
                .enum(['liquid'])
                .describe('\* `liquid` - liquid')
                .default(messagingTemplatesCreateBodyContentOneTemplatingDefault)
                .describe(
                    "Templating language for the email content. Always 'liquid' — Liquid tags pass through verbatim.\n\n\* `liquid` - liquid"
                ),
            email: zod
                .union([
                    zod.object({
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
                            .object({
                                counters: zod
                                    .looseObject({})
                                    .optional()
                                    .describe(
                                        'Highest htmlID suffix per element type, e.g. {\"u_row\": 1, \"u_content_text\": 2}.'
                                    ),
                                schemaVersion: zod.number().describe('Design schema version, e.g. 16.'),
                                body: zod.object({
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
                            .object({
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

/**
 * What every route of the transactional email API shares: the flag, workflow access and the send.
 */
export const MessagingTemplatesRetrieveParams = () => zod.object({
    id: zod.string().describe('A UUID string identifying this message template.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * What every route of the transactional email API shares: the flag, workflow access and the send.
 */
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

export const messagingTemplatesPartialUpdateBodyKeyMax = 400

export const MessagingTemplatesPartialUpdateBody = () => zod.object({
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
        .object({
            templating: zod
                .enum(['liquid'])
                .describe('\* `liquid` - liquid')
                .default(messagingTemplatesPartialUpdateBodyContentOneTemplatingDefault)
                .describe(
                    "Templating language for the email content. Always 'liquid' — Liquid tags pass through verbatim.\n\n\* `liquid` - liquid"
                ),
            email: zod
                .union([
                    zod.object({
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
                            .object({
                                counters: zod
                                    .looseObject({})
                                    .optional()
                                    .describe(
                                        'Highest htmlID suffix per element type, e.g. {\"u_row\": 1, \"u_content_text\": 2}.'
                                    ),
                                schemaVersion: zod.number().describe('Design schema version, e.g. 16.'),
                                body: zod.object({
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
                            .object({
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
    key: zod
        .string()
        .max(messagingTemplatesPartialUpdateBodyKeyMax)
        .optional()
        .describe(
            'Give a template that has no key one, so code can take it over: the next upload under this key updates this template and keeps its id, workflow and sender. Send it as the only field of the PATCH. Letters, digits, hyphens (-) and underscores (_). Set once: a template that has a key keeps it.'
        ),
})

/**
 * What every route of the transactional email API shares: the flag, workflow access and the send.
 */
export const MessagingTemplatesDesignPartialUpdateParams = () => zod.object({
    id: zod.string().describe('A UUID string identifying this message template.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const MessagingTemplatesDesignPartialUpdateBody = () => zod.object({
    operations: zod
        .array(
            zod.object({
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
 * Make this template sendable over the transactional email API. This creates the workflow that sends it, with its own metrics, run history and versions. This can't be undone: the template stays transactional. Transactional sends ignore marketing opt-outs. Calling it again on a transactional template changes nothing.
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

export const MessagingTemplatesMakeTransactionalCreateBody = () => zod.object({
    from_integration_id: zod
        .number()
        .nullish()
        .describe(
            "ID of the verified email sender integration the email is sent from. Defaults to the project's default sender."
        ),
})

/**
 * Create or update the email template with this key from HTML, for templates kept as files in a repository. The first upload creates the template and makes it transactional with the project's default verified sender. A later upload publishes changed content at once, and answers `unchanged` when the content is the same. With `if_not_superseded`, an upload of content that newer content already replaced changes nothing and answers `superseded`. An upload keeps the template's sender and never turns a paused template back on.
 * @summary Upload a template by key
 */
export const MessagingTemplatesByKeyUpdateParams = () => zod.object({
    key: zod
        .string()
        .describe(
            'Key of the template, chosen by you. Letters, digits, hyphens (-) and underscores (_), at most 400 characters. The same key names the template in every project.'
        ),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const messagingTemplatesByKeyUpdateBodyNameMax = 400

export const messagingTemplatesByKeyUpdateBodySourceOneRepositoryMax = 400

export const messagingTemplatesByKeyUpdateBodySourceOnePathMax = 400

export const messagingTemplatesByKeyUpdateBodySourceOneRefMax = 400

export const messagingTemplatesByKeyUpdateBodyIfNotSupersededDefault = false
export const messagingTemplatesByKeyUpdateBodyIfCodeManagedDefault = false

export const MessagingTemplatesByKeyUpdateBody = () => zod.object({
    name: zod
        .string()
        .max(messagingTemplatesByKeyUpdateBodyNameMax)
        .describe('Template name shown in the template library.'),
    subject: zod.string().describe('Email subject line. Supports Liquid, such as `{{ variables.first_name }}`.'),
    html: zod
        .string()
        .optional()
        .describe(
            'Email body as HTML, stored as sent. Supports Liquid, such as `{{ variables.first_name }}`. Send at least one of `html` and `text`.'
        ),
    text: zod
        .string()
        .optional()
        .describe(
            "Plain-text body for email clients that can't show HTML, stored as sent. Send at least one of `html` and `text`. Leaving it out removes the stored one."
        ),
    preheader: zod
        .string()
        .optional()
        .describe('Inbox preview text shown after the subject. Leaving it out removes the stored one.'),
    source: zod
        .object({
            repository: zod
                .string()
                .max(messagingTemplatesByKeyUpdateBodySourceOneRepositoryMax)
                .nullish()
                .describe('Host and path of the repository the file is in, such as `github.com\/example\/app`.'),
            path: zod
                .string()
                .max(messagingTemplatesByKeyUpdateBodySourceOnePathMax)
                .nullish()
                .describe('Path of the template file in the repository, such as `emails\/welcome.html`.'),
            ref: zod
                .string()
                .max(messagingTemplatesByKeyUpdateBodySourceOneRefMax)
                .nullish()
                .describe('Commit or branch the file was uploaded from.'),
        })
        .optional()
        .describe(
            'Where the template file lives, so people in PostHog can find it. Leaving it out, or a part of it, keeps what is stored.'
        ),
    if_not_superseded: zod
        .boolean()
        .default(messagingTemplatesByKeyUpdateBodyIfNotSupersededDefault)
        .describe(
            'Set it on uploads a program makes on its own, such as after a send answered `template_outdated`. When newer content already replaced this content, the upload changes nothing and answers `superseded`. Leave it out to publish the content in any case, such as to roll back to earlier content.'
        ),
    if_code_managed: zod
        .boolean()
        .default(messagingTemplatesByKeyUpdateBodyIfCodeManagedDefault)
        .describe(
            'Set it on uploads a send makes on its own. When people edit the template with this key in PostHog, the upload changes nothing and answers `409` with `template_edited_in_posthog`. Leave it out to take the template over from PostHog.'
        ),
})
