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
    BulkIntervieweeContextRequestApi,
    IntervieweeContextApi,
    IntervieweeIdentifierRequestApi,
    PatchedIntervieweeContextApi,
    PatchedUserInterviewApi,
    PatchedUserInterviewTopicApi,
    PreviewInviteRequestApi,
    SendInvitesRequestApi,
    UserInterviewApi,
    UserInterviewSearchRequestApi,
    UserInterviewTopicApi,
} from './api.zod.schemas'

/**
 * Planned user interview topics: who we want to target and what we want to ask about.
 */
export const UserInterviewTopicsCreateBody = UserInterviewTopicApi

/**
 * Planned user interview topics: who we want to target and what we want to ask about.
 */
export const UserInterviewTopicsUpdateBody = UserInterviewTopicApi

/**
 * Planned user interview topics: who we want to target and what we want to ask about.
 */
export const UserInterviewTopicsPartialUpdateBody = PatchedUserInterviewTopicApi

/**
 * Add a single interviewee to this topic. Email-shaped identifiers (including the `Display Name <email@host>` form) are appended to `interviewee_emails`; everything else is appended to `interviewee_distinct_ids`. Idempotent — adding an identifier that's already present leaves the topic unchanged. Returns the updated topic.
 */
export const UserInterviewTopicsAddIntervieweeCreateBody = IntervieweeIdentifierRequestApi

/**
 * Render the invite email exactly as a specific targeted interviewee would receive it — personalized subject and body — without sending anything and without creating or reading any share links. Pass `interviewee_identifier` to preview for a particular person, or omit it to preview for the first targeted interviewee. The body always shows an illustrative placeholder link (`is_preview_link: true`), never a live interview URL.
 */
export const UserInterviewTopicsPreviewInviteCreateBody = PreviewInviteRequestApi

/**
 * Remove an interviewee from this topic. Drops the identifier from both `interviewee_emails` and `interviewee_distinct_ids`, and disables any active SharingConfiguration linked to an IntervieweeContext for that identifier on this topic so the removed person can no longer open their interview link. Idempotent — removing an identifier that isn't present is a no-op. Returns the updated topic.
 */
export const UserInterviewTopicsRemoveIntervieweeCreateBody = IntervieweeIdentifierRequestApi

/**
 * Generate (if needed) and email a personalized public interview link to every targeted interviewee on this topic whose identifier is an email address. Distinct-ID-only interviewees are skipped and surfaced in the response. Each invite is keyed on the underlying SharingConfiguration so re-runs after token rotation produce a fresh send.
 */
export const UserInterviewTopicsSendInvitesCreateBody = SendInvitesRequestApi

/**
 * Per-interviewee extra context for a user interview topic. At most one row per (topic, interviewee_identifier).
 */
export const UserInterviewTopicsIntervieweesCreateBody = IntervieweeContextApi

/**
 * Per-interviewee extra context for a user interview topic. At most one row per (topic, interviewee_identifier).
 */
export const UserInterviewTopicsIntervieweesUpdateBody = IntervieweeContextApi

/**
 * Per-interviewee extra context for a user interview topic. At most one row per (topic, interviewee_identifier).
 */
export const UserInterviewTopicsIntervieweesPartialUpdateBody = PatchedIntervieweeContextApi

/**
 * Create up to 500 interviewee context rows for a topic in a single request. Rows whose (topic, interviewee_identifier) already exists are skipped — the response surfaces an `inserted_count`, a `skipped_count`, and the `skipped_identifiers` so the caller can reconcile. Items must have unique `interviewee_identifier` values within the batch.
 */
export const UserInterviewTopicsIntervieweesBulkCreateBody = BulkIntervieweeContextRequestApi

export const UserInterviewsCreateBody = UserInterviewApi

export const UserInterviewsUpdateBody = UserInterviewApi

export const UserInterviewsPartialUpdateBody = PatchedUserInterviewApi

/**
 * Embed `query` with the same model used to index interview transcripts and summaries, then return the top matches by cosine distance. Each match is a single (interview, document_type) pair — an interview can appear up to twice if both its transcript and summary score above other interviews. Useful for surfacing relevant interview snippets in natural language, without exact keyword matches.
 * @summary Search interview responses by semantic similarity
 */
export const UserInterviewsSearchCreateBody = UserInterviewSearchRequestApi
