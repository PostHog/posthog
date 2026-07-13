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
 * Per-audience Slack destinations for the daily merged-PR digest.
 */
export const stamphogDigestChannelsCreateBodyAudienceKeyMax = 255

export const stamphogDigestChannelsCreateBodySlackIntegrationIdMin = -2147483648
export const stamphogDigestChannelsCreateBodySlackIntegrationIdMax = 2147483647

export const stamphogDigestChannelsCreateBodySlackChannelIdMax = 64

export const stamphogDigestChannelsCreateBodySlackChannelNameMax = 255

export const StamphogDigestChannelsCreateBody = /* @__PURE__ */ zod.object({
    audience_key: zod
        .string()
        .max(stamphogDigestChannelsCreateBodyAudienceKeyMax)
        .describe("Opaque digest bucket this channel receives, e.g. 'repo:PostHog\/posthog'."),
    slack_integration_id: zod
        .number()
        .min(stamphogDigestChannelsCreateBodySlackIntegrationIdMin)
        .max(stamphogDigestChannelsCreateBodySlackIntegrationIdMax)
        .describe("ID of the team's Slack integration used to post the digest."),
    slack_channel_id: zod
        .string()
        .max(stamphogDigestChannelsCreateBodySlackChannelIdMax)
        .describe("Slack channel ID to post the digest to, e.g. 'C012AB3CD'."),
    slack_channel_name: zod
        .string()
        .max(stamphogDigestChannelsCreateBodySlackChannelNameMax)
        .optional()
        .describe('Human-readable Slack channel name, for display only.'),
    enabled: zod.boolean().optional().describe('Whether this channel is included in the daily digest fan-out.'),
})

/**
 * Per-audience Slack destinations for the daily merged-PR digest.
 */
export const stamphogDigestChannelsUpdateBodyAudienceKeyMax = 255

export const stamphogDigestChannelsUpdateBodySlackIntegrationIdMin = -2147483648
export const stamphogDigestChannelsUpdateBodySlackIntegrationIdMax = 2147483647

export const stamphogDigestChannelsUpdateBodySlackChannelIdMax = 64

export const stamphogDigestChannelsUpdateBodySlackChannelNameMax = 255

export const StamphogDigestChannelsUpdateBody = /* @__PURE__ */ zod.object({
    audience_key: zod
        .string()
        .max(stamphogDigestChannelsUpdateBodyAudienceKeyMax)
        .describe("Opaque digest bucket this channel receives, e.g. 'repo:PostHog\/posthog'."),
    slack_integration_id: zod
        .number()
        .min(stamphogDigestChannelsUpdateBodySlackIntegrationIdMin)
        .max(stamphogDigestChannelsUpdateBodySlackIntegrationIdMax)
        .describe("ID of the team's Slack integration used to post the digest."),
    slack_channel_id: zod
        .string()
        .max(stamphogDigestChannelsUpdateBodySlackChannelIdMax)
        .describe("Slack channel ID to post the digest to, e.g. 'C012AB3CD'."),
    slack_channel_name: zod
        .string()
        .max(stamphogDigestChannelsUpdateBodySlackChannelNameMax)
        .optional()
        .describe('Human-readable Slack channel name, for display only.'),
    enabled: zod.boolean().optional().describe('Whether this channel is included in the daily digest fan-out.'),
})

/**
 * Per-audience Slack destinations for the daily merged-PR digest.
 */
export const stamphogDigestChannelsPartialUpdateBodyAudienceKeyMax = 255

export const stamphogDigestChannelsPartialUpdateBodySlackIntegrationIdMin = -2147483648
export const stamphogDigestChannelsPartialUpdateBodySlackIntegrationIdMax = 2147483647

export const stamphogDigestChannelsPartialUpdateBodySlackChannelIdMax = 64

export const stamphogDigestChannelsPartialUpdateBodySlackChannelNameMax = 255

