import { apiMutator } from '../../../../frontend/src/lib/api-orval-mutator'
/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import type {
    PaginatedWizardSessionDTOListApi,
    UpsertWizardSessionRequestApi,
    WizardSessionDTOApi,
    WizardSessionsLatestRetrieveParams,
    WizardSessionsListParams,
    WizardSessionsStreamRetrieveParams,
} from './api.schemas'

export const getWizardSessionsListUrl = (projectId: string, params?: WizardSessionsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/wizard/sessions/?${stringifiedParams}`
        : `/api/projects/${projectId}/wizard/sessions/`
}

/**
 * List wizard sessions for the project, ordered by started_at desc. This should only be called by the PostHog Wizard. Optional filters: ?workflow_id=<id> and ?skill_id=<id>.
 */
export const wizardSessionsList = async (
    projectId: string,
    params?: WizardSessionsListParams,
    options?: RequestInit
): Promise<PaginatedWizardSessionDTOListApi> => {
    return apiMutator<PaginatedWizardSessionDTOListApi>(getWizardSessionsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getWizardSessionsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/wizard/sessions/`
}

/**
 * Upsert a wizard session. The `session_id` key is the idempotency anchor — reposting the same `session_id` replaces the existing row. Returns 201 on create, 200 on update.
 */
export const wizardSessionsCreate = async (
    projectId: string,
    upsertWizardSessionRequestApi: UpsertWizardSessionRequestApi,
    options?: RequestInit
): Promise<WizardSessionDTOApi> => {
    return apiMutator<WizardSessionDTOApi>(getWizardSessionsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(upsertWizardSessionRequestApi),
    })
}

export const getWizardSessionsRetrieveUrl = (projectId: string, sessionId: string) => {
    return `/api/projects/${projectId}/wizard/sessions/${sessionId}/`
}

/**
 * Retrieve a single wizard session by its session_id.
 */
export const wizardSessionsRetrieve = async (
    projectId: string,
    sessionId: string,
    options?: RequestInit
): Promise<WizardSessionDTOApi> => {
    return apiMutator<WizardSessionDTOApi>(getWizardSessionsRetrieveUrl(projectId, sessionId), {
        ...options,
        method: 'GET',
    })
}

export const getWizardSessionsLatestRetrieveUrl = (projectId: string, params: WizardSessionsLatestRetrieveParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/wizard/sessions/latest/?${stringifiedParams}`
        : `/api/projects/${projectId}/wizard/sessions/latest/`
}

/**
 * Return the single most-recent wizard session for a workflow (and optional skill), or 204 if none exists. Unlike `list`, this is a point lookup the app shell uses to decide whether to open the live SSE stream — it never returns a collection, and 'no run' is a 204 rather than a 404 so clients don't conflate it with a missing endpoint.
 */
export const wizardSessionsLatestRetrieve = async (
    projectId: string,
    params: WizardSessionsLatestRetrieveParams,
    options?: RequestInit
): Promise<WizardSessionDTOApi | void> => {
    return apiMutator<WizardSessionDTOApi | void>(getWizardSessionsLatestRetrieveUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getWizardSessionsStreamRetrieveUrl = (projectId: string, params: WizardSessionsStreamRetrieveParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/wizard/sessions/stream/?${stringifiedParams}`
        : `/api/projects/${projectId}/wizard/sessions/stream/`
}

/**
 * Server-Sent Events stream of wizard session updates for a (workflow_id, skill_id) pair. On connect, the current latest session (if any) is emitted as the first event; subsequent upserts are streamed in real time. The server closes the connection after 900 seconds with an `event: end` line so the client (EventSource) can reconnect.
 *
 * **SDK consumers**: do not call the generated fetch wrapper for this path — it will buffer the entire infinite stream. Use the URL builder (`getWizardSessionsStreamRetrieveUrl`) with the browser's `EventSource` API instead.
 */
export const wizardSessionsStreamRetrieve = async (
    projectId: string,
    params: WizardSessionsStreamRetrieveParams,
    options?: RequestInit
): Promise<string> => {
    return apiMutator<string>(getWizardSessionsStreamRetrieveUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}
