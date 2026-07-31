/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import { PatchedSessionSummariesConfigApi, SessionSummariesApi } from './api.zod.schemas'

/**
 * Update the team's session summaries configuration (product context used to tailor single-session replay summaries).
 */
export const UpdateSessionSummariesConfigBody = PatchedSessionSummariesConfigApi

/**
 * Generate AI summary for a group of session recordings to find patterns and generate a notebook.
 */
export const CreateSessionSummariesBody = SessionSummariesApi
