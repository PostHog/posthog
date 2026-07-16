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
        .describe(
            "Opaque digest bucket this channel receives, e.g. 'repo:PostHog\/posthog'. Immutable after creation — it anchors the audience and its opt-out tombstone."
        ),
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
        .describe(
            "Opaque digest bucket this channel receives, e.g. 'repo:PostHog\/posthog'. Immutable after creation — it anchors the audience and its opt-out tombstone."
        ),
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
        .describe(
            "Opaque digest bucket this channel receives, e.g. 'repo:PostHog\/posthog'. Immutable after creation — it anchors the audience and its opt-out tombstone."
        ),
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
export const stamphogRepoConfigsCreateBodyProviderDefault = `github`
export const stamphogRepoConfigsCreateBodyProviderMax = 32

export const stamphogRepoConfigsCreateBodyRepositoryMax = 255

export const stamphogRepoConfigsCreateBodyTriggerLabelMax = 100

export const StamphogRepoConfigsCreateBody = /* @__PURE__ */ zod.object({
    provider: zod
        .string()
        .max(stamphogRepoConfigsCreateBodyProviderMax)
        .default(stamphogRepoConfigsCreateBodyProviderDefault)
        .describe("SCM provider this config talks to. Defaults to 'github'."),
    repository: zod
        .string()
        .max(stamphogRepoConfigsCreateBodyRepositoryMax)
        .describe("Repository full name, e.g. 'PostHog\/posthog'."),
    enabled: zod.boolean().optional().describe('Whether stamphog actively reviews pull requests for this repo.'),
    digest_enabled: zod
        .boolean()
        .optional()
        .describe('Whether merged PRs on this repo are captured for the daily Slack digest.'),
    review_mode: zod
        .enum(['all', 'label'])
        .describe('\* `all` - all\n\* `label` - label')
        .optional()
        .describe(
            "When reviews run: 'all' reviews every pull request (the default); 'label' reviews only pull requests carrying the trigger label, mirroring the Action's opt-in flow.\n\n\* `all` - all\n\* `label` - label"
        ),
    trigger_label: zod
        .string()
        .max(stamphogRepoConfigsCreateBodyTriggerLabelMax)
        .optional()
        .describe("Pull request label that triggers a review when review_mode is 'label'. Defaults to 'stamphog'."),
})

/**
 * Per-repo stamphog settings — enable/disable review, GitHub App installation, policy overrides.
 */
export const stamphogRepoConfigsUpdateBodyProviderDefault = `github`
export const stamphogRepoConfigsUpdateBodyProviderMax = 32

export const stamphogRepoConfigsUpdateBodyRepositoryMax = 255

export const stamphogRepoConfigsUpdateBodyTriggerLabelMax = 100

export const StamphogRepoConfigsUpdateBody = /* @__PURE__ */ zod.object({
    provider: zod
        .string()
        .max(stamphogRepoConfigsUpdateBodyProviderMax)
        .default(stamphogRepoConfigsUpdateBodyProviderDefault)
        .describe("SCM provider this config talks to. Defaults to 'github'."),
    repository: zod
        .string()
        .max(stamphogRepoConfigsUpdateBodyRepositoryMax)
        .describe("Repository full name, e.g. 'PostHog\/posthog'."),
    enabled: zod.boolean().optional().describe('Whether stamphog actively reviews pull requests for this repo.'),
    digest_enabled: zod
        .boolean()
        .optional()
        .describe('Whether merged PRs on this repo are captured for the daily Slack digest.'),
    review_mode: zod
        .enum(['all', 'label'])
        .describe('\* `all` - all\n\* `label` - label')
        .optional()
        .describe(
            "When reviews run: 'all' reviews every pull request (the default); 'label' reviews only pull requests carrying the trigger label, mirroring the Action's opt-in flow.\n\n\* `all` - all\n\* `label` - label"
        ),
    trigger_label: zod
        .string()
        .max(stamphogRepoConfigsUpdateBodyTriggerLabelMax)
        .optional()
        .describe("Pull request label that triggers a review when review_mode is 'label'. Defaults to 'stamphog'."),
})

/**
 * Per-repo stamphog settings — enable/disable review, GitHub App installation, policy overrides.
 */
export const stamphogRepoConfigsPartialUpdateBodyProviderDefault = `github`
export const stamphogRepoConfigsPartialUpdateBodyProviderMax = 32

export const stamphogRepoConfigsPartialUpdateBodyRepositoryMax = 255

export const stamphogRepoConfigsPartialUpdateBodyTriggerLabelMax = 100

export const StamphogRepoConfigsPartialUpdateBody = /* @__PURE__ */ zod.object({
    provider: zod
        .string()
        .max(stamphogRepoConfigsPartialUpdateBodyProviderMax)
        .default(stamphogRepoConfigsPartialUpdateBodyProviderDefault)
        .describe("SCM provider this config talks to. Defaults to 'github'."),
    repository: zod
        .string()
        .max(stamphogRepoConfigsPartialUpdateBodyRepositoryMax)
        .optional()
        .describe("Repository full name, e.g. 'PostHog\/posthog'."),
    enabled: zod.boolean().optional().describe('Whether stamphog actively reviews pull requests for this repo.'),
    digest_enabled: zod
        .boolean()
        .optional()
        .describe('Whether merged PRs on this repo are captured for the daily Slack digest.'),
    review_mode: zod
        .enum(['all', 'label'])
        .describe('\* `all` - all\n\* `label` - label')
        .optional()
        .describe(
            "When reviews run: 'all' reviews every pull request (the default); 'label' reviews only pull requests carrying the trigger label, mirroring the Action's opt-in flow.\n\n\* `all` - all\n\* `label` - label"
        ),
    trigger_label: zod
        .string()
        .max(stamphogRepoConfigsPartialUpdateBodyTriggerLabelMax)
        .optional()
        .describe("Pull request label that triggers a review when review_mode is 'label'. Defaults to 'stamphog'."),
})

/**
 * Per-repo stamphog settings — enable/disable review, GitHub App installation, policy overrides.
 */
export const StamphogRepoConfigsSyncInstallationCreateBody = /* @__PURE__ */ zod
    .object({
        installation_id: zod
            .string()
            .describe('GitHub App installation ID returned on the post-install Setup URL redirect.'),
        code: zod
            .string()
            .describe(
                "GitHub user-to-server OAuth code from the post-install redirect (present when the App has 'Request user authorization during installation' enabled). Exchanged server-side to prove the caller owns the installation before its repos are bound."
            ),
        state: zod
            .string()
            .describe(
                "Signed state token minted by install_info and round-tripped through GitHub's install redirect. Binds the callback to the team and user that started the flow, so a stolen installation_id + code can't be replayed against another team's session."
            ),
    })
    .describe(
        "Request body for binding a completed GitHub App installation to the current team.\n\nRequires both the ``installation_id`` and the user-to-server OAuth ``code`` from the post-install\nredirect: the code proves the caller actually owns the installation, without which any caller could\nbind another org's installation to their own team."
    )
