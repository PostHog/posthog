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
    WizardSessionsListParams,
} from './api.schemas'

export const getWizardSessionsListUrl = (projectId: string, params?: WizardSessionsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/wizard/sessions/?${stringifiedParams}`
        : `/api/projects/${projectId}/wizard/sessions/`
}

/**
 * List wizard sessions for the project, ordered by started_at desc. Optional filters: ?workflow_id=<id> and ?skill_id=<id>.
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
 * Upsert a wizard session. The session_id key determines whether this creates a new row or replaces an existing one. Always returns 201.
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

export const getWizardSessionsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/wizard/sessions/${id}/`
}

/**
 * Retrieve a single wizard session by its session_id (path parameter {id}).
 */
export const wizardSessionsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<WizardSessionDTOApi> => {
    return apiMutator<WizardSessionDTOApi>(getWizardSessionsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}
