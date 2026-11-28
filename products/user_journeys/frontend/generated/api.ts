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
    CreateJourneyDeployApi,
    CreateJourneyInputApi,
    CreateJourneyRunApi,
    ElementPathsResultApi,
    JourneyApi,
    JourneyDeployDetailApi,
    JourneyFunnelQueryApi,
    JourneyRunApi,
    JourneyRunDetailApi,
    PaginatedJourneyDeployListApi,
    PaginatedJourneyListApi,
    PaginatedJourneyRunListApi,
    PatchedUpdateJourneyInputApi,
    UserJourneysDeploysListParams,
    UserJourneysElementPathsRetrieveParams,
    UserJourneysListParams,
    UserJourneysRunsListParams,
} from './api.schemas'

export const getUserJourneysListUrl = (projectId: string, params?: UserJourneysListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/user_journeys/?${stringifiedParams}`
        : `/api/projects/${projectId}/user_journeys/`
}

/**
 * List the project's journeys, newest first, each with its latest run.
 */
export const userJourneysList = async (
    projectId: string,
    params?: UserJourneysListParams,
    options?: RequestInit
): Promise<PaginatedJourneyListApi> => {
    return apiMutator<PaginatedJourneyListApi>(getUserJourneysListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getUserJourneysCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/user_journeys/`
}

/**
 * Create a journey.
 */
export const userJourneysCreate = async (
    projectId: string,
    createJourneyInputApi: CreateJourneyInputApi,
    options?: RequestInit
): Promise<JourneyApi> => {
    return apiMutator<JourneyApi>(getUserJourneysCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(createJourneyInputApi),
    })
}

export const getUserJourneysRunsListUrl = (
    projectId: string,
    journeyId: string,
    params?: UserJourneysRunsListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/user_journeys/${journeyId}/runs/?${stringifiedParams}`
        : `/api/projects/${projectId}/user_journeys/${journeyId}/runs/`
}

/**
 * List the journey's runs, newest first. Steps are left out; get a run to see them.
 */
export const userJourneysRunsList = async (
    projectId: string,
    journeyId: string,
    params?: UserJourneysRunsListParams,
    options?: RequestInit
): Promise<PaginatedJourneyRunListApi> => {
    return apiMutator<PaginatedJourneyRunListApi>(getUserJourneysRunsListUrl(projectId, journeyId, params), {
        ...options,
        method: 'GET',
    })
}

export const getUserJourneysRunsCreateUrl = (projectId: string, journeyId: string) => {
    return `/api/projects/${projectId}/user_journeys/${journeyId}/runs/`
}

/**
 * Start a run of the journey now. The run starts as pending and finishes in the background.
 */
export const userJourneysRunsCreate = async (
    projectId: string,
    journeyId: string,
    createJourneyRunApi?: CreateJourneyRunApi,
    options?: RequestInit
): Promise<JourneyRunApi> => {
    return apiMutator<JourneyRunApi>(getUserJourneysRunsCreateUrl(projectId, journeyId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(createJourneyRunApi),
    })
}

export const getUserJourneysRunsRetrieveUrl = (projectId: string, journeyId: string, id: string) => {
    return `/api/projects/${projectId}/user_journeys/${journeyId}/runs/${id}/`
}

/**
 * Get a run with each step's verdict and screenshot URLs.
 */
export const userJourneysRunsRetrieve = async (
    projectId: string,
    journeyId: string,
    id: string,
    options?: RequestInit
): Promise<JourneyRunDetailApi> => {
    return apiMutator<JourneyRunDetailApi>(getUserJourneysRunsRetrieveUrl(projectId, journeyId, id), {
        ...options,
        method: 'GET',
    })
}

export const getUserJourneysRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/user_journeys/${id}/`
}

/**
 * Get a journey.
 */
export const userJourneysRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<JourneyApi> => {
    return apiMutator<JourneyApi>(getUserJourneysRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getUserJourneysPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/user_journeys/${id}/`
}

/**
 * Change some fields of a journey.
 */
export const userJourneysPartialUpdate = async (
    projectId: string,
    id: string,
    patchedUpdateJourneyInputApi?: PatchedUpdateJourneyInputApi,
    options?: RequestInit
): Promise<JourneyApi> => {
    return apiMutator<JourneyApi>(getUserJourneysPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedUpdateJourneyInputApi),
    })
}

export const getUserJourneysDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/user_journeys/${id}/`
}

/**
 * Delete a journey.
 */
export const userJourneysDestroy = async (projectId: string, id: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getUserJourneysDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getUserJourneysFunnelQueryRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/user_journeys/${id}/funnel_query/`
}

/**
 * Get the funnel query that measures how many sessions complete the journey.
 */
export const userJourneysFunnelQueryRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<JourneyFunnelQueryApi> => {
    return apiMutator<JourneyFunnelQueryApi>(getUserJourneysFunnelQueryRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getUserJourneysDeploysListUrl = (projectId: string, params?: UserJourneysDeploysListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/user_journeys/deploys/?${stringifiedParams}`
        : `/api/projects/${projectId}/user_journeys/deploys/`
}

/**
 * List the project's deploys, newest deploy time first, each with the verdict on its runs.
 */
export const userJourneysDeploysList = async (
    projectId: string,
    params?: UserJourneysDeploysListParams,
    options?: RequestInit
): Promise<PaginatedJourneyDeployListApi> => {
    return apiMutator<PaginatedJourneyDeployListApi>(getUserJourneysDeploysListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getUserJourneysDeploysCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/user_journeys/deploys/`
}

/**
 * Record a deploy and start a run of the project's journeys against it. The runs finish in the background.
 */
export const userJourneysDeploysCreate = async (
    projectId: string,
    createJourneyDeployApi: CreateJourneyDeployApi,
    options?: RequestInit
): Promise<JourneyDeployDetailApi> => {
    return apiMutator<JourneyDeployDetailApi>(getUserJourneysDeploysCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(createJourneyDeployApi),
    })
}

export const getUserJourneysDeploysRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/user_journeys/deploys/${id}/`
}

/**
 * Get a deploy with the verdict on its runs. Poll it until `status` is neither `pending` nor `running`.
 */
export const userJourneysDeploysRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<JourneyDeployDetailApi> => {
    return apiMutator<JourneyDeployDetailApi>(getUserJourneysDeploysRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getUserJourneysElementPathsRetrieveUrl = (
    projectId: string,
    params: UserJourneysElementPathsRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/user_journeys/element_paths/?${stringifiedParams}`
        : `/api/projects/${projectId}/user_journeys/element_paths/`
}

/**
 * Find the most common paths that sessions take before and after a click on one element.
 */
export const userJourneysElementPathsRetrieve = async (
    projectId: string,
    params: UserJourneysElementPathsRetrieveParams,
    options?: RequestInit
): Promise<ElementPathsResultApi> => {
    return apiMutator<ElementPathsResultApi>(getUserJourneysElementPathsRetrieveUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}
