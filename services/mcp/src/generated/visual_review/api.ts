/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 23 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * List all projects for the team.
 */
export const VisualReviewReposListParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const VisualReviewReposListQueryParams = () => zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

/**
 * Get a repo by ID.
 */
export const VisualReviewReposRetrieveParams = () => zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * Update a repo's settings.
 */
export const VisualReviewReposPartialUpdateParams = () => zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const VisualReviewReposPartialUpdateBody = () => zod.object({
    baseline_file_paths: zod.record(zod.string(), zod.string()).nullish(),
    enable_pr_comments: zod
        .boolean()
        .nullish()
        .describe('Post a pull request comment when a run finds visual changes to review.'),
    debt_digest_enabled: zod
        .boolean()
        .nullish()
        .describe(
            'Post the visual review debt digest to the Slack channels of the teams that own the snapshots. Off by default. The digest goes out every Monday morning.'
        ),
})

/**
 * Snapshots in a repo whose rendering cannot be trusted: those that failed the gate on a recent default-branch run, those whose absorbed diff is close to the threshold, and those under an active quarantine. Small absorbed diffs well under the threshold are omitted, as is everything else, so this is far smaller than the baselines universe; `totals.tracked` gives the full denominator. Each entry carries the share of the last 7 days of default-branch runs that failed the gate (`hard_rate`) and the share a toleration absorbed (`soft_rate`), plus `headroom`, the fraction of the diff threshold its worst absorbed run leaves free. Capped at 2000 entries, which sets `truncated`. Filtering, faceting and search are done client-side; this endpoint takes no filter query params.
 */
export const VisualReviewReposFlakinessRetrieveParams = () => zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * List quarantined identifiers. Without filter: active only. With identifier: full history.
 */
export const VisualReviewReposQuarantineListParams = () => zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const VisualReviewReposQuarantineListQueryParams = () => zod.object({
    identifier: zod.string().optional().describe('Filter by identifier (returns full history)'),
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
    run_type: zod.string().optional().describe('Filter by run type'),
})

/**
 * Quarantine a snapshot identifier for a specific run type.
 */
export const visualReviewReposQuarantineCreatePathRunTypeRegExp = new RegExp('^[^\/]+$')

export const VisualReviewReposQuarantineCreateParams = () => zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
    run_type: zod.string().regex(visualReviewReposQuarantineCreatePathRunTypeRegExp),
})

export const visualReviewReposQuarantineCreateBodyIdentifierMax = 512

export const visualReviewReposQuarantineCreateBodyReasonMax = 255

export const visualReviewReposQuarantineCreateBodyNotifyOwnersDefault = false

export const VisualReviewReposQuarantineCreateBody = () => zod.object({
    identifier: zod
        .string()
        .max(visualReviewReposQuarantineCreateBodyIdentifierMax)
        .describe('Snapshot identifier to quarantine.'),
    reason: zod
        .string()
        .max(visualReviewReposQuarantineCreateBodyReasonMax)
        .describe('Why this snapshot is being quarantined.'),
    expires_at: zod.iso
        .datetime({ offset: true })
        .nullish()
        .describe(
            'When the quarantine lifts itself, as an ISO 8601 datetime. Through MCP an omitted or later expiry becomes 30 days from now; anywhere else omitting it means no expiry.'
        ),
    source_run_id: zod
        .string()
        .nullish()
        .describe(
            "Optional pointer to the run whose failing snapshot prompted this quarantine — used to surface a 'view the failing run' link later."
        ),
    notify_owners: zod
        .boolean()
        .default(visualReviewReposQuarantineCreateBodyNotifyOwnersDefault)
        .describe(
            'Post the quarantine to the Slack channel of the team that owns the story, naming the user who quarantined it. Only Storybook snapshots have an owning team. Best effort: skipped when the story has no owning team or the project has no Slack integration.'
        ),
})

/**
 * Expire all active quarantine entries for an identifier.
 */
export const visualReviewReposQuarantineExpireCreatePathRunTypeRegExp = new RegExp('^[^\/]+$')

export const VisualReviewReposQuarantineExpireCreateParams = () => zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
    run_type: zod.string().regex(visualReviewReposQuarantineExpireCreatePathRunTypeRegExp),
})

export const visualReviewReposQuarantineExpireCreateBodyIdentifierMax = 512

export const VisualReviewReposQuarantineExpireCreateBody = () => zod.object({
    identifier: zod
        .string()
        .max(visualReviewReposQuarantineExpireCreateBodyIdentifierMax)
        .describe('Snapshot identifier to unquarantine'),
})

