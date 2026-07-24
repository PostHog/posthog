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
