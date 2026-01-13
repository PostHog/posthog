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
    ApproveRunInputApi,
    ArtifactApi,
    ArtifactUploadedApi,
    CreateRunInputApi,
    CreateRunResultApi,
    PaginatedProjectListApi,
    PaginatedSnapshotListApi,
    ProjectApi,
    RunApi,
    UploadUrlApi,
    UploadUrlRequestApi,
    VisualReviewProjectsListParams,
    VisualReviewRunsSnapshotsListParams,
} from './api.schemas'

/**
 * List all projects for the team.
 */
export type visualReviewProjectsListResponse200 = {
    data: PaginatedProjectListApi
    status: 200
}

export type visualReviewProjectsListResponseSuccess = visualReviewProjectsListResponse200 & {
    headers: Headers
}
export type visualReviewProjectsListResponse = visualReviewProjectsListResponseSuccess

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
): Promise<visualReviewProjectsListResponse> => {
    return apiMutator<visualReviewProjectsListResponse>(getVisualReviewProjectsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

/**
 * Create a new project.
 */
export type visualReviewProjectsCreateResponse201 = {
    data: ProjectApi
    status: 201
}

export type visualReviewProjectsCreateResponseSuccess = visualReviewProjectsCreateResponse201 & {
    headers: Headers
}
export type visualReviewProjectsCreateResponse = visualReviewProjectsCreateResponseSuccess

export const getVisualReviewProjectsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/visual_review/projects/`
}

export const visualReviewProjectsCreate = async (
    projectId: string,
    options?: RequestInit
): Promise<visualReviewProjectsCreateResponse> => {
    return apiMutator<visualReviewProjectsCreateResponse>(getVisualReviewProjectsCreateUrl(projectId), {
        ...options,
        method: 'POST',
    })
}

/**
 * Get a project by ID.
 */
export type visualReviewProjectsRetrieveResponse200 = {
    data: ProjectApi
    status: 200
}

export type visualReviewProjectsRetrieveResponseSuccess = visualReviewProjectsRetrieveResponse200 & {
    headers: Headers
}
export type visualReviewProjectsRetrieveResponse = visualReviewProjectsRetrieveResponseSuccess

export const getVisualReviewProjectsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/visual_review/projects/${id}/`
}

export const visualReviewProjectsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<visualReviewProjectsRetrieveResponse> => {
    return apiMutator<visualReviewProjectsRetrieveResponse>(getVisualReviewProjectsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

/**
 * Register an artifact after it has been uploaded to S3.
 */
export type visualReviewProjectsArtifactsCreateResponse201 = {
    data: ArtifactApi
    status: 201
}

export type visualReviewProjectsArtifactsCreateResponseSuccess = visualReviewProjectsArtifactsCreateResponse201 & {
    headers: Headers
}
export type visualReviewProjectsArtifactsCreateResponse = visualReviewProjectsArtifactsCreateResponseSuccess

export const getVisualReviewProjectsArtifactsCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/visual_review/projects/${id}/artifacts/`
}

export const visualReviewProjectsArtifactsCreate = async (
    projectId: string,
    id: string,
    artifactUploadedApi: ArtifactUploadedApi,
    options?: RequestInit
): Promise<visualReviewProjectsArtifactsCreateResponse> => {
    return apiMutator<visualReviewProjectsArtifactsCreateResponse>(
        getVisualReviewProjectsArtifactsCreateUrl(projectId, id),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(artifactUploadedApi),
        }
    )
}

/**
 * Get a presigned URL for uploading an artifact.
 */
export type visualReviewProjectsUploadUrlCreateResponse200 = {
    data: UploadUrlApi
    status: 200
}

export type visualReviewProjectsUploadUrlCreateResponseSuccess = visualReviewProjectsUploadUrlCreateResponse200 & {
    headers: Headers
}
export type visualReviewProjectsUploadUrlCreateResponse = visualReviewProjectsUploadUrlCreateResponseSuccess

export const getVisualReviewProjectsUploadUrlCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/visual_review/projects/${id}/upload-url/`
}

export const visualReviewProjectsUploadUrlCreate = async (
    projectId: string,
    id: string,
    uploadUrlRequestApi: UploadUrlRequestApi,
    options?: RequestInit
): Promise<visualReviewProjectsUploadUrlCreateResponse> => {
    return apiMutator<visualReviewProjectsUploadUrlCreateResponse>(
        getVisualReviewProjectsUploadUrlCreateUrl(projectId, id),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(uploadUrlRequestApi),
        }
    )
}

/**
 * Create a new run from a CI manifest.
 */
export type visualReviewRunsCreateResponse201 = {
    data: CreateRunResultApi
    status: 201
}

export type visualReviewRunsCreateResponseSuccess = visualReviewRunsCreateResponse201 & {
    headers: Headers
}
export type visualReviewRunsCreateResponse = visualReviewRunsCreateResponseSuccess

export const getVisualReviewRunsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/visual_review/runs/`
}

export const visualReviewRunsCreate = async (
    projectId: string,
    createRunInputApi: CreateRunInputApi,
    options?: RequestInit
): Promise<visualReviewRunsCreateResponse> => {
    return apiMutator<visualReviewRunsCreateResponse>(getVisualReviewRunsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(createRunInputApi),
    })
}

/**
 * Get run status and summary.
 */
export type visualReviewRunsRetrieveResponse200 = {
    data: RunApi
    status: 200
}

export type visualReviewRunsRetrieveResponseSuccess = visualReviewRunsRetrieveResponse200 & {
    headers: Headers
}
export type visualReviewRunsRetrieveResponse = visualReviewRunsRetrieveResponseSuccess

export const getVisualReviewRunsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/visual_review/runs/${id}/`
}

