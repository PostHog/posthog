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
 * * `off` - Off
 * * `always` - Always
 * * `fallback` - When auto-approval does not approve
 */
export type RoutingModeEnumApi = (typeof RoutingModeEnumApi)[keyof typeof RoutingModeEnumApi]

export const RoutingModeEnumApi = {
    Off: 'off',
    Always: 'always',
    Fallback: 'fallback',
} as const

/**
 * * `waiting` - Waiting for auto-approval's verdict
 * * `routing` - Routing
 * * `requested` - Requested
 * * `done` - Done
 */
export type RoutingStatusEnumApi = (typeof RoutingStatusEnumApi)[keyof typeof RoutingStatusEnumApi]

export const RoutingStatusEnumApi = {
    Waiting: 'waiting',
    Routing: 'routing',
    Requested: 'requested',
    Done: 'done',
} as const

/**
 * * `full` - Every owner
 * * `pinned` - Pinned owners only
 */
export type RoutingScopeEnumApi = (typeof RoutingScopeEnumApi)[keyof typeof RoutingScopeEnumApi]

export const RoutingScopeEnumApi = {
    Full: 'full',
    Pinned: 'pinned',
} as const

export interface CodeReviewApprovalPullRequestRoutingApi {
    /** The phase of the latest routing record: 'waiting' (fallback mode, the head waits for auto-approval's verdict or the safety net), 'routing' (a task holds the claim and requested nobody yet), 'requested' (the review requests went out, the routing comment is not finished) or 'done'.
     *
     * * `waiting` - Waiting for auto-approval's verdict
     * * `routing` - Routing
     * * `requested` - Requested
     * * `done` - Done */
    readonly status: RoutingStatusEnumApi
    /** The repository's routing_mode when the record was written. Compare with the pull request's routing_mode.
     *
     * * `off` - Off
     * * `always` - Always
     * * `fallback` - When auto-approval does not approve */
    readonly mode: RoutingModeEnumApi
    /** 'full', or 'pinned' when an auto-approval asks only the owners of sensitive and new paths. Null while the record waits.
     *
     * * `full` - Every owner
     * * `pinned` - Pinned owners only */
    readonly scope: RoutingScopeEnumApi | null
    /** The head commit the record is for. It can be older than the pull request head. */
    readonly head_sha: string
    /** What started the record: 'opened', 'ready_for_review', 'verdict:<outcome>', 'external_review', 'approval_retracted' or 'safety_net'. */
    readonly trigger: string
    /** True when a 'routing' or 'requested' claim is older than the takeover limit. The task can still be alive, and a later delivery does not always finish an expired 'requested' claim. */
    readonly claim_expired: boolean
    /**
     * When the head started to wait for auto-approval's verdict. Null unless waiting.
     * @nullable
     */
    readonly waiting_since: string | null
    /**
     * When a task claimed the pull request for this record.
     * @nullable
     */
    readonly claimed_at: string | null
    /**
     * When the claim planned its requests. Null until the plan is saved.
     * @nullable
     */
    readonly routed_at: string | null
    /** The head that a full routing of this pull request requested owners for, blank if none. Fallback mode routes in full at most once per pull request. */
    readonly full_routed_head: string
    /** The latest approved head whose pinned owners were requested, blank if none. */
    readonly pinned_routed_head: string
}

export interface CodeReviewApprovalPullRequestApi {
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
    /** The repository's routing_mode now. 'off' means reviewer routing does not run for new events.
     *
     * * `off` - Off
     * * `always` - Always
     * * `fallback` - When auto-approval does not approve */
    readonly routing_mode: RoutingModeEnumApi
    /** The latest reviewer routing record of the pull request, or null when routing never wrote one: routing is off, the pull request is still a draft, or no routing event arrived yet. Use the routing runs list for the owners each run requested or cut. */
    readonly routing: CodeReviewApprovalPullRequestRoutingApi | null
    /** When this pull request was first captured. */
    readonly created_at: string
    /** When this pull request was last updated. */
    readonly updated_at: string
}

export interface PaginatedCodeReviewApprovalPullRequestListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: CodeReviewApprovalPullRequestApi[]
}

/**
 * * `all` - All pull requests
 * * `label` - Labeled pull requests
 */
export type ReviewModeEnumApi = (typeof ReviewModeEnumApi)[keyof typeof ReviewModeEnumApi]

export const ReviewModeEnumApi = {
    All: 'all',
    Label: 'label',
} as const

/**
 * On fork pull requests, routing adds the mapped label instead of requesting a review from the team, so an outside author cannot notify it. Keys are owners.yaml team slugs such as 'team-devex', values are GitHub label names. A team with no entry gets a review request as usual.
 */
