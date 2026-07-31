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

export const ResolutionSourceEnumApi = zod
    .enum(['manual', 'slack_name_match', 'stamphog_config', 'owners_contact'])
    .describe(
        '\* `manual` - MANUAL\n\* `slack_name_match` - SLACK_NAME_MATCH\n\* `stamphog_config` - STAMPHOG_CONFIG\n\* `owners_contact` - OWNERS_CONTACT'
    )

export type ResolutionSourceEnumApi = zod.input<typeof ResolutionSourceEnumApi>
export type ResolutionSourceEnumApiOutput = zod.output<typeof ResolutionSourceEnumApi>

export const digestChannelApiAudienceKeyMax = 255

export const digestChannelApiSlackIntegrationIdMin = -2147483648
export const digestChannelApiSlackIntegrationIdMax = 2147483647

export const digestChannelApiSlackChannelIdMax = 64

export const digestChannelApiSlackChannelNameMax = 255

export const DigestChannelApi = zod.object({
    id: zod.uuid(),
    audience_key: zod
        .string()
        .max(digestChannelApiAudienceKeyMax)
        .describe(
            "Opaque digest bucket this channel receives, e.g. 'repo:PostHog\/posthog'. Immutable after creation — it anchors the audience and its opt-out tombstone."
        ),
    slack_integration_id: zod
        .number()
        .min(digestChannelApiSlackIntegrationIdMin)
        .max(digestChannelApiSlackIntegrationIdMax)
        .describe("ID of the team's Slack integration used to post the digest."),
    slack_channel_id: zod
        .string()
        .max(digestChannelApiSlackChannelIdMax)
        .describe("Slack channel ID to post the digest to, e.g. 'C012AB3CD'."),
    slack_channel_name: zod
        .string()
        .max(digestChannelApiSlackChannelNameMax)
        .optional()
        .describe('Human-readable Slack channel name, for display only.'),
    resolution_source: ResolutionSourceEnumApi.describe(
        "How this row was created: 'manual' (via this API), 'slack_name_match' (auto-provisioned because the workspace has a channel named exactly like the audience_key), 'stamphog_config' (auto-provisioned from the channel the repo declared under 'digest:' in .stamphog\/policy.yml), or 'owners_contact' (reserved for the future owners.yaml contact.slack step, not implemented yet).\n\n\* `manual` - MANUAL\n\* `slack_name_match` - SLACK_NAME_MATCH\n\* `stamphog_config` - STAMPHOG_CONFIG\n\* `owners_contact` - OWNERS_CONTACT"
    ),
    enabled: zod.boolean().optional().describe('Whether this channel is included in the daily digest fan-out.'),
    last_digest_at: zod.iso.datetime({ offset: true }).nullable(),
    created_at: zod.iso.datetime({ offset: true }),
    updated_at: zod.iso.datetime({ offset: true }),
})

export type DigestChannelApi = zod.input<typeof DigestChannelApi>
export type DigestChannelApiOutput = zod.output<typeof DigestChannelApi>

export const PaginatedDigestChannelListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(DigestChannelApi),
})

export type PaginatedDigestChannelListApi = zod.input<typeof PaginatedDigestChannelListApi>
export type PaginatedDigestChannelListApiOutput = zod.output<typeof PaginatedDigestChannelListApi>

export const patchedDigestChannelApiAudienceKeyMax = 255

export const patchedDigestChannelApiSlackIntegrationIdMin = -2147483648
export const patchedDigestChannelApiSlackIntegrationIdMax = 2147483647

export const patchedDigestChannelApiSlackChannelIdMax = 64

export const patchedDigestChannelApiSlackChannelNameMax = 255

