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

import {
    ChannelFeedMessageWriteApi,
    ChannelWriteApi,
    CodeInviteRedeemRequestApi,
    LoopPreviewRequestApi,
    LoopSkillBundlesWriteApi,
    LoopWriteApi,
    PatchedChannelWriteApi,
    PatchedLoopWriteApi,
    PatchedSandboxCustomImageUpdateApi,
    PatchedSandboxEnvironmentWriteApi,
    PatchedTaskAutomationWriteApi,
    PatchedTaskRunSetOutputRequestApi,
    PatchedTaskRunUpdateApi,
    PatchedTaskWriteApi,
    SandboxCustomImageBuildApi,
    SandboxCustomImageWriteApi,
    SandboxEnvironmentWriteApi,
    TaskActivityMarkReadApi,
    TaskAutomationWriteApi,
    TaskCreateApi,
    TaskPinRequestApi,
    TaskPresenceBeaconRequestApi,
    TaskRunAppendLogRequestApi,
    TaskRunArtifactPresignRequestApi,
    TaskRunArtifactsFinalizeUploadRequestApi,
    TaskRunArtifactsPrepareUploadRequestApi,
    TaskRunArtifactsUploadRequestApi,
    TaskRunBootstrapCreateRequestApi,
    TaskRunCancelRequestApi,
    TaskRunCommandRequestApi,
    TaskRunCreateRequestSchemaApi,
    TaskRunLivingArtifactChartRequestApi,
    TaskRunLivingArtifactCreateRequestApi,
    TaskRunLivingArtifactEditRequestApi,
    TaskRunRelayMessageRequestApi,
    TaskRunStartRequestApi,
    TaskStagedArtifactsFinalizeUploadRequestApi,
    TaskStagedArtifactsPrepareUploadRequestApi,
    TaskSummariesRequestApi,
    TaskThreadMessageDTOApi,
    TaskThreadMessageWriteApi,
    TaskWriteApi,
    WarmTaskRequestApi,
} from './api.zod.schemas'

/**
 * Redeem a PostHog Desktop invite code to enable access.
 * @summary Redeem invite code
 */
export const CodeInvitesRedeemCreateBody = CodeInviteRedeemRequestApi

/**
 * API for managing loops — named, cloud-executed agent automations triggered by
 * schedule, GitHub events or authenticated API calls. See `products/tasks/docs/LOOPS.md`.
 * @summary Create a loop
 */
export const LoopsCreateBody = LoopWriteApi

/**
 * Partial update. Identity-bearing fields (instructions, repositories, connectors, behaviors, model config, triggers) are owner-only on team loops; name, description, notifications and enable/pause are editable by any team member.
 * @summary Update a loop
 */
export const LoopsPartialUpdateBody = PatchedLoopWriteApi

/**
 * Dry run: renders the assembled instructions and trigger context for a supplied sample payload (or a synthetic schedule fire when omitted), without creating a task, run, or any other side effect.
 * @summary Preview a loop fire
 */
export const LoopsPreviewCreateBody = LoopPreviewRequestApi

/**
 * Replaces the loop's attached skill bundles wholesale: zipped local skills whose contents are seeded into every fired run's sandbox. Send an empty list to detach every skill. Owner-only on team loops, like other identity-bearing configuration.
 * @summary Replace a loop's skill bundles
 */
export const LoopsSkillBundlesUpdateBody = LoopSkillBundlesWriteApi

/**
 * Authenticated POST trigger for `type=api` triggers. Project secret API key auth (`loop:write` scope), project-wide. Request body (JSON, capped at 64 KB) becomes run context. Send an `Idempotency-Key` header to dedupe retries.
 * @summary Fire a loop externally
 */
export const LoopsTriggerCreateBody = /* @__PURE__ */ zod.record(zod.string(), zod.unknown())

/**
 * Create a draft custom image and start its interactive image-builder agent task. The returned builder_task_id points at the conversation.
 */
export const SandboxCustomImagesCreateBody = SandboxCustomImageWriteApi

/**
 * Rename or update the description of a custom image. Only mutable metadata (name, description) is editable; the build spec and status are managed by the build flow.
 */
export const SandboxCustomImagesPartialUpdateBody = PatchedSandboxCustomImageUpdateApi

/**
 * Persist the image spec (from the request body or the builder agent's sandbox), run the security scan, and on pass build and publish the image.
 */
export const SandboxCustomImagesBuildCreateBody = SandboxCustomImageBuildApi

