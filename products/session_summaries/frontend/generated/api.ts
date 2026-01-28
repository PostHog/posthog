/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import { apiMutator } from '../../../../frontend/src/lib/api-orval-mutator'
import type { SessionSummariesApi } from './api.schemas'

/**
 * Generate AI summary for a group of session recordings to find patterns and generate a notebook.
 */
export const getCreateSessionSummariesUrl = (projectId: string) => {
    return `/api/environments/${projectId}/session_summaries/create_session_summaries/`
}

export const createSessionSummaries = async (
    projectId: string,
    sessionSummariesApi: SessionSummariesApi,
    options?: RequestInit
): Promise<SessionSummariesApi> => {
    return apiMutator<SessionSummariesApi>(getCreateSessionSummariesUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(sessionSummariesApi),
    })
}

/**
 * Generate AI individual summary for each session, without grouping.
 */
export const getCreateSessionSummariesIndividuallyUrl = (projectId: string) => {
    return `/api/environments/${projectId}/session_summaries/create_session_summaries_individually/`
}

export const createSessionSummariesIndividually = async (
    projectId: string,
    sessionSummariesApi: SessionSummariesApi,
    options?: RequestInit
): Promise<SessionSummariesApi> => {
    return apiMutator<SessionSummariesApi>(getCreateSessionSummariesIndividuallyUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(sessionSummariesApi),
    })
}
