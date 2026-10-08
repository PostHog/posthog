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
    DigestRunApi,
    PaginatedDigestRunListApi,
    PaginatedReviewRunListApi,
    PaginatedStamphogPullRequestListApi,
    PaginatedStamphogRepoConfigListApi,
    PatchedStamphogRepoConfigWriteApi,
    ReviewRequestApi,
    ReviewRequestResponseApi,
    ReviewRunApi,
    StamphogAddRepositoryApi,
    StamphogAvailableRepositoriesApi,
    StamphogDigestRunsListParams,
    StamphogInstallInfoApi,
    StamphogPullRequestApi,
    StamphogPullRequestsListParams,
    StamphogRepoConfigApi,
    StamphogRepoConfigWriteApi,
    StamphogRepoConfigsAvailableRepositoriesRetrieveParams,
    StamphogRepoConfigsListParams,
    StamphogReviewRunsListParams,
    StamphogSyncInstallationRequestApi,
    StamphogSyncInstallationResponseApi,
} from './api.schemas'

export const getStamphogDigestRunsListUrl = (projectId: string, params?: StamphogDigestRunsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/stamphog/digest_runs/?${stringifiedParams}`
        : `/api/projects/${projectId}/stamphog/digest_runs/`
}

/**
 * Read-only history of posted (or attempted) digests, filterable by Slack channel.
 */
export const stamphogDigestRunsList = async (
    projectId: string,
    params?: StamphogDigestRunsListParams,
    options?: RequestInit
): Promise<PaginatedDigestRunListApi> => {
    return apiMutator<PaginatedDigestRunListApi>(getStamphogDigestRunsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getStamphogDigestRunsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/stamphog/digest_runs/${id}/`
}

/**
 * Read-only history of posted (or attempted) digests, filterable by Slack channel.
 */
export const stamphogDigestRunsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<DigestRunApi> => {
    return apiMutator<DigestRunApi>(getStamphogDigestRunsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getStamphogPullRequestsListUrl = (projectId: string, params?: StamphogPullRequestsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/stamphog/pull_requests/?${stringifiedParams}`
        : `/api/projects/${projectId}/stamphog/pull_requests/`
}

/**
 * Read-only pull requests stamphog knows about, filterable by PR number and merge state.
 */
export const stamphogPullRequestsList = async (
    projectId: string,
    params?: StamphogPullRequestsListParams,
    options?: RequestInit
): Promise<PaginatedStamphogPullRequestListApi> => {
    return apiMutator<PaginatedStamphogPullRequestListApi>(getStamphogPullRequestsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getStamphogPullRequestsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/stamphog/pull_requests/${id}/`
}

/**
 * Read-only pull requests stamphog knows about, filterable by PR number and merge state.
 */
export const stamphogPullRequestsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<StamphogPullRequestApi> => {
    return apiMutator<StamphogPullRequestApi>(getStamphogPullRequestsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getStamphogRepoConfigsListUrl = (projectId: string, params?: StamphogRepoConfigsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/stamphog/repo_configs/?${stringifiedParams}`
        : `/api/projects/${projectId}/stamphog/repo_configs/`
}

/**
 * Per-repo stamphog settings — enable/disable review, GitHub App installation, policy overrides.
 */
export const stamphogRepoConfigsList = async (
    projectId: string,
    params?: StamphogRepoConfigsListParams,
    options?: RequestInit
): Promise<PaginatedStamphogRepoConfigListApi> => {
    return apiMutator<PaginatedStamphogRepoConfigListApi>(getStamphogRepoConfigsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getStamphogRepoConfigsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/stamphog/repo_configs/`
}

/**
 * Per-repo stamphog settings — enable/disable review, GitHub App installation, policy overrides.
 */
export const stamphogRepoConfigsCreate = async (
    projectId: string,
    stamphogRepoConfigWriteApi: StamphogRepoConfigWriteApi,
    options?: RequestInit
): Promise<StamphogRepoConfigApi> => {
    return apiMutator<StamphogRepoConfigApi>(getStamphogRepoConfigsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(stamphogRepoConfigWriteApi),
    })
}

export const getStamphogRepoConfigsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/stamphog/repo_configs/${id}/`
}

/**
 * Per-repo stamphog settings — enable/disable review, GitHub App installation, policy overrides.
 */
export const stamphogRepoConfigsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<StamphogRepoConfigApi> => {
    return apiMutator<StamphogRepoConfigApi>(getStamphogRepoConfigsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getStamphogRepoConfigsUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/stamphog/repo_configs/${id}/`
}

/**
 * Per-repo stamphog settings — enable/disable review, GitHub App installation, policy overrides.
 */
export const stamphogRepoConfigsUpdate = async (
    projectId: string,
    id: string,
    stamphogRepoConfigWriteApi: StamphogRepoConfigWriteApi,
    options?: RequestInit
): Promise<StamphogRepoConfigApi> => {
    return apiMutator<StamphogRepoConfigApi>(getStamphogRepoConfigsUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(stamphogRepoConfigWriteApi),
    })
}

export const getStamphogRepoConfigsPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/stamphog/repo_configs/${id}/`
}

/**
 * Per-repo stamphog settings — enable/disable review, GitHub App installation, policy overrides.
 */
export const stamphogRepoConfigsPartialUpdate = async (
    projectId: string,
    id: string,
    patchedStamphogRepoConfigWriteApi?: PatchedStamphogRepoConfigWriteApi,
    options?: RequestInit
): Promise<StamphogRepoConfigApi> => {
    return apiMutator<StamphogRepoConfigApi>(getStamphogRepoConfigsPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedStamphogRepoConfigWriteApi),
    })
}

export const getStamphogRepoConfigsDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/stamphog/repo_configs/${id}/`
}

