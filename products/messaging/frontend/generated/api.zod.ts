/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

export const messagingCategoriesCreateBodyKeyMax = 64

export const messagingCategoriesCreateBodyNameMax = 128

export const MessagingCategoriesCreateBody = /* @__PURE__ */ zod.object({
    key: zod.string().max(messagingCategoriesCreateBodyKeyMax),
    name: zod.string().max(messagingCategoriesCreateBodyNameMax),
    description: zod.string().optional(),
    public_description: zod.string().optional(),
    category_type: zod
        .enum(['marketing', 'transactional'])
        .optional()
        .describe('\* `marketing` - Marketing\n\* `transactional` - Transactional'),
    deleted: zod.boolean().optional(),
})

export const messagingCategoriesUpdateBodyKeyMax = 64

export const messagingCategoriesUpdateBodyNameMax = 128

export const MessagingCategoriesUpdateBody = /* @__PURE__ */ zod.object({
    key: zod.string().max(messagingCategoriesUpdateBodyKeyMax),
    name: zod.string().max(messagingCategoriesUpdateBodyNameMax),
    description: zod.string().optional(),
    public_description: zod.string().optional(),
    category_type: zod
        .enum(['marketing', 'transactional'])
        .optional()
        .describe('\* `marketing` - Marketing\n\* `transactional` - Transactional'),
    deleted: zod.boolean().optional(),
})

export const messagingCategoriesPartialUpdateBodyKeyMax = 64

export const messagingCategoriesPartialUpdateBodyNameMax = 128

export const MessagingCategoriesPartialUpdateBody = /* @__PURE__ */ zod.object({
    key: zod.string().max(messagingCategoriesPartialUpdateBodyKeyMax).optional(),
    name: zod.string().max(messagingCategoriesPartialUpdateBodyNameMax).optional(),
    description: zod.string().optional(),
    public_description: zod.string().optional(),
    category_type: zod
        .enum(['marketing', 'transactional'])
        .optional()
        .describe('\* `marketing` - Marketing\n\* `transactional` - Transactional'),
    deleted: zod.boolean().optional(),
})

/**
 * Import subscription topics and globally unsubscribed users from Customer.io API.
 * Persists the App API key in Integration(kind="customerio-app").
 * If no app_api_key is provided, reuses the stored Integration key.
 */
export const messagingCategoriesImportFromCustomerioCreateBodyKeyMax = 64

export const messagingCategoriesImportFromCustomerioCreateBodyNameMax = 128

export const MessagingCategoriesImportFromCustomerioCreateBody = /* @__PURE__ */ zod.object({
    key: zod.string().max(messagingCategoriesImportFromCustomerioCreateBodyKeyMax),
    name: zod.string().max(messagingCategoriesImportFromCustomerioCreateBodyNameMax),
    description: zod.string().optional(),
    public_description: zod.string().optional(),
    category_type: zod
        .enum(['marketing', 'transactional'])
        .optional()
        .describe('\* `marketing` - Marketing\n\* `transactional` - Transactional'),
    deleted: zod.boolean().optional(),
})

/**
 * Import customer preferences from CSV file
 * Expected CSV columns: id, email, cio_subscription_preferences
 */
export const messagingCategoriesImportPreferencesCsvCreateBodyKeyMax = 64

export const messagingCategoriesImportPreferencesCsvCreateBodyNameMax = 128

export const MessagingCategoriesImportPreferencesCsvCreateBody = /* @__PURE__ */ zod.object({
    key: zod.string().max(messagingCategoriesImportPreferencesCsvCreateBodyKeyMax),
    name: zod.string().max(messagingCategoriesImportPreferencesCsvCreateBodyNameMax),
    description: zod.string().optional(),
    public_description: zod.string().optional(),
    category_type: zod
        .enum(['marketing', 'transactional'])
        .optional()
        .describe('\* `marketing` - Marketing\n\* `transactional` - Transactional'),
    deleted: zod.boolean().optional(),
})

/**
 * Save Customer.io Track API credentials and/or toggle outbound sync.
 *
 * Accepts:
 *   - site_id (optional): set on first creation only
 *   - api_key (optional): set on first creation only
 *   - region (optional): "us" or "eu", set on first creation only
 *   - track_enabled (required): enable or disable outbound sync
 */
export const messagingCategoriesSaveTrackConfigCreateBodyKeyMax = 64

