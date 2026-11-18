/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 3 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * List the notification destinations of a warehouse alert.
 */
export const WarehouseAlertsDestinationsListParams = () => zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * Add a notification destination to a warehouse alert.
 */
export const WarehouseAlertsDestinationsCreateParams = () => zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const warehouseAlertsDestinationsCreateBodyPagerdutySeverityDefault = `critical`
export const warehouseAlertsDestinationsCreateBodyPagerdutyRegionDefault = `us`

export const WarehouseAlertsDestinationsCreateBody = () => zod.object({
    type: zod
        .enum(['slack', 'webhook', 'teams', 'discord', 'pagerduty'])
        .describe(
            '\* `slack` - slack\n\* `webhook` - webhook\n\* `teams` - teams\n\* `discord` - discord\n\* `pagerduty` - pagerduty'
        )
        .describe(
            'Notification destination type.\n\n\* `slack` - slack\n\* `webhook` - webhook\n\* `teams` - teams\n\* `discord` - discord\n\* `pagerduty` - pagerduty'
        ),
    event_kinds: zod
        .array(zod.enum(['firing', 'resolved']).describe('\* `firing` - firing\n\* `resolved` - resolved'))
        .min(1)
        .default([`firing`, `resolved`])
        .describe(
            'Which transitions send a message. A PagerDuty destination opens an incident when the alert fires and resolves it when the alert resolves, whatever this lists. Defaults to every kind.'
        ),
    slack_workspace_id: zod
        .number()
        .optional()
        .describe('Integration ID for the Slack workspace. Required when type=slack.'),
    slack_channel_id: zod.string().optional().describe('Slack channel ID. Required when type=slack.'),
    slack_channel_name: zod.string().optional().describe('Human-readable channel name for display.'),
    webhook_url: zod.url().optional().describe('HTTPS endpoint to post to. Required for webhook, teams and discord.'),
    pagerduty_routing_key: zod
        .string()
        .optional()
        .describe('Integration key of a PagerDuty Events API v2 integration. Required when type=pagerduty.'),
    pagerduty_severity: zod
        .enum(['critical', 'error', 'warning', 'info'])
        .describe('\* `critical` - critical\n\* `error` - error\n\* `warning` - warning\n\* `info` - info')
        .default(warehouseAlertsDestinationsCreateBodyPagerdutySeverityDefault)
        .describe(
            'Severity PagerDuty records on the incident. Used when type=pagerduty.\n\n\* `critical` - critical\n\* `error` - error\n\* `warning` - warning\n\* `info` - info'
        ),
    pagerduty_region: zod
        .enum(['us', 'eu'])
        .describe('\* `us` - us\n\* `eu` - eu')
        .default(warehouseAlertsDestinationsCreateBodyPagerdutyRegionDefault)
        .describe('PagerDuty service region of the account. Used when type=pagerduty.\n\n\* `us` - us\n\* `eu` - eu'),
})

/**
 * Delete notification destinations of a warehouse alert.
 */
export const WarehouseAlertsDestinationsDeleteCreateParams = () => zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const warehouseAlertsDestinationsDeleteCreateBodyDestinationIdsMax = 5

export const WarehouseAlertsDestinationsDeleteCreateBody = () => zod.object({
    destination_ids: zod
        .array(zod.string())
        .min(1)
        .max(warehouseAlertsDestinationsDeleteCreateBodyDestinationIdsMax)
        .describe("IDs of the alert's destinations to delete, as the list endpoint returns them."),
})
