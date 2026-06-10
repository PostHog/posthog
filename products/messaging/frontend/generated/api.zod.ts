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
Persists the App API key in Integration(kind="customerio-app").
If no app_api_key is provided, reuses the stored Integration key.
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
Expected CSV columns: id, email, cio_subscription_preferences
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

Accepts:
  - site_id (optional): set on first creation only
  - api_key (optional): set on first creation only
  - region (optional): "us" or "eu", set on first creation only
  - track_enabled (required): enable or disable outbound sync
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

Accepts:
  - webhook_signing_secret (optional): set on first creation only
  - webhook_enabled (required): enable or disable the webhook
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

export const messagingTemplatesCreateBodyNameMax = 400

export const messagingTemplatesCreateBodyContentOneTemplatingDefault = `liquid`
export const messagingTemplatesCreateBodyTypeMax = 24

export const MessagingTemplatesCreateBody = /* @__PURE__ */ zod.object({
    name: zod
        .string()
        .max(messagingTemplatesCreateBodyNameMax)
        .describe('Human-readable template name shown in the library.'),
    description: zod.string().optional().describe('What the template is for and when to use it.'),
    content: zod
        .object({
            templating: zod
                .enum(['hog', 'liquid'])
                .describe('\* `hog` - hog\n\* `liquid` - liquid')
                .default(messagingTemplatesCreateBodyContentOneTemplatingDefault)
                .describe(
                    "Templating language for subject\/html\/text. Defaults to 'liquid'; hog treats braces as syntax.\n\n\* `hog` - hog\n\* `liquid` - liquid"
                ),
            email: zod
                .union([
                    zod.object({
                        subject: zod
                            .string()
                            .optional()
                            .describe(
                                'Email subject line. Supports Liquid templating. Required for email-type templates.'
                            ),
                        text: zod.string().optional().describe('Plain-text fallback body, sent alongside the HTML.'),
                        html: zod
                            .string()
                            .optional()
                            .describe(
                                'Full HTML document sent verbatim as the email body. Supports Liquid templating. When design is provided without html, the server renders html from the design.'
                            ),
                        design: zod
                            .record(zod.string(), zod.unknown())
                            .optional()
                            .describe(
                                'Unlayer design JSON — the source of truth for the visual editor. Sent without html, the server renders the email HTML from it.'
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
})

export const messagingTemplatesUpdateBodyNameMax = 400

export const messagingTemplatesUpdateBodyContentOneTemplatingDefault = `liquid`
export const messagingTemplatesUpdateBodyTypeMax = 24

export const MessagingTemplatesUpdateBody = /* @__PURE__ */ zod.object({
    name: zod
        .string()
        .max(messagingTemplatesUpdateBodyNameMax)
        .describe('Human-readable template name shown in the library.'),
    description: zod.string().optional().describe('What the template is for and when to use it.'),
    content: zod
        .object({
            templating: zod
                .enum(['hog', 'liquid'])
                .describe('\* `hog` - hog\n\* `liquid` - liquid')
                .default(messagingTemplatesUpdateBodyContentOneTemplatingDefault)
                .describe(
                    "Templating language for subject\/html\/text. Defaults to 'liquid'; hog treats braces as syntax.\n\n\* `hog` - hog\n\* `liquid` - liquid"
                ),
            email: zod
                .union([
                    zod.object({
                        subject: zod
                            .string()
                            .optional()
                            .describe(
                                'Email subject line. Supports Liquid templating. Required for email-type templates.'
                            ),
                        text: zod.string().optional().describe('Plain-text fallback body, sent alongside the HTML.'),
                        html: zod
                            .string()
                            .optional()
                            .describe(
                                'Full HTML document sent verbatim as the email body. Supports Liquid templating. When design is provided without html, the server renders html from the design.'
                            ),
                        design: zod
                            .record(zod.string(), zod.unknown())
                            .optional()
                            .describe(
                                'Unlayer design JSON — the source of truth for the visual editor. Sent without html, the server renders the email HTML from it.'
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
})

export const messagingTemplatesPartialUpdateBodyNameMax = 400

export const messagingTemplatesPartialUpdateBodyContentOneTemplatingDefault = `liquid`
export const messagingTemplatesPartialUpdateBodyTypeMax = 24

export const MessagingTemplatesPartialUpdateBody = /* @__PURE__ */ zod.object({
    name: zod
        .string()
        .max(messagingTemplatesPartialUpdateBodyNameMax)
        .optional()
        .describe('Human-readable template name shown in the library.'),
    description: zod.string().optional().describe('What the template is for and when to use it.'),
    content: zod
        .object({
            templating: zod
                .enum(['hog', 'liquid'])
                .describe('\* `hog` - hog\n\* `liquid` - liquid')
                .default(messagingTemplatesPartialUpdateBodyContentOneTemplatingDefault)
                .describe(
                    "Templating language for subject\/html\/text. Defaults to 'liquid'; hog treats braces as syntax.\n\n\* `hog` - hog\n\* `liquid` - liquid"
                ),
            email: zod
                .union([
                    zod.object({
                        subject: zod
                            .string()
                            .optional()
                            .describe(
                                'Email subject line. Supports Liquid templating. Required for email-type templates.'
                            ),
                        text: zod.string().optional().describe('Plain-text fallback body, sent alongside the HTML.'),
                        html: zod
                            .string()
                            .optional()
                            .describe(
                                'Full HTML document sent verbatim as the email body. Supports Liquid templating. When design is provided without html, the server renders html from the design.'
                            ),
                        design: zod
                            .record(zod.string(), zod.unknown())
                            .optional()
                            .describe(
                                'Unlayer design JSON — the source of truth for the visual editor. Sent without html, the server renders the email HTML from it.'
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
})