export type CodeReviewApprovalRepositoryApiRoutingForkLabels = { [key: string]: string }

export interface CodeReviewApprovalRepositoryApi {
    readonly id: string
    /** SCM provider this config talks to. Defaults to 'github'. */
    provider?: string
    /** Repository full name, e.g. 'PostHog/posthog'. */
    repository: string
    /** Whether auto-approval actively reviews pull requests for this repo. */
    enabled: boolean
    /** Provider app installation ID that authorizes API calls for this repo. Set only by the verified sync_installation flow; ignored on direct writes. */
    readonly installation_id: string
    /** Whether merged PRs on this repo are captured for the daily Slack digest. Requires 'enabled', since the digest reports what auto-approval approved. */
    digest_enabled?: boolean
    /** When reviews run: 'label' reviews only pull requests carrying the trigger label (the default), mirroring the Action's opt-in flow; 'all' reviews every pull request.
     *
     * * `all` - All pull requests
     * * `label` - Labeled pull requests */
    readonly review_mode: ReviewModeEnumApi
    /** Pull request label that triggers a review when review_mode is 'label'. Defaults to 'stamphog'. */
    trigger_label?: string
    /** When auto-approval requests reviews from the code owners in the repository's owners.yaml: 'off' (the default) never; 'always' when a pull request opens ready for review or is marked ready; 'fallback' only when auto-approval does not approve, where an approval requests only the owners of sensitive and new paths.
     *
     * * `off` - Off
     * * `always` - Always
     * * `fallback` - When auto-approval does not approve */
    readonly routing_mode: RoutingModeEnumApi
    /** On fork pull requests, routing adds the mapped label instead of requesting a review from the team, so an outside author cannot notify it. Keys are owners.yaml team slugs such as 'team-devex', values are GitHub label names. A team with no entry gets a review request as usual. */
    readonly routing_fork_labels: CodeReviewApprovalRepositoryApiRoutingForkLabels
    /** Whether a clean PostHog Review run on a pull request that opened or was marked ready starts a silent auto-approval review of that head, whatever review_mode says. A silent review posts only an approval: any other verdict is stored and nothing is written to the pull request. Only for review_mode 'label' in a repository where PostHog Review runs automatic reviews: 'all' refuses it, and setting review_mode to 'all' turns it off. With routing_mode 'fallback', a head waits for that silent review before routing. Defaults to false. */
    readonly review_on_clean_external_review: boolean
    /**
     * The caller's access level on the code review auto-approval resource, resolved for the team that owns this row. 'editor' can turn reviews on. 'manager' is required to turn them off or to change review_mode, trigger_label, routing_mode, routing_fork_labels or review_on_clean_external_review.
     * @nullable
     */
    readonly user_access_level: string | null
    readonly created_at: string
    readonly updated_at: string
}

export interface PaginatedCodeReviewApprovalRepositoryListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: CodeReviewApprovalRepositoryApi[]
}

/**
 * On fork pull requests, routing adds the mapped label instead of requesting a review from the team, so an outside author cannot notify it. Keys are owners.yaml team slugs such as 'team-devex', values are GitHub label names. A team with no entry gets a review request as usual. Sending the field replaces the whole map, and an empty object removes every label.
 */
export type CodeReviewApprovalRepositoryWriteApiRoutingForkLabels = { [key: string]: string }

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
export interface CodeReviewApprovalRepositoryWriteApi {
    /** SCM provider this config talks to. Defaults to 'github'. Set on create only, an update ignores it. */
    provider?: string
    /** Repository full name, e.g. 'PostHog/posthog'. Set on create only, an update ignores it. */
    repository: string
    /** Whether auto-approval actively reviews pull requests for this repo. */
    enabled?: boolean
    /** Whether merged PRs on this repo are captured for the daily Slack digest. */
    digest_enabled?: boolean
    /** When reviews run: 'label' reviews only pull requests carrying the trigger label (the default), mirroring the Action's opt-in flow; 'all' reviews every pull request.
     *
     * * `all` - All pull requests
     * * `label` - Labeled pull requests */
    review_mode?: ReviewModeEnumApi
    /** Pull request label that triggers a review when review_mode is 'label'. Defaults to 'stamphog'. */
    trigger_label?: string
    /** When auto-approval requests reviews from the code owners in the repository's owners.yaml: 'off' (the default) never; 'always' when a pull request opens ready for review or is marked ready; 'fallback' only when auto-approval does not approve, where an approval requests only the owners of sensitive and new paths.
     *
     * * `off` - Off
     * * `always` - Always
     * * `fallback` - When auto-approval does not approve */
    routing_mode?: RoutingModeEnumApi
    /** On fork pull requests, routing adds the mapped label instead of requesting a review from the team, so an outside author cannot notify it. Keys are owners.yaml team slugs such as 'team-devex', values are GitHub label names. A team with no entry gets a review request as usual. Sending the field replaces the whole map, and an empty object removes every label. */
    routing_fork_labels?: CodeReviewApprovalRepositoryWriteApiRoutingForkLabels
    /** Whether a clean PostHog Review run on a pull request that opened or was marked ready starts a silent auto-approval review of that head, whatever review_mode says. A silent review posts only an approval: any other verdict is stored and nothing is written to the pull request. Only for review_mode 'label' in a repository where PostHog Review runs automatic reviews: 'all' refuses it, and setting review_mode to 'all' turns it off. With routing_mode 'fallback', a head waits for that silent review before routing. Defaults to false. */
    review_on_clean_external_review?: boolean
}

