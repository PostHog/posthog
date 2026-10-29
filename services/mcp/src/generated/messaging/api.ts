/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 10 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

export const MessagingCategoriesListParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const MessagingCategoriesListQueryParams = () => zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

export const MessagingCategoriesCreateParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const messagingCategoriesCreateBodyKeyMax = 64

export const messagingCategoriesCreateBodyNameMax = 128

export const MessagingCategoriesCreateBody = () => zod.object({
    key: zod
        .string()
        .max(messagingCategoriesCreateBodyKeyMax)
        .describe(
            "Stable identifier for the category, unique within the project, for example `newsletter`. Opt-out lists and preference imports refer to categories by key. You can't change the key after creation."
        ),
    name: zod
        .string()
        .max(messagingCategoriesCreateBodyNameMax)
        .describe('Display name of the category, shown in the PostHog app.'),
    description: zod
        .string()
        .optional()
        .describe("Internal notes about which messages belong to this category. Recipients don't see it."),
    public_description: zod
        .string()
        .optional()
        .describe('Description that recipients see next to the category on the preferences page.'),
    category_type: zod
        .enum(['marketing', 'transactional'])
        .describe('\* `marketing` - Marketing\n\* `transactional` - Transactional')
        .optional()
        .describe(
            "`marketing` (the default): recipients can opt out of it, and sends skip recipients who did. `transactional`: for messages a recipient must get, such as receipts or password resets. Sends ignore opt-outs, and the category doesn't appear on the preferences page. Set `message_category_type` on a workflow message step to the type of its category.\n\n\* `marketing` - Marketing\n\* `transactional` - Transactional"
        ),
})

export const MessagingCategoriesRetrieveParams = () => zod.object({
    id: zod.string().describe('A UUID string identifying this message category.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const MessagingCategoriesPartialUpdateParams = () => zod.object({
    id: zod.string().describe('A UUID string identifying this message category.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const messagingCategoriesPartialUpdateBodyNameMax = 128

export const MessagingCategoriesPartialUpdateBody = () => zod.object({
    name: zod
        .string()
        .max(messagingCategoriesPartialUpdateBodyNameMax)
        .optional()
        .describe('Display name of the category, shown in the PostHog app.'),
    description: zod
        .string()
        .optional()
        .describe("Internal notes about which messages belong to this category. Recipients don't see it."),
    public_description: zod
        .string()
        .optional()
        .describe('Description that recipients see next to the category on the preferences page.'),
    category_type: zod
        .enum(['marketing', 'transactional'])
        .describe('\* `marketing` - Marketing\n\* `transactional` - Transactional')
        .optional()
        .describe(
            "`marketing` (the default): recipients can opt out of it, and sends skip recipients who did. `transactional`: for messages a recipient must get, such as receipts or password resets. Sends ignore opt-outs, and the category doesn't appear on the preferences page. Set `message_category_type` on a workflow message step to the type of its category.\n\n\* `marketing` - Marketing\n\* `transactional` - Transactional"
        ),
})

/**
 * Opt every recipient in the list out of the category named on their entry, or a default category.
 * @summary Add multiple recipients to the opt-out list
 */
export const MessagingPreferencesBulkAddOptOutsCreateParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const messagingPreferencesBulkAddOptOutsCreateBodyOptOutsItemIdentifierMax = 512

export const MessagingPreferencesBulkAddOptOutsCreateBody = () => zod.object({
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
 * Get opt-outs filtered by category or overall opt-outs if no category specified
 * @summary List recipients opted out of a message category
 */
export const MessagingPreferencesOptOutsRetrieveParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const messagingPreferencesOptOutsRetrieveQuerySearchMax = 512

export const MessagingPreferencesOptOutsRetrieveQueryParams = () => zod.object({
    category_key: zod
        .string()
        .optional()
        .describe(
            'Message category key to list opt-outs for. If omitted, lists recipients opted out of all marketing messages.'
        ),
    page: zod.number().optional(),
    page_size: zod.number().optional(),
    search: zod
        .string()
        .max(messagingPreferencesOptOutsRetrieveQuerySearchMax)
        .optional()
        .describe('Case-insensitive substring match on the recipient identifier.'),
})

/**
 * Opt a recipient back in to a specific category, or to all marketing messages.
 * @summary Remove a recipient from the opt-out list
 */
export const MessagingPreferencesRemoveOptOutCreateParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const messagingPreferencesRemoveOptOutCreateBodyIdentifierMax = 512

export const MessagingPreferencesRemoveOptOutCreateBody = () => zod.object({
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
 * Send a Supabase project's auth emails through transactional email templates.
 * @summary Get the Supabase auth email settings
 */
export const MessagingSupabaseAuthEmailsSettingsRetrieveParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * Send a Supabase project's auth emails through transactional email templates.
 * @summary Update the Supabase auth email settings
 */
export const MessagingSupabaseAuthEmailsSettingsPartialUpdateParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const messagingSupabaseAuthEmailsSettingsPartialUpdateBodySupabaseUrlMax = 200

export const messagingSupabaseAuthEmailsSettingsPartialUpdateBodyHookSecretMax = 500

export const MessagingSupabaseAuthEmailsSettingsPartialUpdateBody = () => zod.object({
    supabase_url: zod
        .string()
        .max(messagingSupabaseAuthEmailsSettingsPartialUpdateBodySupabaseUrlMax)
        .optional()
        .describe(
            "The Supabase project URL, such as https:\/\/abcdefgh.supabase.co, from the project's API settings in the Supabase dashboard. It must use https."
        ),
    hook_secret: zod
        .string()
        .max(messagingSupabaseAuthEmailsSettingsPartialUpdateBodyHookSecretMax)
        .optional()
        .describe(
            'The Send Email Hook secret, starting with v1,whsec_. Supabase generates it under Authentication, Hooks, Send Email hook. Leave it out to keep the stored secret.'
        ),
    templates: zod
        .record(zod.string(), zod.string())
        .optional()
        .describe(
            'Supabase email action type to the id of the email template that sends it. Each template must be transactional and marked sensitive. This replaces the whole mapping: include every type to keep, and leave a type out to unmap it. A core auth email with no template fails in Supabase, and a notification with no template is skipped. Valid action types: signup, invite, magiclink, email, recovery, email_change, reauthentication, password_changed_notification, email_changed_notification, phone_changed_notification, identity_linked_notification, identity_unlinked_notification, mfa_factor_enrolled_notification, mfa_factor_unenrolled_notification.'
        ),
})

/**
 * Create a transactional template for each core Supabase auth email that has no template yet, and map it. Needs a verified email sender.
 * @summary Create starter templates for the Supabase auth emails
 */
export const MessagingSupabaseAuthEmailsStarterTemplatesCreateParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})