/**
 * Per-repo stamphog settings — enable/disable review, GitHub App installation, policy overrides.
 */
export const stamphogRepoConfigsDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getStamphogRepoConfigsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getStamphogRepoConfigsAddRepositoryCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/stamphog/repo_configs/add_repository/`
}

/**
 * Turn reviews on for a repository from the project's connected GitHub installations. Creates the repo config, or turns an existing one back on. Needs the editor level on stamphog.
 */
export const stamphogRepoConfigsAddRepositoryCreate = async (
    projectId: string,
    stamphogAddRepositoryApi: StamphogAddRepositoryApi,
    options?: RequestInit
): Promise<StamphogRepoConfigApi> => {
    return apiMutator<StamphogRepoConfigApi>(getStamphogRepoConfigsAddRepositoryCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(stamphogAddRepositoryApi),
    })
}

export const getStamphogRepoConfigsAvailableRepositoriesRetrieveUrl = (
    projectId: string,
    params?: StamphogRepoConfigsAvailableRepositoriesRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/stamphog/repo_configs/available_repositories/?${stringifiedParams}`
        : `/api/projects/${projectId}/stamphog/repo_configs/available_repositories/`
}

/**
 * List repositories from the project's connected GitHub installations that are not added to stamphog yet, so they can be added with add_repository.
 */
export const stamphogRepoConfigsAvailableRepositoriesRetrieve = async (
    projectId: string,
    params?: StamphogRepoConfigsAvailableRepositoriesRetrieveParams,
    options?: RequestInit
): Promise<StamphogAvailableRepositoriesApi> => {
    return apiMutator<StamphogAvailableRepositoriesApi>(
        getStamphogRepoConfigsAvailableRepositoriesRetrieveUrl(projectId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getStamphogRepoConfigsInstallInfoRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/stamphog/repo_configs/install_info/`
}

/**
 * Per-repo stamphog settings — enable/disable review, GitHub App installation, policy overrides.
 */
export const stamphogRepoConfigsInstallInfoRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<StamphogInstallInfoApi> => {
    return apiMutator<StamphogInstallInfoApi>(getStamphogRepoConfigsInstallInfoRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getStamphogRepoConfigsSyncInstallationCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/stamphog/repo_configs/sync_installation/`
}

/**
 * Per-repo stamphog settings — enable/disable review, GitHub App installation, policy overrides.
 */
export const stamphogRepoConfigsSyncInstallationCreate = async (
    projectId: string,
    stamphogSyncInstallationRequestApi: StamphogSyncInstallationRequestApi,
    options?: RequestInit
): Promise<StamphogSyncInstallationResponseApi> => {
    return apiMutator<StamphogSyncInstallationResponseApi>(getStamphogRepoConfigsSyncInstallationCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(stamphogSyncInstallationRequestApi),
    })
}

export const getStamphogReviewRunsListUrl = (projectId: string, params?: StamphogReviewRunsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/stamphog/review_runs/?${stringifiedParams}`
        : `/api/projects/${projectId}/stamphog/review_runs/`
}

/**
 * History of stamphog review runs, filterable by repository, PR number, and status, plus manual review requests.
 */
export const stamphogReviewRunsList = async (
    projectId: string,
    params?: StamphogReviewRunsListParams,
    options?: RequestInit
): Promise<PaginatedReviewRunListApi> => {
    return apiMutator<PaginatedReviewRunListApi>(getStamphogReviewRunsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getStamphogReviewRunsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/stamphog/review_runs/`
}

/**
 * History of stamphog review runs, filterable by repository, PR number, and status, plus manual review requests.
 */
export const stamphogReviewRunsCreate = async (
    projectId: string,
    reviewRequestApi: ReviewRequestApi,
    options?: RequestInit
): Promise<ReviewRequestResponseApi> => {
    return apiMutator<ReviewRequestResponseApi>(getStamphogReviewRunsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(reviewRequestApi),
    })
}

export const getStamphogReviewRunsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/stamphog/review_runs/${id}/`
}

/**
 * History of stamphog review runs, filterable by repository, PR number, and status, plus manual review requests.
 */
export const stamphogReviewRunsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<ReviewRunApi> => {
    return apiMutator<ReviewRunApi>(getStamphogReviewRunsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}