/**
 * On fork pull requests, routing adds the mapped label instead of requesting a review from the team, so an outside author cannot notify it. Keys are owners.yaml team slugs such as 'team-devex', values are GitHub label names. A team with no entry gets a review request as usual. Sending the field replaces the whole map, and an empty object removes every label.
 */
export type PatchedCodeReviewApprovalRepositoryWriteApiRoutingForkLabels = { [key: string]: string }

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
export interface PatchedCodeReviewApprovalRepositoryWriteApi {
    /** SCM provider this config talks to. Defaults to 'github'. Set on create only, an update ignores it. */
    provider?: string
    /** Repository full name, e.g. 'PostHog/posthog'. Set on create only, an update ignores it. */
    repository?: string
    /** Whether auto-approval actively reviews pull requests for this repo. */
    enabled?: boolean
    /** Whether merged PRs on this repo are captured for the daily Slack digest. */
    digest_enabled?: boolean
    /** When reviews run: 'label' reviews only pull requests carrying the trigger label (the default), mirroring the Action's opt-in flow; 'all' reviews every pull request.
     *
     * * `all` - All pull requests
     * * `label` - Labeled pull requests */
    review_mode?: ReviewModeEnumApi
    /** Pull request label that triggers a review when review_mode is 'label'. Defaults to 'stamphog'. */
    trigger_label?: string
    /** When auto-approval requests reviews from the code owners in the repository's owners.yaml: 'off' (the default) never; 'always' when a pull request opens ready for review or is marked ready; 'fallback' only when auto-approval does not approve, where an approval requests only the owners of sensitive and new paths.
     *
     * * `off` - Off
     * * `always` - Always
     * * `fallback` - When auto-approval does not approve */
    routing_mode?: RoutingModeEnumApi
    /** On fork pull requests, routing adds the mapped label instead of requesting a review from the team, so an outside author cannot notify it. Keys are owners.yaml team slugs such as 'team-devex', values are GitHub label names. A team with no entry gets a review request as usual. Sending the field replaces the whole map, and an empty object removes every label. */
    routing_fork_labels?: PatchedCodeReviewApprovalRepositoryWriteApiRoutingForkLabels
    /** Whether a clean PostHog Review run on a pull request that opened or was marked ready starts a silent auto-approval review of that head, whatever review_mode says. A silent review posts only an approval: any other verdict is stored and nothing is written to the pull request. Only for review_mode 'label' in a repository where PostHog Review runs automatic reviews: 'all' refuses it, and setting review_mode to 'all' turns it off. With routing_mode 'fallback', a head waits for that silent review before routing. Defaults to false. */
    review_on_clean_external_review?: boolean
}

/**
 * * `found` - Found
 * * `missing` - Missing
 * * `unavailable` - Unavailable
 */
export type OwnersFileStatusEnumApi = (typeof OwnersFileStatusEnumApi)[keyof typeof OwnersFileStatusEnumApi]

export const OwnersFileStatusEnumApi = {
    Found: 'found',
    Missing: 'missing',
    Unavailable: 'unavailable',
} as const

/**
 * Whether a repository can use reviewer requests, which read ownership from its owners.yaml.
 */
export interface CodeReviewApprovalOwnersFileApi {
    /** Whether the default branch has a root owners.yaml: 'found', 'missing', or 'unavailable' when the check could not ask GitHub (no installation, or GitHub answered with an error).
     *
     * * `found` - Found
     * * `missing` - Missing
     * * `unavailable` - Unavailable */
    owners_file: OwnersFileStatusEnumApi
}

/**
 * Request body for turning reviews on for a repository from a connected installation.
 */
export interface CodeReviewApprovalAddRepositoryApi {
    /** Repository full name, e.g. 'PostHog/posthog'. It must be in one of the project's connected GitHub installations, as available_repositories lists them. A repository the project already has is turned back on. */
    repository: string
}

/**
 * Repositories from the team's connected GitHub installations that are not added to auto-approval yet.
 */
