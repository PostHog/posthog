/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
/**
 * * `manual` - MANUAL
 * * `slack_name_match` - SLACK_NAME_MATCH
 * * `stamphog_config` - STAMPHOG_CONFIG
 * * `owners_contact` - OWNERS_CONTACT
 */
export type ResolutionSourceEnumApi = (typeof ResolutionSourceEnumApi)[keyof typeof ResolutionSourceEnumApi]

export const ResolutionSourceEnumApi = {
    Manual: 'manual',
    SlackNameMatch: 'slack_name_match',
    StamphogConfig: 'stamphog_config',
    OwnersContact: 'owners_contact',
} as const

/**
 * * `pending` - PENDING
 * * `completed` - COMPLETED
 * * `failed` - FAILED
 */
export type DigestRunStatusEnumApi = (typeof DigestRunStatusEnumApi)[keyof typeof DigestRunStatusEnumApi]

export const DigestRunStatusEnumApi = {
    Pending: 'pending',
    Completed: 'completed',
    Failed: 'failed',
} as const

export interface DigestRunApi {
    readonly id: string
    /** Digest bucket this run drained, e.g. a team slug or 'repo:PostHog/posthog'. */
    readonly audience_key: string
    /** Slack channel this digest was posted to, e.g. 'C012AB3CD'. */
    readonly slack_channel_id: string
    /** Human-readable name of that channel, for display. */
    readonly slack_channel_name: string
    /** Why the digest went to this channel: 'slack_name_match' (no declaration anywhere, so the audience_key matched a same-named Slack channel), 'stamphog_config' (the channel the repo declared under 'digest:' in .stamphog/policy.yml), 'owners_contact' (a teams: entry in a root owners.yaml named it), or 'manual' (no longer produced).
     *
     * * `manual` - MANUAL
     * * `slack_name_match` - SLACK_NAME_MATCH
     * * `stamphog_config` - STAMPHOG_CONFIG
     * * `owners_contact` - OWNERS_CONTACT */
    readonly resolution_source: ResolutionSourceEnumApi
    /** Current state of the digest run (pending, completed, failed).
     *
     * * `pending` - PENDING
     * * `completed` - COMPLETED
     * * `failed` - FAILED */
    readonly status: DigestRunStatusEnumApi
    /** Number of merged PRs included in the posted digest. */
    readonly pr_count: number
    /** Slack message timestamp of the posted digest, if posted. */
    readonly slack_message_ts: string
    /** Error message if the run failed, blank otherwise. */
    readonly error: string
    /** When the digest run was created. */
    readonly created_at: string
    /**
     * When the digest was posted to Slack, if it was.
     * @nullable
     */
    readonly posted_at: string | null
}

export interface PaginatedDigestRunListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: DigestRunApi[]
}

export interface StamphogPullRequestApi {
    readonly id: string
    /** Full name of the repository this pull request belongs to. */
    readonly repository: string
    /** Pull request number on GitHub. */
    readonly pr_number: number
    /** Pull request title, refreshed on every relevant webhook delivery. */
    readonly title: string
    /** GitHub login of the pull request author. */
    readonly author_login: string
    /** Full URL to the pull request on GitHub. */
    readonly pr_url: string
    /** Branch name of the PR head. */
    readonly head_branch: string
    /** Whether this pull request has merged (merged_at is set). */
    readonly merged: boolean
    /**
     * When the pull request merged, null if it hasn't.
     * @nullable
     */
    readonly merged_at: string | null
    /** Merge commit SHA, blank until the pull request merges. */
    readonly merge_commit_sha: string
    /** Lines added, recorded when the pull request merges. */
    readonly additions: number
    /** Lines deleted, recorded when the pull request merges. */
    readonly deletions: number
    /** Files changed, recorded when the pull request merges. */
    readonly changed_files: number
    /** When this pull request was first captured. */
    readonly created_at: string
    /** When this pull request was last updated. */
    readonly updated_at: string
}

export interface PaginatedStamphogPullRequestListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: StamphogPullRequestApi[]
}

/**
 * * `all` - all
 * * `label` - label
 */
export type ReviewModeEnumApi = (typeof ReviewModeEnumApi)[keyof typeof ReviewModeEnumApi]

export const ReviewModeEnumApi = {
    All: 'all',
    Label: 'label',
} as const