export const PatchedDigestChannelApi = zod.object({
    id: zod.uuid().optional(),
    audience_key: zod
        .string()
        .max(patchedDigestChannelApiAudienceKeyMax)
        .optional()
        .describe(
            "Opaque digest bucket this channel receives, e.g. 'repo:PostHog\/posthog'. Immutable after creation — it anchors the audience and its opt-out tombstone."
        ),
    slack_integration_id: zod
        .number()
        .min(patchedDigestChannelApiSlackIntegrationIdMin)
        .max(patchedDigestChannelApiSlackIntegrationIdMax)
        .optional()
        .describe("ID of the team's Slack integration used to post the digest."),
    slack_channel_id: zod
        .string()
        .max(patchedDigestChannelApiSlackChannelIdMax)
        .optional()
        .describe("Slack channel ID to post the digest to, e.g. 'C012AB3CD'."),
    slack_channel_name: zod
        .string()
        .max(patchedDigestChannelApiSlackChannelNameMax)
        .optional()
        .describe('Human-readable Slack channel name, for display only.'),
    resolution_source: ResolutionSourceEnumApi.optional().describe(
        "How this row was created: 'manual' (via this API), 'slack_name_match' (auto-provisioned because the workspace has a channel named exactly like the audience_key), 'stamphog_config' (auto-provisioned from the channel the repo declared under 'digest:' in .stamphog\/policy.yml), or 'owners_contact' (reserved for the future owners.yaml contact.slack step, not implemented yet).\n\n\* `manual` - MANUAL\n\* `slack_name_match` - SLACK_NAME_MATCH\n\* `stamphog_config` - STAMPHOG_CONFIG\n\* `owners_contact` - OWNERS_CONTACT"
    ),
    enabled: zod.boolean().optional().describe('Whether this channel is included in the daily digest fan-out.'),
    last_digest_at: zod.iso.datetime({ offset: true }).nullish(),
    created_at: zod.iso.datetime({ offset: true }).optional(),
    updated_at: zod.iso.datetime({ offset: true }).optional(),
})

export type PatchedDigestChannelApi = zod.input<typeof PatchedDigestChannelApi>
export type PatchedDigestChannelApiOutput = zod.output<typeof PatchedDigestChannelApi>

export const DigestRunStatusEnumApi = zod
    .enum(['pending', 'completed', 'failed'])
    .describe('\* `pending` - PENDING\n\* `completed` - COMPLETED\n\* `failed` - FAILED')

export type DigestRunStatusEnumApi = zod.input<typeof DigestRunStatusEnumApi>
export type DigestRunStatusEnumApiOutput = zod.output<typeof DigestRunStatusEnumApi>

export const DigestRunApi = zod.object({
    id: zod.uuid(),
    digest_channel: zod.uuid().describe('ID of the digest channel this run belongs to.'),
    status: DigestRunStatusEnumApi.describe(
        'Current state of the digest run (pending, completed, failed).\n\n\* `pending` - PENDING\n\* `completed` - COMPLETED\n\* `failed` - FAILED'
    ),
    pr_count: zod.number().describe('Number of merged PRs included in the posted digest.'),
    slack_message_ts: zod.string().describe('Slack message timestamp of the posted digest, if posted.'),
    error: zod.string().describe('Error message if the run failed, blank otherwise.'),
    created_at: zod.iso.datetime({ offset: true }).describe('When the digest run was created.'),
    posted_at: zod.iso
        .datetime({ offset: true })
        .nullable()
        .describe('When the digest was posted to Slack, if it was.'),
})

export type DigestRunApi = zod.input<typeof DigestRunApi>
export type DigestRunApiOutput = zod.output<typeof DigestRunApi>

export const PaginatedDigestRunListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(DigestRunApi),
})

export type PaginatedDigestRunListApi = zod.input<typeof PaginatedDigestRunListApi>
export type PaginatedDigestRunListApiOutput = zod.output<typeof PaginatedDigestRunListApi>