export const messagingCategoriesSaveTrackConfigCreateBodyNameMax = 128

export const MessagingCategoriesSaveTrackConfigCreateBody = /* @__PURE__ */ zod.object({
    key: zod.string().max(messagingCategoriesSaveTrackConfigCreateBodyKeyMax),
    name: zod.string().max(messagingCategoriesSaveTrackConfigCreateBodyNameMax),
    description: zod.string().optional(),
    public_description: zod.string().optional(),
    category_type: zod
        .enum(['marketing', 'transactional'])
        .optional()
        .describe('\* `marketing` - Marketing\n\* `transactional` - Transactional'),
    deleted: zod.boolean().optional(),
})

/**
 * Save webhook signing secret and/or toggle the Customer.io webhook sync.
 *
 * Accepts:
 *   - webhook_signing_secret (optional): set on first creation only
 *   - webhook_enabled (required): enable or disable the webhook
 */
export const messagingCategoriesSaveWebhookConfigCreateBodyKeyMax = 64

export const messagingCategoriesSaveWebhookConfigCreateBodyNameMax = 128

export const MessagingCategoriesSaveWebhookConfigCreateBody = /* @__PURE__ */ zod.object({
    key: zod.string().max(messagingCategoriesSaveWebhookConfigCreateBodyKeyMax),
    name: zod.string().max(messagingCategoriesSaveWebhookConfigCreateBodyNameMax),
    description: zod.string().optional(),
    public_description: zod.string().optional(),
    category_type: zod
        .enum(['marketing', 'transactional'])
        .optional()
        .describe('\* `marketing` - Marketing\n\* `transactional` - Transactional'),
    deleted: zod.boolean().optional(),
})

/**
 * Manually add a recipient to the opt-out list for a specific category or all marketing messages.
 * @summary Manually add a recipient to the opt-out list
 */
export const messagingPreferencesAddOptOutCreateBodyIdentifierMax = 512

export const MessagingPreferencesAddOptOutCreateBody = /* @__PURE__ */ zod.object({
    identifier: zod
        .string()
        .max(messagingPreferencesAddOptOutCreateBodyIdentifierMax)
        .describe('The recipient identifier to opt out (e.g. email address).'),
    category_key: zod
        .string()
        .optional()
        .describe('Optional message category key. If omitted, the recipient is opted out of all marketing messages.'),
})

/**
 * Opt every recipient in the list out of the category named on their entry, or a default category.
 * @summary Add multiple recipients to the opt-out list
 */
export const messagingPreferencesBulkAddOptOutsCreateBodyOptOutsItemIdentifierMax = 512

export const MessagingPreferencesBulkAddOptOutsCreateBody = /* @__PURE__ */ zod.object({
    opt_outs: zod
        .array(
            zod.object({
                identifier: zod
                    .string()
                    .max(messagingPreferencesBulkAddOptOutsCreateBodyOptOutsItemIdentifierMax)
                    .describe('The recipient identifier to opt out (e.g. email address).'),
                category_key: zod
                    .string()
                    .optional()
                    .describe('Message category key for this recipient. Overrides the request-level category_key.'),
            })
        )
        .describe('Recipients to opt out, at most 1000 per request.'),
    category_key: zod
        .string()
        .optional()
        .describe(
            'Message category key applied to entries without their own. If omitted, recipients are opted out of all marketing messages.'
        ),
})

/**
 * Generate an unsubscribe link for the current user's email address
 * @summary Generate a preferences page link for a recipient
 */
export const messagingPreferencesGenerateLinkCreateBodyRecipientMax = 512

export const MessagingPreferencesGenerateLinkCreateBody = /* @__PURE__ */ zod.object({
    recipient: zod
        .string()
        .max(messagingPreferencesGenerateLinkCreateBodyRecipientMax)
        .optional()
        .describe("Recipient to generate the link for. Defaults to the requesting user's own email address."),
})

/**
 * Opt a recipient back in to a specific category, or to all marketing messages.
 * @summary Remove a recipient from the opt-out list
 */
export const messagingPreferencesRemoveOptOutCreateBodyIdentifierMax = 512

export const MessagingPreferencesRemoveOptOutCreateBody = /* @__PURE__ */ zod.object({
    identifier: zod
        .string()
        .max(messagingPreferencesRemoveOptOutCreateBodyIdentifierMax)
        .describe('The recipient identifier to opt back in (e.g. email address).'),
    category_key: zod
        .string()
        .optional()
        .describe(
            'Optional message category key. If omitted, the recipient is opted back in to all marketing messages.'
        ),
})