/**
 * Snapshots that keep getting tolerated, counted across baselines, most manual tolerations first. A toleration accepts one exact rendering, so a snapshot that keeps needing them renders differently from run to run, and the fix belongs in the story. With no parameters this is the weekly debt digest's rule (3 or more tolerations by a person or agent in 30 days), except that quarantined snapshots are kept and marked with `is_quarantined`. The list is small and returns fast; start here to find flaky stories worth fixing, then read one snapshot's history with the per-snapshot tools.
 */
export const VisualReviewReposTolerationPileupsRetrieveParams = () => zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const visualReviewReposTolerationPileupsRetrieveQueryIncludeQuarantinedDefault = true
export const visualReviewReposTolerationPileupsRetrieveQueryLimitDefault = 100
export const visualReviewReposTolerationPileupsRetrieveQueryLimitMax = 500

export const visualReviewReposTolerationPileupsRetrieveQueryMinAutomaticTolerationsMax = 10000

export const visualReviewReposTolerationPileupsRetrieveQueryMinTolerationsDefault = 3
export const visualReviewReposTolerationPileupsRetrieveQueryMinTolerationsMax = 100

export const visualReviewReposTolerationPileupsRetrieveQueryRunTypeMax = 64

export const visualReviewReposTolerationPileupsRetrieveQueryWindowDaysDefault = 30
export const visualReviewReposTolerationPileupsRetrieveQueryWindowDaysMax = 90

export const VisualReviewReposTolerationPileupsRetrieveQueryParams = () => zod.object({
    include_quarantined: zod
        .boolean()
        .default(visualReviewReposTolerationPileupsRetrieveQueryIncludeQuarantinedDefault)
        .describe(
            'Keep snapshots that an active quarantine already covers. They are marked with `is_quarantined`. Set to false to see only piles nobody has acted on yet.'
        ),
    limit: zod
        .number()
        .min(1)
        .max(visualReviewReposTolerationPileupsRetrieveQueryLimitMax)
        .default(visualReviewReposTolerationPileupsRetrieveQueryLimitDefault)
        .describe('Maximum number of snapshots to return. `total` and `truncated` say whether more matched.'),
    min_automatic_tolerations: zod
        .number()
        .min(1)
        .max(visualReviewReposTolerationPileupsRetrieveQueryMinAutomaticTolerationsMax)
        .optional()
        .describe(
            "Also list a snapshot when it collected at least this many automatic tolerations in the window. An automatic toleration is a rendering under both diff thresholds, so it never blocked anybody; many of them still mean the story is unstable. Omit to ignore automatic tolerations when deciding what to list. With 10, the list matches the Tolerate dialog's quarantine suggestion."
        ),
    min_tolerations: zod
        .number()
        .min(1)
        .max(visualReviewReposTolerationPileupsRetrieveQueryMinTolerationsMax)
        .default(visualReviewReposTolerationPileupsRetrieveQueryMinTolerationsDefault)
        .describe(
            "List a snapshot when a person or agent tolerated it at least this many times in the window. The default, 3, is the weekly debt digest's rule. Lower it to see snapshots that are starting to pile up, raise it to see only the worst ones."
        ),
    run_type: zod
        .string()
        .min(1)
        .max(visualReviewReposTolerationPileupsRetrieveQueryRunTypeMax)
        .optional()
        .describe('Only list snapshots of this run type, for example `storybook` or `playwright`.'),
    window_days: zod
        .number()
        .min(1)
        .max(visualReviewReposTolerationPileupsRetrieveQueryWindowDaysMax)
        .default(visualReviewReposTolerationPileupsRetrieveQueryWindowDaysDefault)
        .describe('How many days back to count tolerations. Defaults to 30.'),
})

/**
 * List runs in this repo, optionally filtered by review state and free-text search.
 */
export const VisualReviewReposRunsListParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
    repo_id: zod.string(),
})

export const VisualReviewReposRunsListQueryParams = () => zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
    review_state: zod.string().optional().describe('Filter by review state'),
    search: zod.string().optional().describe('Free-text search over branch, commit SHA, run type, and PR number'),
})

/**
 * Review state counts for runs in this repo.
 */
export const VisualReviewReposRunsCountsRetrieveParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
    repo_id: zod.string(),
})

/**
 * List runs for the team, optionally filtered by review state, PR number, commit SHA, branch, or free-text search.
 */
export const VisualReviewRunsListParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const VisualReviewRunsListQueryParams = () => zod.object({
    branch: zod.string().optional().describe('Filter by branch name'),
    commit_sha: zod.string().optional().describe('Filter by full commit SHA'),
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
    pr_number: zod.number().optional().describe('Filter by GitHub PR number'),
    review_state: zod.string().optional().describe('Filter by review state'),
    search: zod.string().optional().describe('Free-text search over branch, commit SHA, run type, and PR number'),
})