export interface CodeReviewApprovalAvailableRepositoriesApi {
    /** Repository full names the team can add, sorted by name and capped by limit. Only repositories a project member proved access to on GitHub are listed, and never one another project already holds under the same installation. */
    readonly repositories: readonly string[]
    /** How many repositories match the search in total, before limit applies. */
    readonly total_count: number
    /** Whether a project member connected a GitHub installation yet. False means GitHub must be connected before any repository can be added. True with a total_count of 0 and no search means no repository is left to add. */
    readonly has_installation: boolean
}

/**
 * Static info the frontend needs to render the 'Connect a repository' button.
 */
export interface CodeReviewApprovalInstallInfoApi {
    /** URL-friendly slug of the Stamphog GitHub app, or blank if unconfigured. */
    readonly app_slug: string
    /** GitHub install URL (github.com/apps/<slug>/installations/new) the 'Connect' button opens. The user picks a GitHub account there and chooses which repositories the App can reach, including an account where the App is already installed. Blank if the App slug is unconfigured. */
    readonly install_url: string
    /** GitHub authorize URL (github.com/login/oauth/authorize). GitHub's redirect after configuring an existing installation carries no OAuth code, so the client passes through this URL once: an installed App redirects straight back with a code, which sync_installation uses to prove ownership. Blank if the App client id is unconfigured. */
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
export interface CodeReviewApprovalSyncInstallationRequestApi {
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
export interface CodeReviewApprovalDiscoveredInstallationApi {
    /** GitHub installation id, as a string. */
    readonly id: string
    /** Login of the org or user account the installation lives on. */
    readonly account_login: string
}

/**
 * Result of syncing an installation: the team's rows bound to it, and what the team can add now.
 */
export interface CodeReviewApprovalSyncInstallationResponseApi {
    /** Repo configs this team already had for the installation's repositories, now bound to it. A sync creates no repo config: use add_repository to turn reviews on for a repository. */
    readonly synced: readonly CodeReviewApprovalRepositoryApi[]
    /** Repository full names skipped because another team already owns them under this installation. */
    readonly skipped: readonly string[]
    /** How many repositories this team can add after the sync, across all its connected installations. List them with available_repositories. */
    readonly available_count: number
    /** True only on the discovery path (no installation_id) when the caller can reach no installation of this App — it isn't installed anywhere they can see. The frontend should route the user to the GitHub install page (install_url). Always false on the explicit installation_id path. */
    readonly app_not_installed: boolean
    /** Populated only on the discovery path when the caller can reach MORE than one installation of this App: nothing was bound, and the user must pick which installation to connect. The frontend re-runs the authorize flow and calls back with the chosen installation_id, which the explicit path verifies. Empty whenever a bind happened (or nothing was found). */
    readonly installations: readonly CodeReviewApprovalDiscoveredInstallationApi[]
}

/**
 * * `single_candidate` - Single candidate
 * * `fork` - Fork
 * * `nothing_cuttable` - Nothing cuttable
 * * `no_answer` - No answer
 * * `stamphog_approved` - Auto-approved
 * * `files_truncated` - Files truncated
 */
export type LlmSkipReasonEnumApi = (typeof LlmSkipReasonEnumApi)[keyof typeof LlmSkipReasonEnumApi]

export const LlmSkipReasonEnumApi = {
    SingleCandidate: 'single_candidate',
    Fork: 'fork',
    NothingCuttable: 'nothing_cuttable',
    NoAnswer: 'no_answer',
    StamphogApproved: 'stamphog_approved',
    FilesTruncated: 'files_truncated',
} as const

/**
 * * `requested` - Requested
 * * `labeled` - Labeled
 * * `refused` - Refused by GitHub
 * * `cut` - Cut
 * * `not_requested` - Not requested
 * * `already_requested` - Already requested
 */
export type RoutingOwnerOutcomeEnumApi = (typeof RoutingOwnerOutcomeEnumApi)[keyof typeof RoutingOwnerOutcomeEnumApi]

export const RoutingOwnerOutcomeEnumApi = {
    Requested: 'requested',
    Labeled: 'labeled',
    Refused: 'refused',
    Cut: 'cut',
    NotRequested: 'not_requested',
    AlreadyRequested: 'already_requested',
} as const

/**
 * * `sensitive` - Owns a sensitive path
 * * `new_path` - Owns a new path
 * * `largest_owner` - Has the largest part
 * * `diff_not_seen` - Diff not shown to the model
 * * `cut_skipped` - Cut step skipped
 * * `model_kept` - Kept by the model
 * * `model_cut` - Cut by the model
 * * `stamphog_approved` - Auto-approved
 */
export type RoutingOwnerReasonEnumApi = (typeof RoutingOwnerReasonEnumApi)[keyof typeof RoutingOwnerReasonEnumApi]

export const RoutingOwnerReasonEnumApi = {
    Sensitive: 'sensitive',
    NewPath: 'new_path',
    LargestOwner: 'largest_owner',
    DiffNotSeen: 'diff_not_seen',
    CutSkipped: 'cut_skipped',
    ModelKept: 'model_kept',
    ModelCut: 'model_cut',
    StamphogApproved: 'stamphog_approved',
} as const

/**
 * * `sensitive` - Sensitive path
 * * `new_path` - New path
 */
export type PinReasonEnumApi = (typeof PinReasonEnumApi)[keyof typeof PinReasonEnumApi]

export const PinReasonEnumApi = {
    Sensitive: 'sensitive',
    NewPath: 'new_path',
} as const

export interface CodeReviewApprovalRoutingPinApi {
    /** Why the path pins its owner.
     *
     * * `sensitive` - Sensitive path
     * * `new_path` - New path */
    readonly reason: PinReasonEnumApi
    /** The changed path, or the new directory, that pinned the owner. */
    path: string
}

/**
 * * `team` - Team
 * * `person` - Person
 */
export type OwnerKindEnumApi = (typeof OwnerKindEnumApi)[keyof typeof OwnerKindEnumApi]

export const OwnerKindEnumApi = {
    Team: 'team',
    Person: 'person',
} as const

export interface CodeReviewApprovalRoutingRunOwnerApi {
    /** What the run did with the owner: 'requested', 'labeled' (a fork label instead of a request), 'refused' (GitHub refused the request or the label), 'cut', 'not_requested' (auto-approval approved, and routing would have asked this owner without the approval; on an older run whose llm_skipped is 'stamphog_approved' it means only that the owner owns changed code) or 'already_requested' (an earlier run asked this pinned owner).
     *
     * * `requested` - Requested
     * * `labeled` - Labeled
     * * `refused` - Refused by GitHub
     * * `cut` - Cut
     * * `not_requested` - Not requested
     * * `already_requested` - Already requested */
    readonly outcome: RoutingOwnerOutcomeEnumApi
    /** Why: 'sensitive' or 'new_path' (pinned, never cut), 'largest_owner' (a pull request keeps at least one reviewer), 'diff_not_seen' (the model did not see all of the owner's diff), 'cut_skipped' (no model call, see llm_skipped on the run), 'model_kept', 'model_cut' or 'stamphog_approved' (older runs only).
     *
     * * `sensitive` - Owns a sensitive path
     * * `new_path` - Owns a new path
     * * `largest_owner` - Has the largest part
     * * `diff_not_seen` - Diff not shown to the model
     * * `cut_skipped` - Cut step skipped
     * * `model_kept` - Kept by the model
     * * `model_cut` - Cut by the model
     * * `stamphog_approved` - Auto-approved */
    readonly reason: RoutingOwnerReasonEnumApi
    /** The changed paths that pinned the owner, so no cut could remove them. */
    readonly pins: readonly CodeReviewApprovalRoutingPinApi[]
    /** Whether the owner is a GitHub team or a person.
     *
     * * `team` - Team
     * * `person` - Person */
    readonly kind: OwnerKindEnumApi
    /** The owner as owners.yaml spells it: a team slug such as 'team-devex', or a GitHub login such as '@octocat'. */
    owner: string
    /** The model's one-line reason to cut this owner. Also set when a guard kept the owner anyway. Blank when the model proposed no cut for them. */
    model_reason?: string
    /** Changed lines in the files this owner owns. */
    lines?: number
    /** Changed files this owner owns. */
    file_count?: number
}

export interface CodeReviewApprovalRoutingRunApi {
    /** ID of the routing run. */
    id: string
    /** Full name of the repository. */
    repository: string
    /** Pull request number. */
    pr_number: number
    /** The head commit the run routed. */
    head_sha: string
    /** The repository's routing_mode when the run made its requests.
     *
     * * `off` - Off
     * * `always` - Always
     * * `fallback` - When auto-approval does not approve */
    readonly mode: RoutingModeEnumApi
    /** What started the run: 'opened', 'ready_for_review', 'verdict:<outcome>', 'external_review', 'approval_retracted' or 'safety_net'. */
    trigger: string
    /** 'full', or 'pinned' when an auto-approval asked only the owners of sensitive and new paths.
     *
     * * `full` - Every owner
     * * `pinned` - Pinned owners only */
    readonly scope: RoutingScopeEnumApi
    /** Whether the pull request came from a fork, which skips the model. */
    fork?: boolean
    /** Why the cut step made no model call. Null when it made one.
     *
     * * `single_candidate` - Single candidate
     * * `fork` - Fork
     * * `nothing_cuttable` - Nothing cuttable
     * * `no_answer` - No answer
     * * `stamphog_approved` - Auto-approved
     * * `files_truncated` - Files truncated */
    readonly llm_skipped: LlmSkipReasonEnumApi | null
    /** The model the cut request reached. Blank when no request reached the gateway. */
    model?: string
    /** Whether GitHub listed fewer files than the pull request changes, so owners may be missing. */
    files_truncated?: boolean
    /** Whether the new-path lookup worked. When false, owners of new paths may not be pinned. */
    additions_resolved?: boolean
    /** The default-branch commit whose owners.yaml files decided the owners. Blank when unknown. */
    owners_sha?: string
    /** The run's decision for every owner of the changed code. */
    readonly owners: readonly CodeReviewApprovalRoutingRunOwnerApi[]
    /**
     * When the run made its requests.
     * @nullable
     */
    created_at?: string | null
}

export interface PaginatedCodeReviewApprovalRoutingRunListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: CodeReviewApprovalRoutingRunApi[]
}

export interface CodeReviewApprovalRoutingFileApi {
    /** The changed path. */
    path: string
    /**
     * The path before a rename. Null for any other change.
     * @nullable
     */
    previous_path?: string | null
    /** GitHub's file status, such as 'added', 'modified', 'removed' or 'renamed'. */
    status?: string
    /** Added lines. */
    additions?: number
    /** Deleted lines. */
    deletions?: number
    /**
     * Repo-relative path of the ownership file, read at the run's owners_sha, whose `owners` list names this owner for the file. Null when only an additions declaration made the owner a candidate (see the owner's `new_path` pins), or when the run is older than this field.
     * @nullable
     */
    owners_source?: string | null
}

export interface CodeReviewApprovalRoutingRunOwnerDetailApi {
    /** What the run did with the owner: 'requested', 'labeled' (a fork label instead of a request), 'refused' (GitHub refused the request or the label), 'cut', 'not_requested' (auto-approval approved, and routing would have asked this owner without the approval; on an older run whose llm_skipped is 'stamphog_approved' it means only that the owner owns changed code) or 'already_requested' (an earlier run asked this pinned owner).
     *
     * * `requested` - Requested
     * * `labeled` - Labeled
     * * `refused` - Refused by GitHub
     * * `cut` - Cut
     * * `not_requested` - Not requested
     * * `already_requested` - Already requested */
    readonly outcome: RoutingOwnerOutcomeEnumApi
    /** Why: 'sensitive' or 'new_path' (pinned, never cut), 'largest_owner' (a pull request keeps at least one reviewer), 'diff_not_seen' (the model did not see all of the owner's diff), 'cut_skipped' (no model call, see llm_skipped on the run), 'model_kept', 'model_cut' or 'stamphog_approved' (older runs only).
     *
     * * `sensitive` - Owns a sensitive path
     * * `new_path` - Owns a new path
     * * `largest_owner` - Has the largest part
     * * `diff_not_seen` - Diff not shown to the model
     * * `cut_skipped` - Cut step skipped
     * * `model_kept` - Kept by the model
     * * `model_cut` - Cut by the model
     * * `stamphog_approved` - Auto-approved */
    readonly reason: RoutingOwnerReasonEnumApi
    /** The changed paths that pinned the owner, so no cut could remove them. */
    readonly pins: readonly CodeReviewApprovalRoutingPinApi[]
    /** Whether the owner is a GitHub team or a person.
     *
     * * `team` - Team
     * * `person` - Person */
    readonly kind: OwnerKindEnumApi
    /** Every changed file this owner owns, which is what made them a candidate. Patches are not kept. */
    readonly files: readonly CodeReviewApprovalRoutingFileApi[]
    /** The owner as owners.yaml spells it: a team slug such as 'team-devex', or a GitHub login such as '@octocat'. */
    owner: string
    /** The model's one-line reason to cut this owner. Also set when a guard kept the owner anyway. Blank when the model proposed no cut for them. */
    model_reason?: string
    /** Changed lines in the files this owner owns. */
    lines?: number
    /** Changed files this owner owns. */
    file_count?: number
}

export interface CodeReviewApprovalRoutingRunDetailApi {
    /** ID of the routing run. */
    id: string
    /** Full name of the repository. */
    repository: string
    /** Pull request number. */
    pr_number: number
    /** The head commit the run routed. */
    head_sha: string
    /** The repository's routing_mode when the run made its requests.
     *
     * * `off` - Off
     * * `always` - Always
     * * `fallback` - When auto-approval does not approve */
    readonly mode: RoutingModeEnumApi
    /** What started the run: 'opened', 'ready_for_review', 'verdict:<outcome>', 'external_review', 'approval_retracted' or 'safety_net'. */
    trigger: string
    /** 'full', or 'pinned' when an auto-approval asked only the owners of sensitive and new paths.
     *
     * * `full` - Every owner
     * * `pinned` - Pinned owners only */
    readonly scope: RoutingScopeEnumApi
    /** Whether the pull request came from a fork, which skips the model. */
    fork?: boolean
    /** Why the cut step made no model call. Null when it made one.
     *
     * * `single_candidate` - Single candidate
     * * `fork` - Fork
     * * `nothing_cuttable` - Nothing cuttable
     * * `no_answer` - No answer
     * * `stamphog_approved` - Auto-approved
     * * `files_truncated` - Files truncated */
    readonly llm_skipped: LlmSkipReasonEnumApi | null
    /** The model the cut request reached. Blank when no request reached the gateway. */
    model?: string
    /** Whether GitHub listed fewer files than the pull request changes, so owners may be missing. */
    files_truncated?: boolean
    /** Whether the new-path lookup worked. When false, owners of new paths may not be pinned. */
    additions_resolved?: boolean
    /** The default-branch commit whose owners.yaml files decided the owners. Blank when unknown. */
    owners_sha?: string
    /** The run's decision for every owner of the changed code, with the files each owner owns. */
    readonly owners: readonly CodeReviewApprovalRoutingRunOwnerDetailApi[]
    /**
     * When the run made its requests.
     * @nullable
     */
    created_at?: string | null
}

/**
 * * `self_driving` - Self-driving
 * * `manual` - Manual
 * * `reviewhog_clean` - Clean PostHog Review
 * * `label` - Label
 * * `all` - All
 */
export type ReviewTriggerEnumApi = (typeof ReviewTriggerEnumApi)[keyof typeof ReviewTriggerEnumApi]

export const ReviewTriggerEnumApi = {
    SelfDriving: 'self_driving',
    Manual: 'manual',
    ReviewhogClean: 'reviewhog_clean',
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
 * repository content — changed-file paths (``lifted_files``, ``invalid_folder_files``),
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
 * and default-branch policy file contents, none of which the API returns. The reviewer's reasoning,
 * the text auto-approval posts on GitHub, is parsed out of the stdout and returned as ``reasoning``.
 */
export interface _ReviewOutputSummaryApi {
    /** Version of the auto-approval engine that produced this review, if it reported one. */
    readonly engine_version: string
    /** Exit code of the reviewer process in the sandbox, if the run reached the sandbox stage. */
    readonly reviewer_exit_code: number
}

/**
 * The reviewer's reasoning for one run, the same text auto-approval posts as its GitHub review.
 */
export interface _ReviewReasoningApi {
    /**
     * The reviewer's explanation of its verdict.
     * @nullable
     */
    readonly reasoning: string | null
    /**
     * Issues the reviewer found that block approval.
     * @nullable
     */
    readonly showstoppers: readonly string[] | null
    /**
     * The review text auto-approval posts on GitHub: the reasoning, the judgment points, and the gate outcome.
     * @nullable
     */
    readonly review_body: string | null
    /**
     * A plain-language summary of what the change does.
     * @nullable
     */
    readonly change_summary: string | null
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
    /** What caused this run to exist: self-driving inbox provenance, a manual request through the API, a clean PostHog Review run (a silent review that posts only an approval), the repo's trigger label, or the repo reviewing every PR event.
     *
     * * `self_driving` - Self-driving
     * * `manual` - Manual
     * * `reviewhog_clean` - Clean PostHog Review
     * * `label` - Label
     * * `all` - All */
    readonly trigger: ReviewTriggerEnumApi
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
    /** Allowlisted subset of the reviewer output blob (engine version, reviewer exit code). The raw reviewer stdout, PR payload, changed-file patches, and policy file contents are excluded. The reviewer's reasoning, the text auto-approval posts on GitHub, is in `reasoning` instead. */
    readonly output: _ReviewOutputSummaryApi
    /** The reviewer's reasoning, the same text auto-approval posts as its GitHub review. Returned only when retrieving a single run, and null in list results. Its fields are null until the reviewer has run. */
    readonly reasoning: _ReviewReasoningApi | null
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

/**
 * Request body for asking auto-approval to review one pull request.
 */
export interface ReviewRequestApi {
    /** Full name of the GitHub repository, e.g. 'PostHog/posthog'. It must be connected and enabled for auto-approval. */
    repository: string
    /**
     * Pull request number on GitHub.
     * @minimum 1
     */
    pr_number: number
}

/**
 * The review run a request points at.
 */
export interface ReviewRequestResponseApi {
    /** The review run for the pull request's current head. Poll it by id until status is terminal (completed, gated, failed, or superseded). */
    readonly run: ReviewRunApi
    /** True when this request queued a new run. False when a queued, running, or finished run already covered the current head, which is returned instead. */
    readonly created: boolean
}

export type CodeReviewApprovalsPullRequestsListParams = {
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

export type CodeReviewApprovalsRepositoriesListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type CodeReviewApprovalsRepositoriesAvailableRepositoriesRetrieveParams = {
    /**
     * Maximum number of repositories to return. Defaults to 50, at most 200.
     * @minimum 1
     * @maximum 200
     */
    limit?: number
    /**
     * Case-insensitive substring to match against the repository full name, e.g. 'posthog'.
     */
    search?: string
}

export type CodeReviewApprovalsReviewerRoutingListParams = {
    /**
     * Keep only runs created at or after this time (ISO 8601).
     */
    created_after?: string
    /**
     * Keep only runs created before this time (ISO 8601).
     */
    created_before?: string
    /**
     * Keep only runs on this head commit. Pass the full 40-character SHA.
     * @minLength 1
     * @maxLength 64
     */
    head_sha?: string
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    /**
     * Keep only runs where an owner got this outcome. With `owner`, that owner must have it, so `owner=team-devex&outcome=cut` lists the runs that cut team-devex.
     *
     * * `requested` - Requested
     * * `labeled` - Labeled
     * * `refused` - Refused by GitHub
     * * `cut` - Cut
     * * `not_requested` - Not requested
     * * `already_requested` - Already requested
     * @minLength 1
     */
    outcome?: CodeReviewApprovalsReviewerRoutingListOutcome
    /**
     * Keep only runs that decided about this owner, spelled as in owners.yaml: a team slug such as 'team-devex', or a GitHub login such as '@octocat'.
     * @minLength 1
     */
    owner?: string
    /**
     * Filter by pull request number.
     */
    pr_number?: number
    /**
     * Keep only runs where an owner was kept or cut for this reason. With `owner`, that owner must have it.
     *
     * * `sensitive` - Owns a sensitive path
     * * `new_path` - Owns a new path
     * * `largest_owner` - Has the largest part
     * * `diff_not_seen` - Diff not shown to the model
     * * `cut_skipped` - Cut step skipped
     * * `model_kept` - Kept by the model
     * * `model_cut` - Cut by the model
     * * `stamphog_approved` - Auto-approved
     * @minLength 1
     */
    reason?: CodeReviewApprovalsReviewerRoutingListReason
    /**
     * Filter by repository full name, e.g. 'PostHog/posthog'.
     * @minLength 1
     */
    repository?: string
}

export type CodeReviewApprovalsReviewerRoutingListOutcome =
    (typeof CodeReviewApprovalsReviewerRoutingListOutcome)[keyof typeof CodeReviewApprovalsReviewerRoutingListOutcome]

export const CodeReviewApprovalsReviewerRoutingListOutcome = {
    Requested: 'requested',
    Labeled: 'labeled',
    Refused: 'refused',
    Cut: 'cut',
    NotRequested: 'not_requested',
    AlreadyRequested: 'already_requested',
} as const

export type CodeReviewApprovalsReviewerRoutingListReason =
    (typeof CodeReviewApprovalsReviewerRoutingListReason)[keyof typeof CodeReviewApprovalsReviewerRoutingListReason]

export const CodeReviewApprovalsReviewerRoutingListReason = {
    Sensitive: 'sensitive',
    NewPath: 'new_path',
    LargestOwner: 'largest_owner',
    DiffNotSeen: 'diff_not_seen',
    CutSkipped: 'cut_skipped',
    ModelKept: 'model_kept',
    ModelCut: 'model_cut',
    StamphogApproved: 'stamphog_approved',
} as const

export type CodeReviewApprovalsRunsListParams = {
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
     * Filter by what caused the run. Leave it unset to include runs from every trigger. 'all' is not a wildcard: it matches only runs in repos that review every pull request event. The other values: 'label' (the repo's trigger label opted the PR in), 'manual' (someone requested the review through the API or MCP), 'reviewhog_clean' (a clean PostHog Review run started a silent review, which posts only an approval), and 'self_driving' (auto-approval reviewed a bot-authored PR from the inbox).
     */
    trigger?: CodeReviewApprovalsRunsListTrigger
}

export type CodeReviewApprovalsRunsListTrigger =
    (typeof CodeReviewApprovalsRunsListTrigger)[keyof typeof CodeReviewApprovalsRunsListTrigger]

export const CodeReviewApprovalsRunsListTrigger = {
    All: 'all',
    Label: 'label',
    Manual: 'manual',
    ReviewhogClean: 'reviewhog_clean',
    SelfDriving: 'self_driving',
} as const
