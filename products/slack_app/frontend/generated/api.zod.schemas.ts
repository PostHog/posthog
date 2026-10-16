/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import { z as zod } from 'zod'

export const SlackAppWorkspaceSetupApi = zod.object({
    integration_id: zod.number().describe('ID of the Slack integration that this setup is for.'),
    slack_workspace_name: zod
        .string()
        .nullable()
        .describe('Name of the Slack workspace, as Slack sent it at install time.'),
    open_slack_url: zod
        .url()
        .nullable()
        .describe(
            "Link that opens the PostHog app's direct message in this Slack workspace. Null when the install has no app ID."
        ),
    steps: zod
        .array(zod.string())
        .describe('Keys of the setup steps that apply to this install and are not done yet, in display order.'),
})

export type SlackAppWorkspaceSetupApi = zod.input<typeof SlackAppWorkspaceSetupApi>
export type SlackAppWorkspaceSetupApiOutput = zod.output<typeof SlackAppWorkspaceSetupApi>
