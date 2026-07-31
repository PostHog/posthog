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
    PatchedSessionRecordingApi,
    PatchedSessionRecordingPlaylistApi,
    SessionRecordingApi,
    SessionRecordingBulkDeleteRequestApi,
    SessionRecordingPlaylistApi,
    SessionSummariesApi,
} from './api.zod.schemas'

export const SessionRecordingPlaylistsCreateBody = SessionRecordingPlaylistApi

export const SessionRecordingPlaylistsUpdateBody = SessionRecordingPlaylistApi

export const SessionRecordingPlaylistsPartialUpdateBody = PatchedSessionRecordingPlaylistApi

export const SessionRecordingPlaylistsRecordingsCreateBody = SessionRecordingPlaylistApi

export const SessionRecordingsUpdateBody = SessionRecordingApi

export const SessionRecordingsPartialUpdateBody = PatchedSessionRecordingApi

/**
 * Delete a batch of session recordings by session ID. Deletion is permanent and cannot be undone. IDs that don't match an existing recording are skipped and counted in `total_requested` but not `deleted_count`.
 */
export const SessionRecordingsBulkDeleteCreateBody = SessionRecordingBulkDeleteRequestApi

/**
 * Generate AI individual summary for each session, without grouping.
 */
export const CreateSessionSummariesIndividuallyBody = SessionSummariesApi