export const StamphogDigestChannelsPartialUpdateBody = /* @__PURE__ */ zod.object({
    audience_key: zod
        .string()
        .max(stamphogDigestChannelsPartialUpdateBodyAudienceKeyMax)
        .optional()
        .describe("Opaque digest bucket this channel receives, e.g. 'repo:PostHog\/posthog'."),
    slack_integration_id: zod
        .number()
        .min(stamphogDigestChannelsPartialUpdateBodySlackIntegrationIdMin)
        .max(stamphogDigestChannelsPartialUpdateBodySlackIntegrationIdMax)
        .optional()
        .describe("ID of the team's Slack integration used to post the digest."),
    slack_channel_id: zod
        .string()
        .max(stamphogDigestChannelsPartialUpdateBodySlackChannelIdMax)
        .optional()
        .describe("Slack channel ID to post the digest to, e.g. 'C012AB3CD'."),
    slack_channel_name: zod
        .string()
        .max(stamphogDigestChannelsPartialUpdateBodySlackChannelNameMax)
        .optional()
        .describe('Human-readable Slack channel name, for display only.'),
    enabled: zod.boolean().optional().describe('Whether this channel is included in the daily digest fan-out.'),
})

/**
 * Per-repo stamphog settings — enable/disable review, GitHub App installation, policy overrides.
 */
export const stamphogRepoConfigsCreateBodyProviderMax = 32

export const stamphogRepoConfigsCreateBodyRepositoryMax = 255

export const stamphogRepoConfigsCreateBodyInstallationIdMax = 64

export const StamphogRepoConfigsCreateBody = /* @__PURE__ */ zod.object({
    provider: zod
        .string()
        .max(stamphogRepoConfigsCreateBodyProviderMax)
        .optional()
        .describe("SCM provider this config talks to. Defaults to 'github'."),
    repository: zod
        .string()
        .max(stamphogRepoConfigsCreateBodyRepositoryMax)
        .describe("Repository full name, e.g. 'PostHog\/posthog'."),
    enabled: zod.boolean().optional().describe('Whether stamphog actively reviews pull requests for this repo.'),
    installation_id: zod
        .string()
        .max(stamphogRepoConfigsCreateBodyInstallationIdMax)
        .describe('Provider app installation ID that authorizes API calls for this repo.'),
    digest_enabled: zod
        .boolean()
        .optional()
        .describe('Whether merged PRs on this repo are captured for the daily Slack digest.'),
})

/**
 * Per-repo stamphog settings — enable/disable review, GitHub App installation, policy overrides.
 */
export const stamphogRepoConfigsUpdateBodyProviderMax = 32

export const stamphogRepoConfigsUpdateBodyRepositoryMax = 255

export const stamphogRepoConfigsUpdateBodyInstallationIdMax = 64

export const StamphogRepoConfigsUpdateBody = /* @__PURE__ */ zod.object({
    provider: zod
        .string()
        .max(stamphogRepoConfigsUpdateBodyProviderMax)
        .optional()
        .describe("SCM provider this config talks to. Defaults to 'github'."),
    repository: zod
        .string()
        .max(stamphogRepoConfigsUpdateBodyRepositoryMax)
        .describe("Repository full name, e.g. 'PostHog\/posthog'."),
    enabled: zod.boolean().optional().describe('Whether stamphog actively reviews pull requests for this repo.'),
    installation_id: zod
        .string()
        .max(stamphogRepoConfigsUpdateBodyInstallationIdMax)
        .describe('Provider app installation ID that authorizes API calls for this repo.'),
    digest_enabled: zod
        .boolean()
        .optional()
        .describe('Whether merged PRs on this repo are captured for the daily Slack digest.'),
})

/**
 * Per-repo stamphog settings — enable/disable review, GitHub App installation, policy overrides.
 */
export const stamphogRepoConfigsPartialUpdateBodyProviderMax = 32

export const stamphogRepoConfigsPartialUpdateBodyRepositoryMax = 255

export const stamphogRepoConfigsPartialUpdateBodyInstallationIdMax = 64

export const StamphogRepoConfigsPartialUpdateBody = /* @__PURE__ */ zod.object({
    provider: zod
        .string()
        .max(stamphogRepoConfigsPartialUpdateBodyProviderMax)
        .optional()
        .describe("SCM provider this config talks to. Defaults to 'github'."),
    repository: zod
        .string()
        .max(stamphogRepoConfigsPartialUpdateBodyRepositoryMax)
        .optional()
        .describe("Repository full name, e.g. 'PostHog\/posthog'."),
    enabled: zod.boolean().optional().describe('Whether stamphog actively reviews pull requests for this repo.'),
    installation_id: zod
        .string()
        .max(stamphogRepoConfigsPartialUpdateBodyInstallationIdMax)
        .optional()
        .describe('Provider app installation ID that authorizes API calls for this repo.'),
    digest_enabled: zod
        .boolean()
        .optional()
        .describe('Whether merged PRs on this repo are captured for the daily Slack digest.'),
})
