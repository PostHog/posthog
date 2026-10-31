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

/**
 * @summary Set the default project for the Slack workspace of a Slack app install
 */
export const SlackAppWorkspaceSetupDefaultProjectCreateBody = /* @__PURE__ */ zod.object({
    integration_id: zod
        .number()
        .describe('ID of the Slack integration of the project that becomes the workspace default.'),
})

/**
 * @summary Add PostHog to public channels of a Slack app install
 */
export const slackAppWorkspaceSetupJoinChannelsCreateBodyChannelIdsMax = 20

export const slackAppWorkspaceSetupJoinChannelsCreateBodyPostWelcomeDefault = false

export const SlackAppWorkspaceSetupJoinChannelsCreateBody = /* @__PURE__ */ zod.object({
    channel_ids: zod
        .array(zod.string())
        .min(1)
        .max(slackAppWorkspaceSetupJoinChannelsCreateBodyChannelIdsMax)
        .describe('IDs of the public channels that PostHog joins.'),
    post_welcome: zod
        .boolean()
        .default(slackAppWorkspaceSetupJoinChannelsCreateBodyPostWelcomeDefault)
        .describe('Whether PostHog posts its welcome message in each channel it joins. When false, it joins quietly.'),
})