export interface StamphogRepoConfigApi {
    readonly id: string
    /** SCM provider this config talks to. Defaults to 'github'. */
    provider?: string
    /** Repository full name, e.g. 'PostHog/posthog'. */
    repository: string
    /** Whether stamphog actively reviews pull requests for this repo. */
    enabled: boolean
    /** Provider app installation ID that authorizes API calls for this repo. Set only by the verified sync_installation flow; ignored on direct writes. */
    readonly installation_id: string
    /** Whether merged PRs on this repo are captured for the daily Slack digest. Requires 'enabled', since the digest reports what stamphog approved. */
    digest_enabled?: boolean
    /** When reviews run: 'all' reviews every pull request (the default); 'label' reviews only pull requests carrying the trigger label, mirroring the Action's opt-in flow.
     *
     * * `all` - all
     * * `label` - label */
    readonly review_mode: ReviewModeEnumApi
    /** Pull request label that triggers a review when review_mode is 'label'. Defaults to 'stamphog'. */
    trigger_label?: string
    readonly created_at: string
    readonly updated_at: string
}

export interface PaginatedStamphogRepoConfigListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: StamphogRepoConfigApi[]
}

/**
 * Input shape for creating/updating a repo config.
 *
 * Separate from the read serializer because the contract is an output shape: it carries a
 * required id, which a create request has no way to supply. Same split as visual_review's
 * input serializers.
 *
 * installation_id is deliberately absent: it may only ever be set by the verified
 * sync_installation flow, which proves the caller owns the installation before binding it. A
 * client-supplied value on this path is ignored, so a manually created config carries no
 * installation and simply won't resolve webhooks until synced.
 */
export interface StamphogRepoConfigWriteApi {
    /** SCM provider this config talks to. Defaults to 'github'. */
    provider?: string
    /** Repository full name, e.g. 'PostHog/posthog'. */
    repository: string
    /** Whether stamphog actively reviews pull requests for this repo. */
    enabled?: boolean
    /** Whether merged PRs on this repo are captured for the daily Slack digest. */
    digest_enabled?: boolean
    /** When reviews run: 'all' reviews every pull request (the default); 'label' reviews only pull requests carrying the trigger label, mirroring the Action's opt-in flow.
     *
     * * `all` - all
     * * `label` - label */
    review_mode?: ReviewModeEnumApi
    /** Pull request label that triggers a review when review_mode is 'label'. Defaults to 'stamphog'. */
    trigger_label?: string
}

/**
 * Input shape for creating/updating a repo config.
 *
 * Separate from the read serializer because the contract is an output shape: it carries a
 * required id, which a create request has no way to supply. Same split as visual_review's
 * input serializers.
 *
 * installation_id is deliberately absent: it may only ever be set by the verified
 * sync_installation flow, which proves the caller owns the installation before binding it. A
 * client-supplied value on this path is ignored, so a manually created config carries no
 * installation and simply won't resolve webhooks until synced.
 */
export interface PatchedStamphogRepoConfigWriteApi {
    /** SCM provider this config talks to. Defaults to 'github'. */
    provider?: string
    /** Repository full name, e.g. 'PostHog/posthog'. */
    repository?: string
    /** Whether stamphog actively reviews pull requests for this repo. */
    enabled?: boolean
    /** Whether merged PRs on this repo are captured for the daily Slack digest. */
    digest_enabled?: boolean
    /** When reviews run: 'all' reviews every pull request (the default); 'label' reviews only pull requests carrying the trigger label, mirroring the Action's opt-in flow.
     *
     * * `all` - all
     * * `label` - label */
    review_mode?: ReviewModeEnumApi
    /** Pull request label that triggers a review when review_mode is 'label'. Defaults to 'stamphog'. */
    trigger_label?: string
}

/**
 * Static info the frontend needs to render the 'Connect a repository' button.
 */
export interface StamphogInstallInfoApi {
    /** URL-friendly slug of the dedicated Stamphog GitHub App, or blank if unconfigured. */
    readonly app_slug: string
    /** GitHub install URL (github.com/apps/<slug>/installations/new) the user opens to install the App, or blank if the App slug is unconfigured. Used for the genuinely-not-installed case; the primary 'Connect' button uses authorize_url instead. */
    readonly install_url: string
    /** GitHub authorize URL (github.com/login/oauth/authorize) the 'Connect' button opens. Authorize-first: an already-installed user is redirected straight back with an OAuth code (no installation_id), and sync_installation then discovers their installations server-side. Blank if the App client id is unconfigured. */
    readonly authorize_url: string
}

/**
 * Request body for binding a GitHub App installation to the current team.
 *
 * Always requires the user-to-server OAuth ``code`` (the ownership proof) and the ``state`` token.
 * ``installation_id`` is optional: when present (the fresh-install redirect) exactly that installation
 * is verified and synced; when absent or blank (the authorize-first redirect) the caller's accessible
 * installations are discovered server-side from the code, so the client never has to supply a
 * forgeable id.
 */
