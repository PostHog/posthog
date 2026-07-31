/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import {
    AddSnapshotsInputApi,
    ApproveRunRequestInputApi,
    CreateRepoInputApi,
    CreateRunInputApi,
    FinalizeRunRequestInputApi,
    MarkToleratedInputApi,
    PatchedUpdateRepoRequestInputApi,
    QuarantineInputApi,
} from './api.zod.schemas'

/**
 * Create a new repo.
 */
export const VisualReviewReposCreateBody = CreateRepoInputApi

/**
 * Update a repo's settings.
 */
export const VisualReviewReposPartialUpdateBody = PatchedUpdateRepoRequestInputApi

/**
 * Quarantine a snapshot identifier for a specific run type.
 */
export const VisualReviewReposQuarantineCreateBody = QuarantineInputApi

/**
 * Expire all active quarantine entries for an identifier.
 */
export const VisualReviewReposQuarantineExpireCreateBody = QuarantineInputApi

/**
 * Create a new run from a CI manifest.
 */
export const VisualReviewRunsCreateBody = CreateRunInputApi

/**
 * Add a batch of snapshots to a pending run (shard-based flow).
 */
export const VisualReviewRunsAddSnapshotsCreateBody = AddSnapshotsInputApi

/**
 * Mark snapshots reviewed (DB only).
 *
 * Records the per-snapshot "Accept change" decision. Does not commit the baseline
 * or change the GitHub gate — call finalize to ship the run.
 */
export const VisualReviewRunsApproveCreateBody = ApproveRunRequestInputApi

/**
 * Finalize a fully-reviewed run: commit the approved baseline and green the gate.
 *
 * Commits exactly the snapshots approved in the DB (tolerated ones keep their baseline)
 * and only succeeds once every changed/new snapshot is resolved. With approve_all=true,
 * any still-pending changed/new snapshot is approved first. With commit_to_github=false
 * the server returns the signed baseline YAML instead of committing it.
 */
export const VisualReviewRunsFinalizeCreateBody = FinalizeRunRequestInputApi

/**
 * Mark a changed snapshot as a known tolerated alternate.
 */
export const VisualReviewRunsTolerateCreateBody = MarkToleratedInputApi