export const StamphogPullRequestApi = zod.object({
    id: zod.uuid(),
    repository: zod.string().describe('Full name of the repository this pull request belongs to.'),
    pr_number: zod.number().describe('Pull request number on GitHub.'),
    title: zod.string().describe('Pull request title, refreshed on every relevant webhook delivery.'),
    author_login: zod.string().describe('GitHub login of the pull request author.'),
    pr_url: zod.string().describe('Full URL to the pull request on GitHub.'),
    head_branch: zod.string().describe('Branch name of the PR head.'),
    merged: zod.boolean().describe('Whether this pull request has merged (merged_at is set).'),
    merged_at: zod.iso
        .datetime({ offset: true })
        .nullable()
        .describe("When the pull request merged, null if it hasn't."),
    merge_commit_sha: zod.string().describe('Merge commit SHA, blank until the pull request merges.'),
    additions: zod.number().describe('Lines added, recorded when the pull request merges.'),
    deletions: zod.number().describe('Lines deleted, recorded when the pull request merges.'),
    changed_files: zod.number().describe('Files changed, recorded when the pull request merges.'),
    audience_key: zod
        .string()
        .describe('Digest bucket this merged PR belongs to; blank unless it was digest-eligible.'),
    digest_run: zod.uuid().nullable().describe('ID of the digest run that reported this merged PR, if any.'),
    created_at: zod.iso.datetime({ offset: true }).describe('When this pull request was first captured.'),
    updated_at: zod.iso.datetime({ offset: true }).describe('When this pull request was last updated.'),
})

export type StamphogPullRequestApi = zod.input<typeof StamphogPullRequestApi>
export type StamphogPullRequestApiOutput = zod.output<typeof StamphogPullRequestApi>

export const PaginatedStamphogPullRequestListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(StamphogPullRequestApi),
})

export type PaginatedStamphogPullRequestListApi = zod.input<typeof PaginatedStamphogPullRequestListApi>
export type PaginatedStamphogPullRequestListApiOutput = zod.output<typeof PaginatedStamphogPullRequestListApi>

export const ReviewModeEnumApi = zod.enum(['all', 'label']).describe('\* `all` - all\n\* `label` - label')

export type ReviewModeEnumApi = zod.input<typeof ReviewModeEnumApi>
export type ReviewModeEnumApiOutput = zod.output<typeof ReviewModeEnumApi>

export const stamphogRepoConfigApiProviderDefault = `github`
export const stamphogRepoConfigApiProviderMax = 32

export const stamphogRepoConfigApiRepositoryMax = 255

export const stamphogRepoConfigApiTriggerLabelMax = 100

export const StamphogRepoConfigApi = zod.object({
    id: zod.uuid(),
    provider: zod
        .string()
        .max(stamphogRepoConfigApiProviderMax)
        .default(stamphogRepoConfigApiProviderDefault)
        .describe("SCM provider this config talks to. Defaults to 'github'."),
    repository: zod
        .string()
        .max(stamphogRepoConfigApiRepositoryMax)
        .describe("Repository full name, e.g. 'PostHog\/posthog'."),
    enabled: zod.boolean().optional().describe('Whether stamphog actively reviews pull requests for this repo.'),
    installation_id: zod
        .string()
        .describe(
            'Provider app installation ID that authorizes API calls for this repo. Set only by the verified sync_installation flow; ignored on direct writes.'
        ),
    digest_enabled: zod
        .boolean()
        .optional()
        .describe('Whether merged PRs on this repo are captured for the daily Slack digest.'),
    review_mode: ReviewModeEnumApi.optional().describe(
        "When reviews run: 'all' reviews every pull request (the default); 'label' reviews only pull requests carrying the trigger label, mirroring the Action's opt-in flow.\n\n\* `all` - all\n\* `label` - label"
    ),
    trigger_label: zod
        .string()
        .max(stamphogRepoConfigApiTriggerLabelMax)
        .optional()
        .describe("Pull request label that triggers a review when review_mode is 'label'. Defaults to 'stamphog'."),
    created_at: zod.iso.datetime({ offset: true }),
    updated_at: zod.iso.datetime({ offset: true }),
})

