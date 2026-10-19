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
    ContactCheckResultApi,
    CreateResearchSourceApi,
    PatchedUpdateResearchSourceApi,
    ResearchDeskContactCheckListParams,
    ResearchDeskSessionsListParams,
    ResearchSessionDTOApi,
    ResearchSourceDTOApi,
} from './api.schemas'

export const getResearchDeskContactCheckListUrl = (projectId: string, params?: ResearchDeskContactCheckListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/research_desk/contact_check/?${stringifiedParams}`
        : `/api/projects/${projectId}/research_desk/contact_check/`
}

/**
 * Check whether PostHog recently contacted these people or this company for research.
 *
 * Returns every research touch found across registered sources and detected sessions.
 * A warning is advice: anyone can still reach out.
 */
export const researchDeskContactCheckList = async (
    projectId: string,
    params?: ResearchDeskContactCheckListParams,
    options?: RequestInit
): Promise<ContactCheckResultApi[]> => {
    return apiMutator<ContactCheckResultApi[]>(getResearchDeskContactCheckListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getResearchDeskSessionsListUrl = (projectId: string, params?: ResearchDeskSessionsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/research_desk/sessions/?${stringifiedParams}`
        : `/api/projects/${projectId}/research_desk/sessions/`
}

/**
 * List customer research sessions, ordered by start time, up to 500 per request.
 */
export const researchDeskSessionsList = async (
    projectId: string,
    params?: ResearchDeskSessionsListParams,
    options?: RequestInit
): Promise<ResearchSessionDTOApi[]> => {
    return apiMutator<ResearchSessionDTOApi[]>(getResearchDeskSessionsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getResearchDeskSourcesListUrl = (projectId: string) => {
    return `/api/projects/${projectId}/research_desk/sources/`
}

/**
 * List recruiting sources whose events count as research touches.
 */
export const researchDeskSourcesList = async (
    projectId: string,
    options?: RequestInit
): Promise<ResearchSourceDTOApi[]> => {
    return apiMutator<ResearchSourceDTOApi[]>(getResearchDeskSourcesListUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getResearchDeskSourcesCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/research_desk/sources/`
}

/**
 * Register a workflow, survey, cohort, or event as a recruiting source.
 */
export const researchDeskSourcesCreate = async (
    projectId: string,
    createResearchSourceApi: CreateResearchSourceApi,
    options?: RequestInit
): Promise<ResearchSourceDTOApi> => {
    return apiMutator<ResearchSourceDTOApi>(getResearchDeskSourcesCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(createResearchSourceApi),
    })
}

export const getResearchDeskSourcesPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/research_desk/sources/${id}/`
}

/**
 * Update a source's label, owner, product area, or active state.
 */
export const researchDeskSourcesPartialUpdate = async (
    projectId: string,
    id: string,
    patchedUpdateResearchSourceApi?: PatchedUpdateResearchSourceApi,
    options?: RequestInit
): Promise<ResearchSourceDTOApi> => {
    return apiMutator<ResearchSourceDTOApi>(getResearchDeskSourcesPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedUpdateResearchSourceApi),
    })
}