/**
 * Manually suppress an email address so no workflow sends to it.
 * @summary Manually add an email address to the suppression list
 */
export const messagingSuppressionsAddSuppressionCreateBodyIdentifierMax = 512

export const MessagingSuppressionsAddSuppressionCreateBody = /* @__PURE__ */ zod.object({
    identifier: zod
        .string()
        .max(messagingSuppressionsAddSuppressionCreateBodyIdentifierMax)
        .describe('The email address to suppress. Will not receive any messages until removed.'),
})

/**
 * Remove an address from the suppression list so it can receive messages again.
 * @summary Remove an email address from the suppression list
 */
export const messagingSuppressionsRemoveSuppressionCreateBodyIdentifierMax = 512

export const MessagingSuppressionsRemoveSuppressionCreateBody = /* @__PURE__ */ zod.object({
    identifier: zod
        .string()
        .max(messagingSuppressionsRemoveSuppressionCreateBodyIdentifierMax)
        .describe('The email address to suppress. Will not receive any messages until removed.'),
})

export const messagingTemplatesCreateBodyNameMax = 400

export const messagingTemplatesCreateBodyTagsItemMax = 255

export const messagingTemplatesCreateBodyTagsMax = 10

export const messagingTemplatesCreateBodyContentOneTemplatingDefault = `liquid`
export const messagingTemplatesCreateBodyContentOneEmailOneFromOneEmailMax = 254

export const messagingTemplatesCreateBodyTypeMax = 24

export const messagingTemplatesCreateBodyDraftContentOneTemplatingDefault = `liquid`
export const messagingTemplatesCreateBodyDraftContentOneEmailOneFromOneEmailMax = 254

export const MessagingTemplatesCreateBody = /* @__PURE__ */ zod.object({
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
        .uuid()
        .nullish()
        .describe('Message category ID to file the template under. Must belong to the same project.'),
    deleted: zod.boolean().optional().describe('Soft-delete flag. Set true to remove the template from the library.'),
    sensitive: zod
        .boolean()
        .optional()
        .describe(
            "For emails that carry login codes, reset links or other secrets. PostHog keeps no copy of each sent email's body or filled-in subject, and clicked links keep only the site address. Can change at any time."
        ),
    draft_content: zod
        .union([
            zod.object({
                templating: zod
                    .enum(['liquid'])
                    .describe('\* `liquid` - liquid')
                    .default(messagingTemplatesCreateBodyDraftContentOneTemplatingDefault)
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
                                        .max(messagingTemplatesCreateBodyDraftContentOneEmailOneFromOneEmailMax)
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
            }),
            zod.null(),
        ])
        .optional()
        .describe(
            "Unpublished edits to a transactional template's content. Sends keep using `content`. Saving `content` publishes it and clears the draft. Set null to discard the draft."
        ),
})

export const messagingTemplatesUpdateBodyNameMax = 400

export const messagingTemplatesUpdateBodyTagsItemMax = 255

export const messagingTemplatesUpdateBodyTagsMax = 10

export const messagingTemplatesUpdateBodyContentOneTemplatingDefault = `liquid`
export const messagingTemplatesUpdateBodyContentOneEmailOneFromOneEmailMax = 254

export const messagingTemplatesUpdateBodyTypeMax = 24

export const messagingTemplatesUpdateBodyDraftContentOneTemplatingDefault = `liquid`
export const messagingTemplatesUpdateBodyDraftContentOneEmailOneFromOneEmailMax = 254