/**
 * API for managing sandbox environments that control network access for task runs.
 */
export const SandboxCreateBody = SandboxEnvironmentWriteApi

/**
 * API for managing sandbox environments that control network access for task runs.
 */
export const SandboxPartialUpdateBody = PatchedSandboxEnvironmentWriteApi

/**
 * Clear the unread flag on the requester's feed rows for the given tasks. Read state is per task, so opening a task through any surface clears the same row.
 * @summary Mark task activity read
 */
export const TaskActivityMarkReadCreateBody = TaskActivityMarkReadApi

/**
 * API for managing scheduled task automations.
 */
export const TaskAutomationsCreateBody = TaskAutomationWriteApi

/**
 * API for managing scheduled task automations.
 */
export const TaskAutomationsPartialUpdateBody = PatchedTaskAutomationWriteApi

/**
 * Returns the existing public channel with the (normalized) name, creating it if needed.
 * @summary Resolve or create a public channel
 */
export const TaskChannelsCreateBody = ChannelWriteApi

/**
 * API for a channel's system-announcement feed — durable "PostHog agent" rows
 * (context created, CONTEXT.md being built) rendered alongside the channel's task
 * cards. Read by any team member for a public channel; personal channels are owner-only.
 * @summary Post a channel feed message
 */
export const TaskChannelsFeedCreateBody = ChannelFeedMessageWriteApi

/**
 * API for task channels — the shared feeds tasks are kicked off in. Listing lazily
 * provisions the requester's personal "#me" channel; creation is resolve-or-create
 * by normalized name so clients can map channel-like surfaces onto backend channels.
 * @summary Rename a public channel
 */
export const TaskChannelsPartialUpdateBody = PatchedChannelWriteApi

/**
 * API for managing tasks within a project. Tasks represent units of work to be performed by an agent.
 */
export const TasksCreateBody = TaskCreateApi

/**
 * API for managing tasks within a project. Tasks represent units of work to be performed by an agent.
 */
export const TasksUpdateBody = TaskWriteApi

/**
 * API for managing tasks within a project. Tasks represent units of work to be performed by an agent.
 */
export const TasksPartialUpdateBody = PatchedTaskWriteApi

/**
 * API for managing tasks within a project. Tasks represent units of work to be performed by an agent.
 */
export const TasksPinCreateBody = TaskPinRequestApi

/**
 * Idempotent upsert: marks the calling user + `device_id` as actively watching this task for the next ~60 seconds. While at least one device for the user has a non-expired presence row for this task, the push fanout will skip ALL of that user's other registered devices for task notifications — the contract is 'if any device is demonstrably watching, suppress the others'. Clients call this every ~30s while the task screen is foregrounded. `device_id` is the UUID of the caller's UserPushToken row.
 * @summary Beacon presence for a device watching this task
 */
export const TasksPresenceCreateBody = TaskPresenceBeaconRequestApi

/**
 * Create a new task run and kick off the workflow.
 * @summary Run task
 */
export const TasksRunCreateBody = TaskRunCreateRequestSchemaApi

/**
 * Verify staged S3 uploads and cache their metadata so they can be attached to the next run created for this task.
 * @summary Finalize staged direct uploads for task attachments
 */
export const TasksStagedArtifactsFinalizeUploadCreateBody = TaskStagedArtifactsFinalizeUploadRequestApi

/**
 * Reserve S3 object keys for task attachments before creating a new run and return presigned POST forms for direct uploads.
 * @summary Prepare staged direct uploads for task attachments
 */
export const TasksStagedArtifactsPrepareUploadCreateBody = TaskStagedArtifactsPrepareUploadRequestApi

/**
 * Create a new run for a specific task without starting execution.
 * @summary Create task run
 */
export const TasksRunsCreateBody = TaskRunBootstrapCreateRequestApi

/**
 * API for managing task runs. Each run represents an execution of a task.
 * @summary Update task run
 */
export const TasksRunsPartialUpdateBody = PatchedTaskRunUpdateApi

/**
 * Append one or more log entries to the task run log array
 * @summary Append log entries
 */
export const TasksRunsAppendLogCreateBody = TaskRunAppendLogRequestApi

/**
 * Persist task artifacts to S3 and attach them to the run manifest.
 * @summary Upload artifacts for a task run
 */
export const TasksRunsArtifactsCreateBody = TaskRunArtifactsUploadRequestApi