export type StamphogRepoConfigApi = zod.input<typeof StamphogRepoConfigApi>
export type StamphogRepoConfigApiOutput = zod.output<typeof StamphogRepoConfigApi>

export const PaginatedStamphogRepoConfigListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(StamphogRepoConfigApi),
})

export type PaginatedStamphogRepoConfigListApi = zod.input<typeof PaginatedStamphogRepoConfigListApi>
export type PaginatedStamphogRepoConfigListApiOutput = zod.output<typeof PaginatedStamphogRepoConfigListApi>

export const patchedStamphogRepoConfigApiProviderDefault = `github`
export const patchedStamphogRepoConfigApiProviderMax = 32

export const patchedStamphogRepoConfigApiRepositoryMax = 255

export const patchedStamphogRepoConfigApiTriggerLabelMax = 100

export const PatchedStamphogRepoConfigApi = zod.object({
    id: zod.uuid().optional(),
    provider: zod
        .string()
        .max(patchedStamphogRepoConfigApiProviderMax)
        .default(patchedStamphogRepoConfigApiProviderDefault)
        .describe("SCM provider this config talks to. Defaults to 'github'."),
    repository: zod
        .string()
        .max(patchedStamphogRepoConfigApiRepositoryMax)
        .optional()
        .describe("Repository full name, e.g. 'PostHog\/posthog'."),
    enabled: zod.boolean().optional().describe('Whether stamphog actively reviews pull requests for this repo.'),
    installation_id: zod
        .string()
        .optional()
        .describe(
            'Provider app installation ID that authorizes API calls for this repo. Set only by the verified sync_installation flow; ignored on direct writes.'
        ),
    digest_enabled: zod
        .boolean()
        .optional()
        .describe('Whether merged PRs on this repo are captured for the daily Slack digest.'),
    review_mode: ReviewModeEnumApi.optional().describe(
        "When reviews run: 'all' reviews every pull request (the default); 'label' reviews only pull requests carrying the trigger label, mirroring the Action's opt-in flow.\n\n\* `all` - all\n\* `label` - label"
    ),
    trigger_label: zod
        .string()
        .max(patchedStamphogRepoConfigApiTriggerLabelMax)
        .optional()
        .describe("Pull request label that triggers a review when review_mode is 'label'. Defaults to 'stamphog'."),
    created_at: zod.iso.datetime({ offset: true }).optional(),
    updated_at: zod.iso.datetime({ offset: true }).optional(),
})

export type PatchedStamphogRepoConfigApi = zod.input<typeof PatchedStamphogRepoConfigApi>
export type PatchedStamphogRepoConfigApiOutput = zod.output<typeof PatchedStamphogRepoConfigApi>

export const StamphogInstallInfoApi = zod
    .object({
        app_slug: zod
            .string()
            .describe('URL-friendly slug of the dedicated Stamphog GitHub App, or blank if unconfigured.'),
        install_url: zod
            .string()
            .describe(
                "GitHub install URL (github.com\/apps\/<slug>\/installations\/new) the user opens to install the App, or blank if the App slug is unconfigured. Used for the genuinely-not-installed case; the primary 'Connect' button uses authorize_url instead."
            ),
        authorize_url: zod
            .string()
            .describe(
                "GitHub authorize URL (github.com\/login\/oauth\/authorize) the 'Connect' button opens. Authorize-first: an already-installed user is redirected straight back with an OAuth code (no installation_id), and sync_installation then discovers their installations server-side. Blank if the App client id is unconfigured."
            ),
    })
    .describe("Static info the frontend needs to render the 'Connect a repository' button.")

export type StamphogInstallInfoApi = zod.input<typeof StamphogInstallInfoApi>
export type StamphogInstallInfoApiOutput = zod.output<typeof StamphogInstallInfoApi>

export const stamphogSyncInstallationRequestApiInstallationIdDefault = ``

