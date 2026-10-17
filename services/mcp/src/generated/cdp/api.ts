/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 1 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

export const McpEventSubscriptionsPreviewParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const mcpEventSubscriptionsPreviewBodyFiltersOneSourceDefault = `events`

export const McpEventSubscriptionsPreviewBody = () => zod.object({
    project_id: zod.number().min(1).describe('Project whose captured events should be monitored.'),
    filters: zod
        .object({
            source: zod
                .enum(['events'])
                .describe('\* `events` - events')
                .default(mcpEventSubscriptionsPreviewBodyFiltersOneSourceDefault)
                .describe('Captured PostHog events. Use events.\n\n\* `events` - events'),
            actions: zod
                .array(zod.record(zod.string(), zod.unknown()))
                .optional()
                .describe(
                    'Saved action entries combined with the event entries using OR. Example: [{\"id\": \"123\", \"type\": \"actions\"}].'
                ),
            events: zod
                .array(zod.record(zod.string(), zod.unknown()))
                .optional()
                .describe(
                    'Captured event entries combined with OR. Example: [{\"id\": \"survey sent\", \"type\": \"events\", \"properties\": [{\"key\": \"rating\", \"type\": \"event\", \"operator\": \"lt\", \"value\": 3}]}].'
                ),
            properties: zod
                .array(zod.record(zod.string(), zod.unknown()))
                .optional()
                .describe(
                    'Property conditions applied to all selected events. Example: [{\"key\": \"plan\", \"type\": \"event\", \"operator\": \"exact\", \"value\": \"enterprise\"}].'
                ),
            filter_test_accounts: zod
                .boolean()
                .optional()
                .describe("Apply the project's existing test-account exclusions."),
        })
        .describe('Normal real-time destination filters. Preview the filters before subscribing.'),
})