export interface StamphogSyncInstallationRequestApi {
    /** GitHub App installation ID from the fresh-install Setup URL redirect. Optional: absent or blank means discover the caller's installations from the OAuth code instead (authorize-first flow). The id is not trusted on its own — ownership is always proven via the code. */
    installation_id?: string
    /** GitHub user-to-server OAuth code from the post-install redirect (present when the App has 'Request user authorization during installation' enabled). Exchanged server-side to prove the caller owns the installation before its repos are bound. */
    code: string
    /** Signed state token minted by install_info and round-tripped through GitHub's install redirect. Binds the callback to the team and user that started the flow, so a stolen installation_id + code can't be replayed against another team's session. */
    state: string
}

/**
 * One installation of the App the authorizing user can reach, offered for an explicit pick.
 */
export interface StamphogDiscoveredInstallationApi {
    /** GitHub installation id, as a string. */
    readonly id: string
    /** Login of the org or user account the installation lives on. */
    readonly account_login: string
}

/**
 * Result of syncing an installation: rows created/kept for this team, plus conflicting repos skipped.
 */
export interface StamphogSyncInstallationResponseApi {
    /** Repo configs now bound to this team for the installation (created this call or already present). */
    readonly synced: readonly StamphogRepoConfigApi[]
    /** Repository full names skipped because another team already owns them under this installation. */
    readonly skipped: readonly string[]
    /** True only on the discovery path (no installation_id) when the caller can reach no installation of this App — it isn't installed anywhere they can see. The frontend should route the user to the GitHub install page (install_url). Always false on the explicit installation_id path. */
    readonly app_not_installed: boolean
    /** Populated only on the discovery path when the caller can reach MORE than one installation of this App: nothing was bound, and the user must pick which installation to connect. The frontend re-runs the authorize flow and calls back with the chosen installation_id, which the explicit path verifies. Empty whenever a bind happened (or nothing was found). */
    readonly installations: readonly StamphogDiscoveredInstallationApi[]
}

/**
 * * `self_driving` - SELF_DRIVING
 * * `label` - LABEL
 * * `all` - ALL
 */
export type ReviewRunTriggerEnumApi = (typeof ReviewRunTriggerEnumApi)[keyof typeof ReviewRunTriggerEnumApi]

export const ReviewRunTriggerEnumApi = {
    SelfDriving: 'self_driving',
    Label: 'label',
    All: 'all',
} as const

/**
 * * `queued` - QUEUED
 * * `gated` - GATED
 * * `reviewing` - REVIEWING
 * * `completed` - COMPLETED
 * * `failed` - FAILED
 * * `superseded` - SUPERSEDED
 */
export type ReviewRunStatusEnumApi = (typeof ReviewRunStatusEnumApi)[keyof typeof ReviewRunStatusEnumApi]

export const ReviewRunStatusEnumApi = {
    Queued: 'queued',
    Gated: 'gated',
    Reviewing: 'reviewing',
    Completed: 'completed',
    Failed: 'failed',
    Superseded: 'superseded',
} as const

/**
 * * `none` - NONE
 * * `approved` - APPROVED
 * * `refused` - REFUSED
 * * `escalate` - ESCALATE
 * * `wait` - WAIT
 * * `error` - ERROR
 */
export type ReviewRunVerdictEnumApi = (typeof ReviewRunVerdictEnumApi)[keyof typeof ReviewRunVerdictEnumApi]

export const ReviewRunVerdictEnumApi = {
    None: 'none',
    Approved: 'approved',
    Refused: 'refused',
    Escalate: 'escalate',
    Wait: 'wait',
    Error: 'error',
} as const

/**
 * Allowlisted, content-free slice of ``ReviewRun.gate_result``.
 *
 * The raw gate blob nests ``gates``, ``classification``, and ``policy`` sub-objects that carry
 * repository content — changed-file paths (``safe_migration_files``, ``invalid_folder_files``),
 * manifest gate messages, and declared ``policy.scopes`` — which a project member without repo
 * access must not read. Only the terminal decision is exposed.
 */
export interface _GateResultSummaryApi {
    /** Whether the deterministic gates blocked auto-review before the reviewer ran. */
    readonly gate_blocked: boolean
    /** The engine's raw final-verdict token, if the run reached a verdict. */
    readonly final_verdict: string
}

/**
 * Allowlisted, non-sensitive slice of ``ReviewRun.output``.
 *
 * The raw ``output`` blob also holds the reviewer's stdout, the full PR payload, changed-file patches,
 * and default-branch policy file contents — repository content a project member without repo access
 * must never read. Only these derived, content-free fields are exposed.
 */
