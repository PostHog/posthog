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
    CreateProjectInputApi,
    CreateRunInputApi,
    CreateRunResultApi,
    PaginatedProjectListApi,
    PaginatedRunListApi,
    PaginatedSnapshotListApi,
    PatchedUpdateProjectRequestInputApi,
    ProjectApi,
    RunApi,
    VisualReviewProjectsListParams,
    VisualReviewRunsListParams,
    VisualReviewRunsSnapshotsListParams,
} from './api.schemas'

/**
 * List all projects for the team.
 */
export const getVisualReviewProjectsListUrl = (projectId: string, params?: VisualReviewProjectsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/visual_review/projects/?${stringifiedParams}`
        : `/api/projects/${projectId}/visual_review/projects/`
}

export const visualReviewProjectsList = async (
    projectId: string,
    params?: VisualReviewProjectsListParams,
    options?: RequestInit
): Promise<PaginatedProjectListApi> => {
    return apiMutator<PaginatedProjectListApi>(getVisualReviewProjectsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

/**
 * Create a new project.
 */
export const getVisualReviewProjectsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/visual_review/projects/`
}

export const visualReviewProjectsCreate = async (
    projectId: string,
    createProjectInputApi: CreateProjectInputApi,
    options?: RequestInit
): Promise<ProjectApi> => {
    return apiMutator<ProjectApi>(getVisualReviewProjectsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(createProjectInputApi),
    })
}

/**
 * Get a project by ID.
 */
export const getVisualReviewProjectsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/visual_review/projects/${id}/`
}

export const visualReviewProjectsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<ProjectApi> => {
    return apiMutator<ProjectApi>(getVisualReviewProjectsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

/**
 * Update a project's settings.
 */
export const getVisualReviewProjectsPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/visual_review/projects/${id}/`
}

export const visualReviewProjectsPartialUpdate = async (
    projectId: string,
    id: string,
    patchedUpdateProjectRequestInputApi: PatchedUpdateProjectRequestInputApi,
    options?: RequestInit
): Promise<ProjectApi> => {
    return apiMutator<ProjectApi>(getVisualReviewProjectsPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedUpdateProjectRequestInputApi),
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
