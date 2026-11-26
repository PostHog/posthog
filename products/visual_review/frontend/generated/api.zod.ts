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
 * Create a new repo.
 */
export const VisualReviewReposCreateBody = /* @__PURE__ */ zod.object({
    repo_full_name: zod.string(),
    repo_external_id: zod.number().nullish(),
})

/**
 * Update a repo's settings.
 */
export const VisualReviewReposPartialUpdateBody = /* @__PURE__ */ zod.object({
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
    auto_quarantine_mode: zod
        .union([
            zod.enum(['off', 'preview', 'on']).describe('\* `off` - off\n\* `preview` - preview\n\* `on` - on'),
            zod.null(),
        ])
        .optional()
        .describe(
            'Quarantine a snapshot that full runs on the default branch or in the merge queue prove flaky, and lift a quarantine once the last 500 default-branch runs render the snapshot unchanged. `off` (the default) does nothing. `preview` logs each finding and changes nothing. `on` quarantines the snapshot for 14 days and notifies the owning team, and lifts clean quarantines.\n\n\* `off` - off\n\* `preview` - preview\n\* `on` - on'
        ),
})

/**
 * Quarantine a snapshot identifier for a specific run type.
 */
export const visualReviewReposQuarantineCreateBodyIdentifierMax = 512

export const visualReviewReposQuarantineCreateBodyReasonMax = 255

export const visualReviewReposQuarantineCreateBodyNotifyOwnersDefault = false

