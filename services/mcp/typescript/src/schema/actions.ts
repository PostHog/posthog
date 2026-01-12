import { z } from 'zod'

// String matching options for action steps
export const ActionStepMatchingSchema = z.enum(['contains', 'exact', 'regex'])
export type ActionStepMatching = z.infer<typeof ActionStepMatchingSchema>

// Property filter for action steps
export const ActionPropertyFilterSchema = z.object({
    key: z.string().describe('Property key to filter on'),
    value: z.union([z.string(), z.number(), z.boolean(), z.array(z.string())]).describe('Value to match'),
    operator: z
        .enum([
            'exact',
            'is_not',
            'icontains',
            'not_icontains',
            'regex',
            'not_regex',
            'gt',
            'lt',
            'gte',
            'lte',
            'is_set',
            'is_not_set',
            'is_date_exact',
            'is_date_before',
            'is_date_after',
        ])
        .optional()
        .describe('Comparison operator'),
    type: z.enum(['event', 'person', 'element', 'cohort', 'group']).optional().describe('Property type'),
})

export type ActionPropertyFilter = z.infer<typeof ActionPropertyFilterSchema>

// Action step schema - matches ActionStepJSON from backend
export const ActionStepSchema = z.object({
    event: z
        .string()
        .nullish()
        .describe("Event name to match (e.g., '$pageview', '$autocapture', or custom event name)"),
    url: z.string().nullish().describe('URL to match (only for $pageview and $autocapture events)'),
    url_matching: ActionStepMatchingSchema.nullish().describe('URL matching mode'),
    selector: z.string().nullish().describe('CSS selector to match clicked elements (for $autocapture)'),
    tag_name: z.string().nullish().describe('HTML tag name to match (deprecated, use selector)'),
    text: z.string().nullish().describe('Text content to match on clicked elements'),
    text_matching: ActionStepMatchingSchema.nullish().describe('Text matching mode'),
    href: z.string().nullish().describe('Link href to match'),
    href_matching: ActionStepMatchingSchema.nullish().describe('Href matching mode'),
    properties: z.array(ActionPropertyFilterSchema).nullish().describe('Additional property filters'),
})

export type ActionStep = z.infer<typeof ActionStepSchema>

// Full action schema for API responses
export const ActionSchema = z.object({
    id: z.number(),
    name: z.string().nullable(),
    description: z.string().nullish(),
    steps: z.array(ActionStepSchema).nullish(),
    created_at: z.string(),
    created_by: z
        .object({
            id: z.number(),
            uuid: z.string(),
            email: z.string(),
            first_name: z.string().nullish(),
            last_name: z.string().nullish(),
        })
        .nullish(),
    deleted: z.boolean().nullish(),
    tags: z.array(z.string()).nullish(),
    pinned_at: z.string().nullish(),
    post_to_slack: z.boolean().nullish(),
    slack_message_format: z.string().nullish(),
    bytecode: z.array(z.any()).nullish(),
    bytecode_error: z.string().nullish(),
})

export type Action = z.infer<typeof ActionSchema>

// Simplified action for list view
export const SimpleActionSchema = z.object({
    id: z.number(),
    name: z.string().nullable(),
    description: z.string().nullish(),
    created_at: z.string(),
    tags: z.array(z.string()).nullish(),
    pinned_at: z.string().nullish(),
})

export type SimpleAction = z.infer<typeof SimpleActionSchema>

// Input schema for creating an action
export const CreateActionInputSchema = z.object({
    name: z.string().min(1).describe('Action name (must be unique within the project)'),
    description: z.string().optional().describe('Description of what this action tracks'),
    steps: z
        .array(ActionStepSchema)
        .min(1)
        .describe(
            'Match conditions for this action. Multiple steps use OR logic - an event matches if any step matches.'
        ),
    tags: z.array(z.string()).optional().describe('Tags for organizing actions'),
    post_to_slack: z.boolean().optional().describe('Send notification to Slack when action is triggered'),
    slack_message_format: z.string().optional().describe('Custom Slack message format'),
})

export type CreateActionInput = z.infer<typeof CreateActionInputSchema>

// Input schema for updating an action
export const UpdateActionInputSchema = z.object({
    name: z.string().optional().describe('Update action name'),
    description: z.string().optional().describe('Update description'),
    steps: z.array(ActionStepSchema).optional().describe('Update match conditions'),
    tags: z.array(z.string()).optional().describe('Update tags'),
    post_to_slack: z.boolean().optional().describe('Update Slack notification setting'),
    slack_message_format: z.string().optional().describe('Update Slack message format'),
})

export type UpdateActionInput = z.infer<typeof UpdateActionInputSchema>

// Input schema for listing actions
export const ListActionsInputSchema = z.object({
    limit: z.number().int().positive().optional().describe('Maximum number of actions to return'),
    offset: z.number().int().min(0).optional().describe('Number of actions to skip'),
    search: z.string().optional().describe('Search term to filter actions by name'),
})

export type ListActionsInput = z.infer<typeof ListActionsInputSchema>