/**
 * Streams artifact content for a task run artifact after validating that it belongs to the run.
 * @summary Download an artifact through the backend
 */
export const TasksRunsArtifactsDownloadCreateBody = TaskRunArtifactPresignRequestApi

/**
 * Verify directly uploaded S3 objects and attach them to the run artifact manifest.
 * @summary Finalize direct uploads for task run artifacts
 */
export const TasksRunsArtifactsFinalizeUploadCreateBody = TaskRunArtifactsFinalizeUploadRequestApi

/**
 * Reserve S3 object keys for task artifacts and return presigned POST forms for direct uploads.
 * @summary Prepare direct uploads for task run artifacts
 */
export const TasksRunsArtifactsPrepareUploadCreateBody = TaskRunArtifactsPrepareUploadRequestApi

/**
 * Returns a temporary, signed URL that can be used to download a specific artifact.
 * @summary Generate presigned URL for an artifact
 */
export const TasksRunsArtifactsPresignCreateBody = TaskRunArtifactPresignRequestApi

/**
 * Stop an active cloud run. Interrupts the agent, snapshots interactive sessions for later resume, tears down the sandbox, and marks the run cancelled. Idempotent: cancelling a finished run returns it unchanged.
 * @summary Cancel task run
 */
export const TasksRunsCancelCreateBody = TaskRunCancelRequestApi

/**
 * Queue user_message JSON-RPC commands through the task workflow and forward sandbox control commands to the agent server. Supports user_message, cancel, close, permission_response, set_config_option, mcp_response, native Pi RPC commands, and Pi queue operations.
 * @summary Send command to task run
 */
export const TasksRunsCommandCreateBody = TaskRunCommandRequestApi

/**
 * Queue a Slack relay workflow to post a run message into the mapped Slack thread.
 * @summary Relay run message to Slack
 */
export const TasksRunsRelayMessageCreateBody = TaskRunRelayMessageRequestApi

/**
 * Update the output field for a task run (e.g., PR URL, commit SHA, etc.)
 * @summary Set run output
 */
export const TasksRunsSetOutputPartialUpdateBody = PatchedTaskRunSetOutputRequestApi

/**
 * Start an existing cloud run after any initial run-scoped attachments have been uploaded.
 * @summary Start task run
 */
export const TasksRunsStartCreateBody = TaskRunStartRequestApi

/**
 * Create a stable, editable artifact handle from direct markdown/text content or an existing run artifact. Slack adapters deliver into the mapped Slack thread; document artifacts use external connector storage when available.
 * @summary Create a living artifact for a task run
 */
export const TasksRunsLivingArtifactsCreateBody = TaskRunLivingArtifactCreateRequestApi

/**
 * Commit a new version to an existing living artifact handle.
 * @summary Edit a living artifact for a task run
 */
export const TasksRunsLivingArtifactsEditBody = TaskRunLivingArtifactEditRequestApi

/**
 * Renders a PostHog insight (ad-hoc query JSON or a saved insight) to a PNG server-side and registers it as a slack_file living artifact in one call. Blocks until the render finishes.
 * @summary Render an insight chart and attach it as a living artifact
 */
export const TasksRunsLivingArtifactsChartBody = TaskRunLivingArtifactChartRequestApi

/**
 * API for a task's thread — the human-only side conversation around a task. Messages
 * reach the agent only via the explicit send_to_agent action, gated to the task author.
 * @summary Post a thread message
 */
export const TasksThreadMessagesCreateBody = TaskThreadMessageWriteApi

/**
 * Task author only: forwards the message into the task's latest live run.
 * @summary Send a thread message to the agent
 */
export const TasksThreadMessagesSendToAgentCreateBody = TaskThreadMessageDTOApi

/**
 * Returns summary for the requested tasks: `id`, `title`, `repository`, `created_at`, `updated_at`, and the latest run's `status` and `environment`.
 * @summary Fetch task summaries by ID
 */
export const TasksSummariesCreateBody = TaskSummariesRequestApi

/**
 * Warm a full idling Run for a Code-app cloud task while the user composes: boot a sandbox, clone the repo, check out the branch, and start the agent, then idle awaiting the first message. On submit the normal create+run path transparently reuses and activates this Run; abandoned warms are reaped by the Run's inactivity timeout. Best-effort: returns an empty body when the feature flag is off, the warm pool is full, or the GitHub integration doesn't belong to the team.
 * @summary Warm a task sandbox
 */
export const TasksWarmCreateBody = WarmTaskRequestApi
