/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 7 enabled ops
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
        .describe('Project-unique category key. Cannot be changed after creation.'),
    name: zod.string().max(messagingCategoriesCreateBodyNameMax).describe('Display name of the message category.'),
    description: zod.string().optional().describe('Internal description of the messages in this category.'),
    public_description: zod.string().optional().describe('Description shown to recipients in their preferences page.'),
    category_type: zod
        .enum(['marketing', 'transactional'])
        .describe('\* `marketing` - Marketing\n\* `transactional` - Transactional')
        .optional()
        .describe(
            'Marketing messages respect opt-outs; transactional messages bypass marketing opt-outs.\n\n\* `marketing` - Marketing\n\* `transactional` - Transactional'
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
        .describe('Display name of the message category.'),
    description: zod.string().optional().describe('Internal description of the messages in this category.'),
    public_description: zod.string().optional().describe('Description shown to recipients in their preferences page.'),
    category_type: zod
        .enum(['marketing', 'transactional'])
        .describe('\* `marketing` - Marketing\n\* `transactional` - Transactional')
        .optional()
        .describe(
            'Marketing messages respect opt-outs; transactional messages bypass marketing opt-outs.\n\n\* `marketing` - Marketing\n\* `transactional` - Transactional'
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
