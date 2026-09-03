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
 * Per-repo stamphog settings — enable/disable review, GitHub App installation, policy overrides.
 */
export const StamphogRepoConfigsCreateBody = /* @__PURE__ */ zod
    .object({
        provider: zod.string().optional().describe("SCM provider this config talks to. Defaults to 'github'."),
        repository: zod.string().describe("Repository full name, e.g. 'PostHog\/posthog'."),
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
            .optional()
            .describe("Pull request label that triggers a review when review_mode is 'label'. Defaults to 'stamphog'."),
    })
    .describe(
        "Input shape for creating\/updating a repo config.\n\nSeparate from the read serializer because the contract is an output shape: it carries a\nrequired id, which a create request has no way to supply. Same split as visual_review's\ninput serializers.\n\ninstallation_id is deliberately absent: it may only ever be set by the verified\nsync_installation flow, which proves the caller owns the installation before binding it. A\nclient-supplied value on this path is ignored, so a manually created config carries no\ninstallation and simply won't resolve webhooks until synced."
    )

/**
 * Per-repo stamphog settings — enable/disable review, GitHub App installation, policy overrides.
 */
export const StamphogRepoConfigsUpdateBody = /* @__PURE__ */ zod
    .object({
        provider: zod.string().optional().describe("SCM provider this config talks to. Defaults to 'github'."),
        repository: zod.string().describe("Repository full name, e.g. 'PostHog\/posthog'."),
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
            .optional()
            .describe("Pull request label that triggers a review when review_mode is 'label'. Defaults to 'stamphog'."),
    })
    .describe(
        "Input shape for creating\/updating a repo config.\n\nSeparate from the read serializer because the contract is an output shape: it carries a\nrequired id, which a create request has no way to supply. Same split as visual_review's\ninput serializers.\n\ninstallation_id is deliberately absent: it may only ever be set by the verified\nsync_installation flow, which proves the caller owns the installation before binding it. A\nclient-supplied value on this path is ignored, so a manually created config carries no\ninstallation and simply won't resolve webhooks until synced."
    )

/**
 * Per-repo stamphog settings — enable/disable review, GitHub App installation, policy overrides.
 */
export const StamphogRepoConfigsPartialUpdateBody = /* @__PURE__ */ zod
    .object({
        provider: zod.string().optional().describe("SCM provider this config talks to. Defaults to 'github'."),
        repository: zod.string().optional().describe("Repository full name, e.g. 'PostHog\/posthog'."),
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
            .optional()
            .describe("Pull request label that triggers a review when review_mode is 'label'. Defaults to 'stamphog'."),
    })
    .describe(
        "Input shape for creating\/updating a repo config.\n\nSeparate from the read serializer because the contract is an output shape: it carries a\nrequired id, which a create request has no way to supply. Same split as visual_review's\ninput serializers.\n\ninstallation_id is deliberately absent: it may only ever be set by the verified\nsync_installation flow, which proves the caller owns the installation before binding it. A\nclient-supplied value on this path is ignored, so a manually created config carries no\ninstallation and simply won't resolve webhooks until synced."
    )

/**
 * Per-repo stamphog settings — enable/disable review, GitHub App installation, policy overrides.
 */
export const stamphogRepoConfigsSyncInstallationCreateBodyInstallationIdDefault = ``

export const StamphogRepoConfigsSyncInstallationCreateBody = /* @__PURE__ */ zod
    .object({
        installation_id: zod
            .string()
            .default(stamphogRepoConfigsSyncInstallationCreateBodyInstallationIdDefault)
            .describe(
                "GitHub App installation ID from the fresh-install Setup URL redirect. Optional: absent or blank means discover the caller's installations from the OAuth code instead (authorize-first flow). The id is not trusted on its own — ownership is always proven via the code."
            ),
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
        "Request body for binding a GitHub App installation to the current team.\n\nAlways requires the user-to-server OAuth ``code`` (the ownership proof) and the ``state`` token.\n``installation_id`` is optional: when present (the fresh-install redirect) exactly that installation\nis verified and synced; when absent or blank (the authorize-first redirect) the caller's accessible\ninstallations are discovered server-side from the code, so the client never has to supply a\nforgeable id."
    )