export const VisualReviewReposQuarantineCreateBody = /* @__PURE__ */ zod.object({
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
        .uuid()
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
export const visualReviewReposQuarantineExpireCreateBodyIdentifierMax = 512

export const VisualReviewReposQuarantineExpireCreateBody = /* @__PURE__ */ zod.object({
    identifier: zod
        .string()
        .max(visualReviewReposQuarantineExpireCreateBodyIdentifierMax)
        .describe('Snapshot identifier to unquarantine'),
})

/**
 * Create a new run from a CI manifest.
 */
export const VisualReviewRunsCreateBody = /* @__PURE__ */ zod.object({
    repo_id: zod.uuid(),
    run_type: zod.string(),
    commit_sha: zod.string(),
    branch: zod.string(),
    snapshots: zod.array(
        zod.object({
            identifier: zod.string(),
            content_hash: zod.string(),
            width: zod.number().nullish(),
            height: zod.number().nullish(),
            metadata: zod.record(zod.string(), zod.unknown()).optional(),
        })
    ),
    pr_number: zod.number().nullish(),
    baseline_hashes: zod.record(zod.string(), zod.string()).optional(),
    unchanged_count: zod.number().optional(),
    removed_identifiers: zod.array(zod.string()).optional(),
    purpose: zod.string().optional(),
    metadata: zod.record(zod.string(), zod.unknown()).optional(),
    is_partial: zod.boolean().optional(),
})

/**
 * Add a batch of snapshots to a pending run (shard-based flow).
 */
export const VisualReviewRunsAddSnapshotsCreateBody = /* @__PURE__ */ zod.object({
    snapshots: zod.array(
        zod.object({
            identifier: zod.string(),
            content_hash: zod.string(),
            width: zod.number().nullish(),
            height: zod.number().nullish(),
            metadata: zod.record(zod.string(), zod.unknown()).optional(),
        })
    ),
    baseline_hashes: zod.record(zod.string(), zod.string()).optional(),
    story_index_hash: zod
        .string()
        .optional()
        .describe(
            "SHA-256 of the story-to-file map the CLI built from the Storybook index.json of this run's build. Every shard of a run sends the same value. Empty when the run sends no map."
        ),
})

/**
 * Accept snapshots (DB only).
 *
 * Records the per-snapshot "Accept change" decision. Does not change the baseline or pass
 * the gate; call finalize on the pull request's newest run for that. In ledger mode the run
 * can be an older run of the pull request: the accept counts on every run that renders the
 * same pictures. Works on a quarantined snapshot too: finalize records or commits it, and the
 * quarantine stays.
 */
export const visualReviewRunsApproveCreateBodySnapshotsItemIdentifierMax = 512

export const visualReviewRunsApproveCreateBodySnapshotsItemNewHashMax = 128

export const visualReviewRunsApproveCreateBodySnapshotsItemOldHashMax = 128

export const visualReviewRunsApproveCreateBodyExpectedSeqMin = 0

export const visualReviewRunsApproveCreateBodyOverrideRejectionDefault = false

export const VisualReviewRunsApproveCreateBody = /* @__PURE__ */ zod.object({
    snapshots: zod
        .array(
            zod.object({
                identifier: zod
                    .string()
                    .max(visualReviewRunsApproveCreateBodySnapshotsItemIdentifierMax)
                    .describe('The snapshot identifier, such as a Storybook story id plus theme.'),
                new_hash: zod
                    .string()
                    .max(visualReviewRunsApproveCreateBodySnapshotsItemNewHashMax)
                    .nullish()
                    .describe(
                        "The snapshot's `current_artifact.content_hash` on the run you pass as `id`. Null only for a `removed` snapshot, and only in a ledger-mode repo: elsewhere finalize accepts removals by itself."
                    ),
                old_hash: zod
                    .string()
                    .max(visualReviewRunsApproveCreateBodySnapshotsItemOldHashMax)
                    .nullish()
                    .describe(
                        "Optional: the snapshot's `baseline_artifact.content_hash` on that run, or an empty string for a `new` snapshot. When given, the call is refused if the run compares against another baseline, so the decision lands only on the pair of pictures you looked at."
                    ),
            })
        )
        .describe(
            'Snapshots to accept, each with `identifier` and `new_hash`. This only records the decision (the per-snapshot \"Accept change\" action). It does not change the baseline or pass the gate: the finalize endpoint does that.'
        ),
    expected_seq: zod
        .number()
        .min(visualReviewRunsApproveCreateBodyExpectedSeqMin)
        .nullish()
        .describe(
            'Optional: the highest decision `seq` you read on these snapshots, or 0 when you read none. The call is refused with 409 `decided_since` when someone decided on one of them after that.'
        ),
    override_rejection: zod
        .boolean()
        .default(visualReviewRunsApproveCreateBodyOverrideRejectionDefault)
        .describe(
            'Accept a snapshot someone else rejected. Only for a person who read the rejection. An agent through MCP can never accept over a rejection.'
        ),
})

/**
 * Undo the accept or reject of snapshots, in ledger mode, so they need review again.
 */
export const visualReviewRunsClearCreateBodyIdentifiersItemMax = 512

export const visualReviewRunsClearCreateBodyIdentifiersMax = 500

export const visualReviewRunsClearCreateBodyExpectedSeqMin = 0

export const visualReviewRunsClearCreateBodyOverrideRejectionDefault = false

export const VisualReviewRunsClearCreateBody = /* @__PURE__ */ zod.object({
    identifiers: zod
        .array(zod.string().max(visualReviewRunsClearCreateBodyIdentifiersItemMax))
        .max(visualReviewRunsClearCreateBodyIdentifiersMax)
        .describe('Identifiers of the snapshots whose accept or reject to undo, on the run you pass as `id`.'),
    expected_seq: zod
        .number()
        .min(visualReviewRunsClearCreateBodyExpectedSeqMin)
        .nullish()
        .describe(
            'Optional: the highest decision `seq` you read on these snapshots, or 0 when you read none. The call is refused with 409 `decided_since` when someone decided on one of them after that.'
        ),
    override_rejection: zod
        .boolean()
        .default(visualReviewRunsClearCreateBodyOverrideRejectionDefault)
        .describe(
            "Undo a rejection someone else made. Only for a person who read the rejection. Your own rejection undoes without it. An agent through MCP can never undo another user's rejection."
        ),
})

/**
 * Complete a run: detect removals, verify uploads, trigger diff processing.
 */
export const visualReviewRunsCompleteCreateBodyCheckRunIdMax = 32

export const visualReviewRunsCompleteCreateBodyCheckRunIdRegExp = new RegExp('^\\d+$')

export const VisualReviewRunsCompleteCreateBody = /* @__PURE__ */ zod.object({
    check_run_id: zod
        .string()
        .max(visualReviewRunsCompleteCreateBodyCheckRunIdMax)
        .regex(visualReviewRunsCompleteCreateBodyCheckRunIdRegExp)
        .optional()
        .describe(
            'Numeric GitHub Actions job ID of the CI job that completes the run, from `${{ job.check_run_id }}`. Recompute re-runs this job, so it re-reads the verdict without capturing the snapshots again. Omit it outside GitHub Actions.'
        ),
})

/**
 * Finalize a fully-reviewed run: record or commit the accepted baseline and pass the gate.
 *
 * Succeeds only once every changed, new and removed snapshot is accepted, tolerated or
 * quarantined, and none is rejected. In ledger mode an accept made on an earlier run of the
 * pull request counts while the pictures are the same, and removals nobody rejected are
 * accepted. With approve_all=true every change nobody decided on is accepted first; a
 * rejected snapshot is never accepted. With commit_to_github=false the server returns the
 * signed baseline YAML instead of committing it.
 */
export const visualReviewRunsFinalizeCreateBodyApproveAllDefault = false
export const visualReviewRunsFinalizeCreateBodyCommitToGithubDefault = true
export const visualReviewRunsFinalizeCreateBodyAddImagesToCommentOnPrDefault = false

export const VisualReviewRunsFinalizeCreateBody = /* @__PURE__ */ zod.object({
    approve_all: zod
        .boolean()
        .default(visualReviewRunsFinalizeCreateBodyApproveAllDefault)
        .describe(
            'Accept every changed and new snapshot that nobody decided on before finalizing. Tolerated and quarantined snapshots are left alone, and a rejected snapshot is never accepted, so it still blocks. Leave false to finalize a run you already reviewed: finalizing fails if any change still needs review.'
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
export const visualReviewRunsLiftOnMergeCreateBodyIdentifierMax = 512

export const VisualReviewRunsLiftOnMergeCreateBody = /* @__PURE__ */ zod.object({
    identifier: zod
        .string()
        .max(visualReviewRunsLiftOnMergeCreateBodyIdentifierMax)
        .describe(
            "Identifier of a quarantined snapshot in this run, such as a Storybook story ID. The snapshot's picture is what a default-branch run must render for the quarantine to lift. An unchanged snapshot uses its baseline. A changed or new snapshot must be approved first, because requesting a lift never approves a picture."
        ),
})

/**
 * Reject snapshots of a pull request run with a reason, in ledger mode.
 *
 * A rejected snapshot blocks finalize until the pull request renders a different picture or
 * the rejection is undone.
 */
export const visualReviewRunsRejectCreateBodySnapshotsItemIdentifierMax = 512

export const visualReviewRunsRejectCreateBodySnapshotsItemNewHashMax = 128

export const visualReviewRunsRejectCreateBodySnapshotsItemOldHashMax = 128

export const visualReviewRunsRejectCreateBodySnapshotsItemReasonMax = 500

export const visualReviewRunsRejectCreateBodyExpectedSeqMin = 0

export const VisualReviewRunsRejectCreateBody = /* @__PURE__ */ zod.object({
    snapshots: zod
        .array(
            zod.object({
                identifier: zod
                    .string()
                    .max(visualReviewRunsRejectCreateBodySnapshotsItemIdentifierMax)
                    .describe('The snapshot identifier, such as a Storybook story id plus theme.'),
                new_hash: zod
                    .string()
                    .max(visualReviewRunsRejectCreateBodySnapshotsItemNewHashMax)
                    .nullish()
                    .describe(
                        "The snapshot's `current_artifact.content_hash` on the run you pass as `id`. Null only for a `removed` snapshot, and only in a ledger-mode repo: elsewhere finalize accepts removals by itself."
                    ),
                old_hash: zod
                    .string()
                    .max(visualReviewRunsRejectCreateBodySnapshotsItemOldHashMax)
                    .nullish()
                    .describe(
                        "Optional: the snapshot's `baseline_artifact.content_hash` on that run, or an empty string for a `new` snapshot. When given, the call is refused if the run compares against another baseline, so the decision lands only on the pair of pictures you looked at."
                    ),
                reason: zod
                    .string()
                    .min(1)
                    .max(visualReviewRunsRejectCreateBodySnapshotsItemReasonMax)
                    .describe(
                        'What is wrong with the new picture, so the author can fix it. Shown on the pull request.'
                    ),
            })
        )
        .describe('Snapshots to reject, each with `identifier`, `new_hash` and `reason`.'),
    expected_seq: zod
        .number()
        .min(visualReviewRunsRejectCreateBodyExpectedSeqMin)
        .nullish()
        .describe(
            'Optional: the highest decision `seq` you read on these snapshots, or 0 when you read none. The call is refused with 409 `decided_since` when someone decided on one of them after that.'
        ),
})

/**
 * Mark a changed snapshot as a known tolerated alternate.
 */
export const VisualReviewRunsTolerateCreateBody = /* @__PURE__ */ zod.object({
    snapshot_id: zod
        .uuid()
        .describe(
            'UUID of the changed snapshot to mark as a known tolerated alternate. Future runs that produce the same alternate hash for this identifier will not be flagged as changes.'
        ),
})

/**
 * Report that CI decided a commit needs no visual run, so the required commit status passes.
 *
 * Does nothing when a run of the commit and run type exists, or when the repo reads its baselines from the YAML file.
 */
export const visualReviewRunsSkipCreateBodyCommitShaRegExp = new RegExp('^[0-9a-f]{40}$')

export const VisualReviewRunsSkipCreateBody = /* @__PURE__ */ zod.object({
    repo_id: zod.uuid().describe('ID of the Visual Review repo the commit belongs to.'),
    run_type: zod.string().describe('Run type that needs no run at this commit, for example `storybook`.'),
    commit_sha: zod
        .string()
        .regex(visualReviewRunsSkipCreateBodyCommitShaRegExp)
        .describe('Full SHA of the commit that gets the passing status.'),
    branch: zod.string().describe('Branch CI ran on. Only logged.'),
    pr_number: zod.number().nullish().describe('Pull request the commit belongs to, if any. Only logged.'),
})
