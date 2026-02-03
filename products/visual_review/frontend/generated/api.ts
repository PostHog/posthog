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
import type {
    ApproveRunRequestInputApi,
    CreateRepoInputApi,
    CreateRunInputApi,
    CreateRunResultApi,
    PaginatedRepoListApi,
    PaginatedRunListApi,
    PaginatedSnapshotListApi,
    PatchedUpdateRepoRequestInputApi,
    RepoApi,
    RunApi,
    VisualReviewReposListParams,
    VisualReviewRunsListParams,
    VisualReviewRunsSnapshotsListParams,
} from './api.schemas'

/**
 * List all projects for the team.
 */
export const getVisualReviewReposListUrl = (projectId: string, params?: VisualReviewReposListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/visual_review/repos/?${stringifiedParams}`
        : `/api/projects/${projectId}/visual_review/repos/`
}

export const visualReviewReposList = async (
    projectId: string,
    params?: VisualReviewReposListParams,
    options?: RequestInit
): Promise<PaginatedRepoListApi> => {
    return apiMutator<PaginatedRepoListApi>(getVisualReviewReposListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

/**
 * Create a new repo.
 */
export const getVisualReviewReposCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/visual_review/repos/`
}

export const visualReviewReposCreate = async (
    projectId: string,
    createRepoInputApi: CreateRepoInputApi,
    options?: RequestInit
): Promise<RepoApi> => {
    return apiMutator<RepoApi>(getVisualReviewReposCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(createRepoInputApi),
    })
}

/**
 * Get a repo by ID.
 */
export const getVisualReviewReposRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/visual_review/repos/${id}/`
}

export const visualReviewReposRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<RepoApi> => {
    return apiMutator<RepoApi>(getVisualReviewReposRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

/**
 * Update a repo's settings.
 */
export const getVisualReviewReposPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/visual_review/repos/${id}/`
}

export const visualReviewReposPartialUpdate = async (
    projectId: string,
    id: string,
    patchedUpdateRepoRequestInputApi: PatchedUpdateRepoRequestInputApi,
    options?: RequestInit
): Promise<RepoApi> => {
    return apiMutator<RepoApi>(getVisualReviewReposPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedUpdateRepoRequestInputApi),
    })
}

/**
 * List all runs for the team.
 */
export const getVisualReviewRunsListUrl = (projectId: string, params?: VisualReviewRunsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/visual_review/runs/?${stringifiedParams}`
        : `/api/projects/${projectId}/visual_review/runs/`
}

export const visualReviewRunsList = async (
    projectId: string,
    params?: VisualReviewRunsListParams,
    options?: RequestInit
): Promise<PaginatedRunListApi> => {
    return apiMutator<PaginatedRunListApi>(getVisualReviewRunsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

/**
 * Create a new run from a CI manifest.
 */
export const getVisualReviewRunsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/visual_review/runs/`
}

export const visualReviewRunsCreate = async (
    projectId: string,
    createRunInputApi: CreateRunInputApi,
    options?: RequestInit
): Promise<CreateRunResultApi> => {
    return apiMutator<CreateRunResultApi>(getVisualReviewRunsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(createRunInputApi),
    })
}

/**
 * Get run status and summary.
 */
export const getVisualReviewRunsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/visual_review/runs/${id}/`
}

export const visualReviewRunsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<RunApi> => {
    return apiMutator<RunApi>(getVisualReviewRunsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

/**
 * Approve visual changes for snapshots in this run.
 */
export const getVisualReviewRunsApproveCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/visual_review/runs/${id}/approve/`
}

export const visualReviewRunsApproveCreate = async (
    projectId: string,
    id: string,
    approveRunRequestInputApi: ApproveRunRequestInputApi,
    options?: RequestInit
): Promise<RunApi> => {
    return apiMutator<RunApi>(getVisualReviewRunsApproveCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(approveRunRequestInputApi),
    })
}

/**
 * Signal that all artifacts have been uploaded. Triggers diff processing.
 */
export const getVisualReviewRunsCompleteCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/visual_review/runs/${id}/complete/`
}

export const visualReviewRunsCompleteCreate = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<RunApi> => {
    return apiMutator<RunApi>(getVisualReviewRunsCompleteCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
    })
}

/**
 * Get all snapshots for a run with diff results.
 */
export const getVisualReviewRunsSnapshotsListUrl = (
    projectId: string,
    id: string,
    params?: VisualReviewRunsSnapshotsListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/visual_review/runs/${id}/snapshots/?${stringifiedParams}`
        : `/api/projects/${projectId}/visual_review/runs/${id}/snapshots/`
}

export const visualReviewRunsSnapshotsList = async (
    projectId: string,
    id: string,
    params?: VisualReviewRunsSnapshotsListParams,
    options?: RequestInit
): Promise<PaginatedSnapshotListApi> => {
    return apiMutator<PaginatedSnapshotListApi>(getVisualReviewRunsSnapshotsListUrl(projectId, id, params), {
        ...options,
        method: 'GET',
    })
}
