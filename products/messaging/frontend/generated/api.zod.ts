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
        .describe('* `marketing` - Marketing\n* `transactional` - Transactional'),
    deleted: zod.boolean().optional(),
})

/**
 * Import subscription topics and globally unsubscribed users from Customer.io API
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
        .describe('* `marketing` - Marketing\n* `transactional` - Transactional'),
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
        .describe('* `marketing` - Marketing\n* `transactional` - Transactional'),
    deleted: zod.boolean().optional(),
})

export const messagingTemplatesCreateBodyNameMax = 400

export const messagingTemplatesCreateBodyTypeMax = 24

export const MessagingTemplatesCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(messagingTemplatesCreateBodyNameMax),
    description: zod.string().optional(),
    content: zod
        .object({
            templating: zod.enum(['hog', 'liquid']).optional().describe('* `hog` - hog\n* `liquid` - liquid'),
            email: zod
                .object({
                    subject: zod.string().optional(),
                    text: zod.string().optional(),
                    html: zod.string().optional(),
                    design: zod.unknown().optional(),
                })
                .nullish(),
        })
        .optional(),
    type: zod.string().max(messagingTemplatesCreateBodyTypeMax).optional(),
    message_category: zod.uuid().nullish(),
    deleted: zod.boolean().optional(),
})