/**
 * Get run status and summary.
 */
export const VisualReviewRunsRetrieveParams = () => zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * Mark snapshots reviewed (DB only).
 *
 * Records the per-snapshot "Accept change" decision. Does not commit the baseline
 * or change the GitHub gate — call finalize to ship the run. Works on a quarantined
 * snapshot too: a quarantined snapshot approved here is committed by finalize, which
 * updates a quarantined story's baseline entry without lifting the quarantine.
 */
export const VisualReviewRunsApproveCreateParams = () => zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const VisualReviewRunsApproveCreateBody = () => zod.object({
    snapshots: zod
        .array(
            zod.object({
                identifier: zod
                    .string()
                    .describe('The snapshot identifier to approve (e.g. Storybook story id plus theme).'),
                new_hash: zod
                    .string()
                    .describe('The content hash of the new baseline image to record for this identifier.'),
            })
        )
        .describe(
            'Snapshots to mark reviewed, each with `identifier` and `new_hash`. This only records the review in the database (the per-snapshot \"Accept change\" action) — it does not change the baseline or the GitHub gate. Commit the baseline and green the gate with the finalize endpoint.'
        ),
})

/**
 * Finalize a fully-reviewed run: commit the approved baseline and green the gate.
 *
 * Commits exactly the snapshots approved in the DB (tolerated ones keep their baseline)
 * and only succeeds once every changed/new snapshot is resolved. With approve_all=true,
 * any still-pending changed/new snapshot is approved first; quarantined snapshots are
 * skipped, but a quarantined snapshot approved by identifier is still committed.
 * With commit_to_github=false the server returns the signed baseline YAML instead of
 * committing it.
 */
export const VisualReviewRunsFinalizeCreateParams = () => zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const visualReviewRunsFinalizeCreateBodyApproveAllDefault = false
export const visualReviewRunsFinalizeCreateBodyCommitToGithubDefault = true
export const visualReviewRunsFinalizeCreateBodyAddImagesToCommentOnPrDefault = false

export const VisualReviewRunsFinalizeCreateBody = () => zod.object({
    approve_all: zod
        .boolean()
        .default(visualReviewRunsFinalizeCreateBodyApproveAllDefault)
        .describe(
            "Approve every still-pending changed and new snapshot before finalizing (tolerated snapshots are left untouched). Leave false to finalize a run you've already reviewed — finalizing fails if any changed\/new snapshot is still unreviewed."
        ),
    commit_to_github: zod
        .boolean()
        .default(visualReviewRunsFinalizeCreateBodyCommitToGithubDefault)
        .describe(
            'Whether the server commits the approved baseline to the PR branch and greens the gate (the normal path — leave true). Set false only for tooling that commits the baseline itself: the server skips the commit and returns the signed YAML in `baseline_content` instead. With false, the gate is NOT greened, `metadata.baseline_commit_sha` is absent, and no post-approval PR comment is posted.'
        ),
    add_images_to_comment_on_pr: zod
        .boolean()
        .default(visualReviewRunsFinalizeCreateBodyAddImagesToCommentOnPrDefault)
        .describe(
            "Whether to embed the before\/after snapshot images in the post-approval PR comment. The comment itself is posted when the repo has PR comments enabled and `commit_to_github` is true: it updates the run's review prompt when the run has one, and posts a new comment when it does not. This flag only controls the images. Defaults false — the comment stays a text summary unless the reviewer opts in to attach the snapshots."
        ),
})

/**
 * Lift a quarantined snapshot's quarantine once this run's pull request merges. The lift applies only after a default-branch run that contains the merge renders the expected picture, and the baseline entry holds that same picture. Requesting a lift never approves a picture: approve a changed or new snapshot by identifier first. Requesting again from the same pull request replaces the pending request.
 */
export const VisualReviewRunsLiftOnMergeCreateParams = () => zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const visualReviewRunsLiftOnMergeCreateBodyIdentifierMax = 512

export const VisualReviewRunsLiftOnMergeCreateBody = () => zod.object({
    identifier: zod
        .string()
        .max(visualReviewRunsLiftOnMergeCreateBodyIdentifierMax)
        .describe(
            "Identifier of a quarantined snapshot in this run, such as a Storybook story ID. The snapshot's picture is what a default-branch run must render for the quarantine to lift. An unchanged snapshot uses its baseline. A changed or new snapshot must be approved first, because requesting a lift never approves a picture."
        ),
})

