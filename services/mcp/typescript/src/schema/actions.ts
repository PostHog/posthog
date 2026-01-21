import { z } from 'zod'

/**
 * Action schemas for the PostHog MCP server.
 *
 * Actions are reusable event definitions that combine multiple trigger conditions
 * (page views, clicks, form submissions, etc.) into a single trackable event.
 */

// Matching type for text/href/url matching
const MatchingTypeSchema = z.enum(['contains', 'regex', 'exact'])

// Property filter schema for filtering on event properties
const PropertyFilterSchema = z.object({
    key: z.string().describe('Property key'),
    value: z
        .union([z.string(), z.number(), z.boolean(), z.array(z.string()), z.array(z.number())])
        .describe('Property value to match'),
    operator: z
        .enum([
            'exact',
            'is_not',
            'is_set',
            'is_not_set',
            'icontains',
            'not_icontains',
            'regex',
            'not_regex',
            'gt',
            'gte',
            'lt',
            'lte',
        ])
        .optional()
        .describe('Comparison operator (default: exact)'),
    type: z.enum(['event', 'person']).optional().describe('Property type'),
})

// Action step schema - defines a single trigger condition
export const ActionStepInputSchema = z.object({
    event: z
        .string()
        .optional()
        .describe("Event name (e.g., '$pageview', '$autocapture', or custom event name)"),
    properties: z.array(PropertyFilterSchema).optional().describe('Event properties to filter on'),
    tag_name: z.string().optional().describe('HTML tag name to match (e.g., "button", "a", "input")'),
    text: z.string().optional().describe('Element text content to match'),
    text_matching: MatchingTypeSchema.optional().describe('How to match text (default: exact)'),
    href: z.string().optional().describe('Link href attribute to match'),
    href_matching: MatchingTypeSchema.optional().describe('How to match href (default: exact)'),
    selector: z.string().optional().describe('CSS selector to match element'),
    url: z.string().optional().describe('Page URL to match'),
    url_matching: MatchingTypeSchema.optional().describe('How to match URL (default: contains)'),
})

// Create action input schema
export const CreateActionInputSchema = z.object({
    name: z.string().min(1).describe('Name of the action (must be unique within the project)'),
    description: z.string().optional().describe('Description of what this action represents'),
    steps: z
        .array(ActionStepInputSchema)
        .min(1)
        .describe('Action steps - each step defines a trigger condition. Multiple steps are OR-ed together.'),
    tags: z.array(z.string()).optional().describe('Tags for organizing actions'),
    post_to_slack: z.boolean().default(false).optional().describe('Whether to post to Slack when this action is triggered'),
    slack_message_format: z.string().optional().describe('Custom Slack message format'),
})

// Update action input schema
export const UpdateActionInputSchema = z.object({
    name: z.string().min(1).optional().describe('Updated action name'),
    description: z.string().optional().nullable().describe('Updated description'),
    steps: z.array(ActionStepInputSchema).optional().describe('Updated action steps'),
    tags: z.array(z.string()).optional().describe('Updated tags'),
    post_to_slack: z.boolean().optional().describe('Whether to post to Slack'),
    slack_message_format: z.string().optional().describe('Custom Slack message format'),
    pinned_at: z.string().nullable().optional().describe('Pin timestamp (set to pin, null to unpin)'),
})

// List actions input schema
// Note: The PostHog Actions API does not support search filtering natively.
// Search is available via the global /api/projects/{project_id}/search/?q=&entities=action endpoint
export const ListActionsInputSchema = z.object({
    limit: z.number().int().positive().optional().describe('Maximum number of actions to return'),
    offset: z.number().int().min(0).optional().describe('Number of actions to skip for pagination'),
})

// Action response schema - permissive to handle API response variations
export const ActionResponseSchema = z
    .object({
        id: z.number(),
        name: z.string(),
        description: z.string().optional().nullable(),
        team_id: z.number(),
        steps: z.array(z.record(z.any())).optional().nullable(),
        tags: z.array(z.string()).optional().nullable(),
        post_to_slack: z.boolean().optional(),
        slack_message_format: z.string().optional().nullable(),
        deleted: z.boolean().optional(),
        pinned_at: z.string().optional().nullable(),
        created_at: z.string().optional(),
        created_by: z.record(z.any()).optional().nullable(),
        is_action: z.boolean().optional(),
        bytecode_error: z.string().optional().nullable(),
    })
    .passthrough() // Allow additional fields from API

// Export types for use in handlers
export type ActionStepInput = z.infer<typeof ActionStepInputSchema>
export type CreateActionInput = z.infer<typeof CreateActionInputSchema>
export type UpdateActionInput = z.infer<typeof UpdateActionInputSchema>
export type ListActionsInput = z.infer<typeof ListActionsInputSchema>
export type ActionResponse = z.infer<typeof ActionResponseSchema>