export const StamphogSyncInstallationRequestApi = zod
    .object({
        installation_id: zod
            .string()
            .default(stamphogSyncInstallationRequestApiInstallationIdDefault)
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

export type StamphogSyncInstallationRequestApi = zod.input<typeof StamphogSyncInstallationRequestApi>
export type StamphogSyncInstallationRequestApiOutput = zod.output<typeof StamphogSyncInstallationRequestApi>

export const StamphogDiscoveredInstallationApi = zod
    .object({
        id: zod.string().describe('GitHub installation id, as a string.'),
        account_login: zod.string().describe('Login of the org or user account the installation lives on.'),
    })
    .describe('One installation of the App the authorizing user can reach, offered for an explicit pick.')

export type StamphogDiscoveredInstallationApi = zod.input<typeof StamphogDiscoveredInstallationApi>
export type StamphogDiscoveredInstallationApiOutput = zod.output<typeof StamphogDiscoveredInstallationApi>

export const StamphogSyncInstallationResponseApi = zod
    .object({
        synced: zod
            .array(StamphogRepoConfigApi)
            .describe(
                'Repo configs now bound to this team for the installation (created this call or already present).'
            ),
        skipped: zod
            .array(zod.string())
            .describe('Repository full names skipped because another team already owns them under this installation.'),
        app_not_installed: zod
            .boolean()
            .describe(
                "True only on the discovery path (no installation_id) when the caller can reach no installation of this App — it isn't installed anywhere they can see. The frontend should route the user to the GitHub install page (install_url). Always false on the explicit installation_id path."
            ),
        installations: zod
            .array(StamphogDiscoveredInstallationApi)
            .describe(
                'Populated only on the discovery path when the caller can reach MORE than one installation of this App: nothing was bound, and the user must pick which installation to connect. The frontend re-runs the authorize flow and calls back with the chosen installation_id, which the explicit path verifies. Empty whenever a bind happened (or nothing was found).'
            ),
    })
    .describe('Result of syncing an installation: rows created\/kept for this team, plus conflicting repos skipped.')

export type StamphogSyncInstallationResponseApi = zod.input<typeof StamphogSyncInstallationResponseApi>
export type StamphogSyncInstallationResponseApiOutput = zod.output<typeof StamphogSyncInstallationResponseApi>

export const ReviewRunStatusEnumApi = zod
    .enum(['queued', 'gated', 'reviewing', 'completed', 'failed', 'superseded'])
    .describe(
        '\* `queued` - QUEUED\n\* `gated` - GATED\n\* `reviewing` - REVIEWING\n\* `completed` - COMPLETED\n\* `failed` - FAILED\n\* `superseded` - SUPERSEDED'
    )

export type ReviewRunStatusEnumApi = zod.input<typeof ReviewRunStatusEnumApi>
export type ReviewRunStatusEnumApiOutput = zod.output<typeof ReviewRunStatusEnumApi>

export const ReviewRunVerdictEnumApi = zod
    .enum(['none', 'approved', 'refused', 'escalate', 'wait', 'error'])
    .describe(
        '\* `none` - NONE\n\* `approved` - APPROVED\n\* `refused` - REFUSED\n\* `escalate` - ESCALATE\n\* `wait` - WAIT\n\* `error` - ERROR'
    )

export type ReviewRunVerdictEnumApi = zod.input<typeof ReviewRunVerdictEnumApi>
export type ReviewRunVerdictEnumApiOutput = zod.output<typeof ReviewRunVerdictEnumApi>

export const _GateResultSummaryApi = zod
    .object({
        gate_blocked: zod
            .boolean()
            .describe('Whether the deterministic gates blocked auto-review before the reviewer ran.'),
        final_verdict: zod.string().describe("The engine's raw final-verdict token, if the run reached a verdict."),
    })
    .describe(
        'Allowlisted, content-free slice of ``ReviewRun.gate_result``.\n\nThe raw gate blob nests ``gates``, ``classification``, and ``policy`` sub-objects that carry\nrepository content — changed-file paths (``safe_migration_files``, ``invalid_folder_files``),\nmanifest gate messages, and declared ``policy.scopes`` — which a project member without repo\naccess must not read. Only the terminal decision is exposed.'
    )

export type _GateResultSummaryApi = zod.input<typeof _GateResultSummaryApi>
export type _GateResultSummaryApiOutput = zod.output<typeof _GateResultSummaryApi>

export const _ReviewOutputSummaryApi = zod
    .object({
        stamphog_version: zod
            .string()
            .describe('Version of the stamphog engine that produced this review, if it reported one.'),
        reviewer_exit_code: zod
            .number()
            .describe('Exit code of the reviewer process in the sandbox, if the run reached the sandbox stage.'),
    })
    .describe(
        "Allowlisted, non-sensitive slice of ``ReviewRun.output``.\n\nThe raw ``output`` blob also holds the reviewer's stdout, the full PR payload, changed-file patches,\nand default-branch policy file contents — repository content a project member without repo access\nmust never read over the API. Only these derived, content-free fields are exposed."
    )

export type _ReviewOutputSummaryApi = zod.input<typeof _ReviewOutputSummaryApi>
export type _ReviewOutputSummaryApiOutput = zod.output<typeof _ReviewOutputSummaryApi>

export const ReviewRunApi = zod.object({
    id: zod.uuid(),
    pull_request: zod.uuid().describe('ID of the pull request this review run belongs to.'),
    repository: zod.string().describe('Full name of the repository this review run belongs to.'),
    pr_number: zod.number().describe('Pull request number on GitHub.'),
    pr_url: zod.string().describe('Full URL to the pull request on GitHub.'),
    head_sha: zod.string().describe('Commit SHA of the PR head at the time this run started.'),
    head_branch: zod.string().describe('Branch name of the PR head.'),
    delivery_id: zod
        .string()
        .nullable()
        .describe('GitHub webhook delivery ID that triggered this run, used for deduplication.'),
    status: ReviewRunStatusEnumApi.describe(
        "Current stage of the review run's lifecycle.\n\n\* `queued` - QUEUED\n\* `gated` - GATED\n\* `reviewing` - REVIEWING\n\* `completed` - COMPLETED\n\* `failed` - FAILED\n\* `superseded` - SUPERSEDED"
    ),
    verdict: ReviewRunVerdictEnumApi.describe(
        'Final verdict reached by the reviewer, if any.\n\n\* `none` - NONE\n\* `approved` - APPROVED\n\* `refused` - REFUSED\n\* `escalate` - ESCALATE\n\* `wait` - WAIT\n\* `error` - ERROR'
    ),
    gate_result: _GateResultSummaryApi.describe(
        'Allowlisted deterministic gate outcome (gate_blocked, final_verdict). The nested gate, classification, and policy sub-objects are excluded — they carry changed-file paths and policy scopes, repository content a project member without repo access must not read.'
    ),
    output: _ReviewOutputSummaryApi.describe(
        'Allowlisted, non-sensitive subset of the reviewer output blob (stamphog version, reviewer exit code). The raw reviewer stdout, PR payload, changed-file patches, and policy file contents are deliberately excluded — they carry repository content a project member without repo access must not read.'
    ),
    error: zod.string().describe('Error message if the run failed, blank otherwise.'),
    created_at: zod.iso.datetime({ offset: true }).describe('When the review run was created.'),
    updated_at: zod.iso.datetime({ offset: true }).describe('When the review run was last updated.'),
    completed_at: zod.iso
        .datetime({ offset: true })
        .nullable()
        .describe('When the review run reached a terminal state, if it has.'),
})

export type ReviewRunApi = zod.input<typeof ReviewRunApi>
export type ReviewRunApiOutput = zod.output<typeof ReviewRunApi>

export const PaginatedReviewRunListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(ReviewRunApi),
})

export type PaginatedReviewRunListApi = zod.input<typeof PaginatedReviewRunListApi>
export type PaginatedReviewRunListApiOutput = zod.output<typeof PaginatedReviewRunListApi>