/**
 * Every request to lift a quarantine when this run's pull request merges, newest first, in any state. Empty for a run without a pull request.
 */
export const VisualReviewRunsQuarantineLiftsListParams = () => zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * Withdraw a pending request to lift a quarantine when this run's pull request merges.
 */
export const VisualReviewRunsQuarantineLiftsCancelCreateParams = () => zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
    request_id: zod.string().describe("UUID of a pending lift request for this run's pull request."),
})

/**
 * Re-evaluate quarantine and counts, update commit status, and optionally rerun the CI job.
 */
export const VisualReviewRunsRecomputeCreateParams = () => zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * Recent change history for a snapshot identifier across runs.
 */
export const VisualReviewRunsSnapshotHistoryListParams = () => zod.object({
    id: zod
        .string()
        .describe(
            'UUID of the visual review run to look the snapshot up from. This is a run id, not the `id` of a snapshot inside that run. The run supplies the repo and run type to search, so the `identifier` query parameter is required alongside it.'
        ),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const VisualReviewRunsSnapshotHistoryListQueryParams = () => zod.object({
    identifier: zod
        .string()
        .describe(
            'Identifier of the snapshot to look up, for example a Storybook story id plus theme. Read it from the `identifier` field of a snapshot in the run. It is a name rather than a UUID, and it is required in addition to the run id in the path.'
        ),
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

/**
 * Get a run's snapshots with diff results, excluding quarantined ones by default.
 */
export const VisualReviewRunsSnapshotsListParams = () => zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const visualReviewRunsSnapshotsListQueryExcludeUnchangedDefault = false
export const visualReviewRunsSnapshotsListQueryIncludeQuarantinedDefault = false
export const visualReviewRunsSnapshotsListQueryQuarantinedOnlyDefault = false

export const VisualReviewRunsSnapshotsListQueryParams = () => zod.object({
    exclude_unchanged: zod
        .boolean()
        .default(visualReviewRunsSnapshotsListQueryExcludeUnchangedDefault)
        .describe(
            'Whether to leave out snapshots whose result is `unchanged`. Defaults to false. Pass true to list only the changed, new and removed snapshots, which is what a review needs. A large run holds thousands of unchanged snapshots and few changes.'
        ),
    include_quarantined: zod
        .boolean()
        .default(visualReviewRunsSnapshotsListQueryIncludeQuarantinedDefault)
        .describe(
            'Whether to include snapshots whose identifier is currently quarantined. Defaults to false: quarantined snapshots are excluded from results and reported in quarantined_count instead, since they are noise when reviewing real changes.'
        ),
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
    quarantined_only: zod
        .boolean()
        .default(visualReviewRunsSnapshotsListQueryQuarantinedOnlyDefault)
        .describe(
            'Whether to list only the snapshots whose identifier is currently quarantined. Defaults to false. When true, `include_quarantined` is ignored and quarantined snapshots are returned. Combine with `exclude_unchanged=false` to find a quarantined story that rendered `unchanged`, which is the snapshot to request a lift on merge for.'
        ),
    snapshot_id: zod
        .string()
        .optional()
        .describe(
            'Return only the snapshot with this id, read from the `id` field of a snapshot in the run. Use it to fetch one snapshot without listing the whole run.'
        ),
})

/**
 * Mark a changed snapshot as a known tolerated alternate.
 */
export const VisualReviewRunsTolerateCreateParams = () => zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const VisualReviewRunsTolerateCreateBody = () => zod.object({
    snapshot_id: zod
        .string()
        .describe(
            'UUID of the changed snapshot to mark as a known tolerated alternate. Future runs that produce the same alternate hash for this identifier will not be flagged as changes.'
        ),
})

/**
 * List known tolerated hashes for a snapshot identifier.
 */
export const VisualReviewRunsToleratedHashesListParams = () => zod.object({
    id: zod
        .string()
        .describe(
            'UUID of the visual review run to look the snapshot up from. This is a run id, not the `id` of a snapshot inside that run. The run supplies the repo and run type to search, so the `identifier` query parameter is required alongside it.'
        ),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const VisualReviewRunsToleratedHashesListQueryParams = () => zod.object({
    identifier: zod
        .string()
        .describe(
            'Identifier of the snapshot to look up, for example a Storybook story id plus theme. Read it from the `identifier` field of a snapshot in the run. It is a name rather than a UUID, and it is required in addition to the run id in the path.'
        ),
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

/**
 * Review state counts for the runs list.
 */
export const VisualReviewRunsCountsRetrieveParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})