export interface _ReviewOutputSummaryApi {
    /** Version of the stamphog engine that produced this review, if it reported one. */
    readonly stamphog_version: string
    /** Exit code of the reviewer process in the sandbox, if the run reached the sandbox stage. */
    readonly reviewer_exit_code: number
}

export interface ReviewRunApi {
    readonly id: string
    /** ID of the pull request this review run belongs to. */
    readonly pull_request: string
    /** Full name of the repository this review run belongs to. */
    readonly repository: string
    /** Pull request number on GitHub. */
    readonly pr_number: number
    /** Full URL to the pull request on GitHub. */
    readonly pr_url: string
    /** Pull request title as of the last webhook delivery applied. */
    readonly title: string
    /** GitHub login of the pull request author. */
    readonly author_login: string
    /** Commit SHA of the PR head at the time this run started. */
    readonly head_sha: string
    /** Branch name of the PR head. */
    readonly head_branch: string
    /**
     * GitHub webhook delivery ID that triggered this run, used for deduplication.
     * @nullable
     */
    readonly delivery_id: string | null
    /** What caused this run to exist: self-driving inbox provenance, the repo's trigger label, or the repo reviewing every PR event.
     *
     * * `self_driving` - SELF_DRIVING
     * * `label` - LABEL
     * * `all` - ALL */
    readonly trigger: ReviewRunTriggerEnumApi
    /** Current stage of the review run's lifecycle.
     *
     * * `queued` - QUEUED
     * * `gated` - GATED
     * * `reviewing` - REVIEWING
     * * `completed` - COMPLETED
     * * `failed` - FAILED
     * * `superseded` - SUPERSEDED */
    readonly status: ReviewRunStatusEnumApi
    /** Final verdict reached by the reviewer, if any.
     *
     * * `none` - NONE
     * * `approved` - APPROVED
     * * `refused` - REFUSED
     * * `escalate` - ESCALATE
     * * `wait` - WAIT
     * * `error` - ERROR */
    readonly verdict: ReviewRunVerdictEnumApi
    /** Allowlisted deterministic gate outcome (gate_blocked, final_verdict). The nested gate, classification, and policy sub-objects are excluded — they carry changed-file paths and policy scopes, repository content a project member without repo access must not read. */
    readonly gate_result: _GateResultSummaryApi
    /** Allowlisted, non-sensitive subset of the reviewer output blob (stamphog version, reviewer exit code). The raw reviewer stdout, PR payload, changed-file patches, and policy file contents are deliberately excluded — they carry repository content a project member without repo access must not read. */
    readonly output: _ReviewOutputSummaryApi
    /** Error message if the run failed, blank otherwise. */
    readonly error: string
    /**
     * ID of the GitHub review this run posted, null if it never posted one.
     * @nullable
     */
    readonly posted_review_id: number | null
    /**
     * When this run's verdict reached GitHub, null if it never did.
     * @nullable
     */
    readonly verdict_posted_at: string | null
    /**
     * When this run's GitHub approval was retracted because the head moved, null if it wasn't.
     * @nullable
     */
    readonly approval_dismissed_at: string | null
    /** When the review run was created. */
    readonly created_at: string
    /** When the review run was last updated. */
    readonly updated_at: string
    /**
     * When the review run reached a terminal state, if it has.
     * @nullable
     */
    readonly completed_at: string | null
}

export interface PaginatedReviewRunListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: ReviewRunApi[]
}

export type StamphogDigestRunsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    /**
     * Filter by the Slack channel the digest was posted to, e.g. 'C012AB3CD'.
     */
    slack_channel_id?: string
}

export type StamphogPullRequestsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * Filter by merge state: true for merged pull requests, false for unmerged.
     */
    merged?: boolean
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    /**
     * Filter by pull request number.
     */
    pr_number?: number
}

export type StamphogRepoConfigsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type StamphogReviewRunsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    /**
     * Filter by pull request number.
     */
    pr_number?: number
    /**
     * Filter by repository full name, e.g. 'PostHog/posthog'.
     */
    repository?: string
    /**
     * Filter by review run status.
     */
    status?: string
    /**
     * Filter by what caused the run: self_driving, label, or all.
     */
    trigger?: StamphogReviewRunsListTrigger
}

export type StamphogReviewRunsListTrigger =
    (typeof StamphogReviewRunsListTrigger)[keyof typeof StamphogReviewRunsListTrigger]

export const StamphogReviewRunsListTrigger = {
    All: 'all',
    Label: 'label',
    SelfDriving: 'self_driving',
} as const