export const visualReviewRunsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<visualReviewRunsRetrieveResponse> => {
    return apiMutator<visualReviewRunsRetrieveResponse>(getVisualReviewRunsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

/**
 * Approve visual changes for snapshots in this run.
 */
export type visualReviewRunsApproveCreateResponse200 = {
    data: RunApi
    status: 200
}

export type visualReviewRunsApproveCreateResponseSuccess = visualReviewRunsApproveCreateResponse200 & {
    headers: Headers
}
export type visualReviewRunsApproveCreateResponse = visualReviewRunsApproveCreateResponseSuccess

export const getVisualReviewRunsApproveCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/visual_review/runs/${id}/approve/`
}

export const visualReviewRunsApproveCreate = async (
    projectId: string,
    id: string,
    approveRunInputApi: ApproveRunInputApi,
    options?: RequestInit
): Promise<visualReviewRunsApproveCreateResponse> => {
    return apiMutator<visualReviewRunsApproveCreateResponse>(getVisualReviewRunsApproveCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(approveRunInputApi),
    })
}

/**
 * Signal that all artifacts have been uploaded. Triggers diff processing.
 */
export type visualReviewRunsCompleteCreateResponse200 = {
    data: RunApi
    status: 200
}

export type visualReviewRunsCompleteCreateResponseSuccess = visualReviewRunsCompleteCreateResponse200 & {
    headers: Headers
}
export type visualReviewRunsCompleteCreateResponse = visualReviewRunsCompleteCreateResponseSuccess

export const getVisualReviewRunsCompleteCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/visual_review/runs/${id}/complete/`
}

export const visualReviewRunsCompleteCreate = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<visualReviewRunsCompleteCreateResponse> => {
    return apiMutator<visualReviewRunsCompleteCreateResponse>(getVisualReviewRunsCompleteCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
    })
}

/**
 * Get all snapshots for a run with diff results.
 */
export type visualReviewRunsSnapshotsListResponse200 = {
    data: PaginatedSnapshotListApi
    status: 200
}

export type visualReviewRunsSnapshotsListResponseSuccess = visualReviewRunsSnapshotsListResponse200 & {
    headers: Headers
}
export type visualReviewRunsSnapshotsListResponse = visualReviewRunsSnapshotsListResponseSuccess

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
): Promise<visualReviewRunsSnapshotsListResponse> => {
    return apiMutator<visualReviewRunsSnapshotsListResponse>(
        getVisualReviewRunsSnapshotsListUrl(projectId, id, params),
        {
            ...options,
            method: 'GET',
        }
    )
}
