import { z } from 'zod'

const UrlMatchingEnum = z.enum(['contains', 'regex', 'exact'])

export const ActionStepJSONSchema = z.object({
    event: z
        .string()
        .nullish()
        .describe('Event name to match, e.g., "$autocapture", "$pageview", or custom event names'),
    properties: z
        .array(z.record(z.unknown()))
        .nullish()
        .describe('Event property filters to match against'),
    selector: z
        .string()
        .nullish()
        .describe('CSS selector to match elements, e.g., "[data-attr^=\'llm-\']", "button.submit"'),
    tag_name: z.string().nullish().describe('HTML tag name to match, e.g., "button", "a", "div"'),
    text: z.string().nullish().describe('Element text content to match'),
    text_matching: UrlMatchingEnum.nullish().describe('How to match text: contains, regex, or exact'),
    href: z.string().nullish().describe('Element href attribute to match (for links)'),
    href_matching: UrlMatchingEnum.nullish().describe('How to match href: contains, regex, or exact'),
    url: z.string().nullish().describe('Page URL to match'),
    url_matching: UrlMatchingEnum.nullish().describe('How to match URL: contains, regex, or exact (default: contains)'),
})

export const ActionSchema = z.object({
    id: z.number(),
    name: z.string().nullish(),
    description: z.string().optional(),
    tags: z.array(z.unknown()).optional(),
    post_to_slack: z.boolean().optional(),
    slack_message_format: z.string().optional(),
    steps: z.array(ActionStepJSONSchema).optional(),
    created_at: z.string(),
    created_by: z
        .object({
            id: z.number(),
            uuid: z.string(),
            distinct_id: z.string().nullish(),
            first_name: z.string().optional(),
            last_name: z.string().optional(),
            email: z.string(),
        })
        .passthrough(),
    deleted: z.boolean().optional(),
    is_calculating: z.boolean(),
    last_calculated_at: z.string().optional(),
    team_id: z.number(),
    is_action: z.boolean(),
    bytecode_error: z.string().nullable(),
    pinned_at: z.string().nullish(),
})

export const SimpleActionSchema = ActionSchema.pick({
    id: true,
    name: true,
    description: true,
    steps: true,
    created_at: true,
    deleted: true,
})

export const CreateActionInputSchema = z.object({
    name: z.string().min(1).describe('Action name - should clearly describe what event is being tracked'),
    description: z.string().optional().describe('Optional description of what this action tracks'),
    steps: z
        .array(ActionStepJSONSchema)
        .min(1)
        .describe('Array of matching rules - at least one step is required'),
    post_to_slack: z.boolean().optional().describe('Whether to post action events to Slack'),
    slack_message_format: z.string().optional().describe('Format for Slack messages if post_to_slack is true'),
    tags: z.array(z.string()).optional().describe('Tags for organizing actions'),
})

export const UpdateActionInputSchema = z.object({
    name: z.string().optional().describe('Update action name'),
    description: z.string().optional().describe('Update action description'),
    steps: z.array(ActionStepJSONSchema).optional().describe('Update matching rules'),
    post_to_slack: z.boolean().optional().describe('Update Slack posting setting'),
    slack_message_format: z.string().optional().describe('Update Slack message format'),
    tags: z.array(z.string()).optional().describe('Update tags'),
})

export const ListActionsSchema = z.object({
    limit: z.number().int().positive().optional().describe('Maximum number of actions to return'),
    offset: z.number().int().min(0).optional().describe('Number of actions to skip'),
    search: z.string().optional().describe('Search query to filter actions by name'),
})

export type ActionStepJSON = z.infer<typeof ActionStepJSONSchema>
export type Action = z.infer<typeof ActionSchema>
export type SimpleAction = z.infer<typeof SimpleActionSchema>
export type CreateActionInput = z.infer<typeof CreateActionInputSchema>
export type UpdateActionInput = z.infer<typeof UpdateActionInputSchema>
export type ListActionsData = z.infer<typeof ListActionsSchema>