export const MessagingTemplatesUpdateBody = /* @__PURE__ */ zod.object({
    name: zod
        .string()
        .max(messagingTemplatesUpdateBodyNameMax)
        .describe('Human-readable template name shown in the library.'),
    description: zod.string().optional().describe('What the template is for and when to use it.'),
    tags: zod
        .array(zod.string().max(messagingTemplatesUpdateBodyTagsItemMax))
        .max(messagingTemplatesUpdateBodyTagsMax)
        .optional()
        .describe(
            'Tags for organizing templates, for example by team or use case. Tags are shared with the rest of the project. Omit to keep the current tags, send an empty list to remove them all.'
        ),
    content: zod
        .object({
            templating: zod
                .enum(['liquid'])
                .describe('\* `liquid` - liquid')
                .default(messagingTemplatesUpdateBodyContentOneTemplatingDefault)
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
                                    .max(messagingTemplatesUpdateBodyContentOneEmailOneFromOneEmailMax)
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
        .max(messagingTemplatesUpdateBodyTypeMax)
        .optional()
        .describe("Message channel of the template. Currently 'email'."),
    message_category: zod
        .uuid()
        .nullish()
        .describe('Message category ID to file the template under. Must belong to the same project.'),
    deleted: zod.boolean().optional().describe('Soft-delete flag. Set true to remove the template from the library.'),
    sensitive: zod
        .boolean()
        .optional()
        .describe(
            "For emails that carry login codes, reset links or other secrets. PostHog keeps no copy of each sent email's body or filled-in subject, and clicked links keep only the site address. Can change at any time."
        ),
    draft_content: zod
        .union([
            zod.object({
                templating: zod
                    .enum(['liquid'])
                    .describe('\* `liquid` - liquid')
                    .default(messagingTemplatesUpdateBodyDraftContentOneTemplatingDefault)
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
                                        .max(messagingTemplatesUpdateBodyDraftContentOneEmailOneFromOneEmailMax)
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
            }),
            zod.null(),
        ])
        .optional()
        .describe(
            "Unpublished edits to a transactional template's content. Sends keep using `content`. Saving `content` publishes it and clears the draft. Set null to discard the draft."
        ),
})

export const messagingTemplatesPartialUpdateBodyNameMax = 400

export const messagingTemplatesPartialUpdateBodyTagsItemMax = 255

export const messagingTemplatesPartialUpdateBodyTagsMax = 10

export const messagingTemplatesPartialUpdateBodyContentOneTemplatingDefault = `liquid`
export const messagingTemplatesPartialUpdateBodyContentOneEmailOneFromOneEmailMax = 254

export const messagingTemplatesPartialUpdateBodyTypeMax = 24

export const messagingTemplatesPartialUpdateBodyDraftContentOneTemplatingDefault = `liquid`
export const messagingTemplatesPartialUpdateBodyDraftContentOneEmailOneFromOneEmailMax = 254

export const MessagingTemplatesPartialUpdateBody = /* @__PURE__ */ zod.object({
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
        .uuid()
        .nullish()
        .describe('Message category ID to file the template under. Must belong to the same project.'),
    deleted: zod.boolean().optional().describe('Soft-delete flag. Set true to remove the template from the library.'),
    sensitive: zod
        .boolean()
        .optional()
        .describe(
            "For emails that carry login codes, reset links or other secrets. PostHog keeps no copy of each sent email's body or filled-in subject, and clicked links keep only the site address. Can change at any time."
        ),
    draft_content: zod
        .union([
            zod.object({
                templating: zod
                    .enum(['liquid'])
                    .describe('\* `liquid` - liquid')
                    .default(messagingTemplatesPartialUpdateBodyDraftContentOneTemplatingDefault)
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
                                        .max(messagingTemplatesPartialUpdateBodyDraftContentOneEmailOneFromOneEmailMax)
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
            }),
            zod.null(),
        ])
        .optional()
        .describe(
            "Unpublished edits to a transactional template's content. Sends keep using `content`. Saving `content` publishes it and clears the draft. Set null to discard the draft."
        ),
})

export const MessagingTemplatesDesignPartialUpdateBody = /* @__PURE__ */ zod.object({
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
export const MessagingTemplatesMakeTransactionalCreateBody = /* @__PURE__ */ zod.object({
    from_integration_id: zod
        .number()
        .nullish()
        .describe(
            "ID of the verified email sender integration the email is sent from. Defaults to the project's default sender."
        ),
})

/**
 * Send one transactional email from this template to one recipient. The template must be made transactional first. `message_data` fills the template's `{{ variables.* }}` placeholders. Transactional emails skip opt-outs and frequency caps. Send an `Idempotency-Key` header to retry safely without sending the email twice.
 * @summary Send a transactional email
 */
export const messagingTemplatesSendCreateBodyIdentifiersOneDistinctIdMax = 400

export const MessagingTemplatesSendCreateBody = /* @__PURE__ */ zod.object({
    to: zod.email().describe('Email address of the recipient.'),
    identifiers: zod
        .object({
            distinct_id: zod
                .string()
                .max(messagingTemplatesSendCreateBodyIdentifiersOneDistinctIdMax)
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
})
