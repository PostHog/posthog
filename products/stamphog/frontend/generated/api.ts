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
    CodeReviewApprovalAddRepositoryApi,
    CodeReviewApprovalAvailableRepositoriesApi,
    CodeReviewApprovalInstallInfoApi,
    CodeReviewApprovalOwnersFileApi,
    CodeReviewApprovalPullRequestApi,
    CodeReviewApprovalRepositoryApi,
    CodeReviewApprovalRepositoryWriteApi,
    CodeReviewApprovalRoutingRunDetailApi,
    CodeReviewApprovalSyncInstallationRequestApi,
    CodeReviewApprovalSyncInstallationResponseApi,
    CodeReviewApprovalsPullRequestsListParams,
    CodeReviewApprovalsRepositoriesAvailableRepositoriesRetrieveParams,
    CodeReviewApprovalsRepositoriesListParams,
    CodeReviewApprovalsReviewerRoutingListParams,
    CodeReviewApprovalsRunsListParams,
    PaginatedCodeReviewApprovalPullRequestListApi,
    PaginatedCodeReviewApprovalRepositoryListApi,
    PaginatedCodeReviewApprovalRoutingRunListApi,
    PaginatedReviewRunListApi,
    PatchedCodeReviewApprovalRepositoryWriteApi,
    ReviewRequestApi,
    ReviewRequestResponseApi,
    ReviewRunApi,
} from './api.schemas'

export const getCodeReviewApprovalsPullRequestsListUrl = (
    projectId: string,
    params?: CodeReviewApprovalsPullRequestsListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/code_review/approvals/pull_requests/?${stringifiedParams}`
        : `/api/projects/${projectId}/code_review/approvals/pull_requests/`
}

/**
 * Read-only pull requests auto-approval knows about, filterable by PR number and merge state.
 */
export const codeReviewApprovalsPullRequestsList = async (
    projectId: string,
    params?: CodeReviewApprovalsPullRequestsListParams,
    options?: RequestInit
): Promise<PaginatedCodeReviewApprovalPullRequestListApi> => {
    return apiMutator<PaginatedCodeReviewApprovalPullRequestListApi>(
        getCodeReviewApprovalsPullRequestsListUrl(projectId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getCodeReviewApprovalsPullRequestsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/code_review/approvals/pull_requests/${id}/`
}

/**
 * Read-only pull requests auto-approval knows about, filterable by PR number and merge state.
 */
export const codeReviewApprovalsPullRequestsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<CodeReviewApprovalPullRequestApi> => {
    return apiMutator<CodeReviewApprovalPullRequestApi>(getCodeReviewApprovalsPullRequestsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getCodeReviewApprovalsRepositoriesListUrl = (
    projectId: string,
    params?: CodeReviewApprovalsRepositoriesListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/code_review/approvals/repositories/?${stringifiedParams}`
        : `/api/projects/${projectId}/code_review/approvals/repositories/`
}

/**
 * Per-repository auto-approval settings: enable or disable review, GitHub App installation, policy overrides.
 */
export const codeReviewApprovalsRepositoriesList = async (
    projectId: string,
    params?: CodeReviewApprovalsRepositoriesListParams,
    options?: RequestInit
): Promise<PaginatedCodeReviewApprovalRepositoryListApi> => {
    return apiMutator<PaginatedCodeReviewApprovalRepositoryListApi>(
        getCodeReviewApprovalsRepositoriesListUrl(projectId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getCodeReviewApprovalsRepositoriesCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/code_review/approvals/repositories/`
}

/**
 * Per-repository auto-approval settings: enable or disable review, GitHub App installation, policy overrides.
 */
export const codeReviewApprovalsRepositoriesCreate = async (
    projectId: string,
    codeReviewApprovalRepositoryWriteApi: CodeReviewApprovalRepositoryWriteApi,
    options?: RequestInit
): Promise<CodeReviewApprovalRepositoryApi> => {
    return apiMutator<CodeReviewApprovalRepositoryApi>(getCodeReviewApprovalsRepositoriesCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(codeReviewApprovalRepositoryWriteApi),
    })
}

export const getCodeReviewApprovalsRepositoriesRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/code_review/approvals/repositories/${id}/`
}

/**
 * Per-repository auto-approval settings: enable or disable review, GitHub App installation, policy overrides.
 */
export const codeReviewApprovalsRepositoriesRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<CodeReviewApprovalRepositoryApi> => {
    return apiMutator<CodeReviewApprovalRepositoryApi>(getCodeReviewApprovalsRepositoriesRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getCodeReviewApprovalsRepositoriesUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/code_review/approvals/repositories/${id}/`
}

/**
 * Per-repository auto-approval settings: enable or disable review, GitHub App installation, policy overrides.
 */
export const codeReviewApprovalsRepositoriesUpdate = async (
    projectId: string,
    id: string,
    codeReviewApprovalRepositoryWriteApi: CodeReviewApprovalRepositoryWriteApi,
    options?: RequestInit
): Promise<CodeReviewApprovalRepositoryApi> => {
    return apiMutator<CodeReviewApprovalRepositoryApi>(getCodeReviewApprovalsRepositoriesUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(codeReviewApprovalRepositoryWriteApi),
    })
}

export const getCodeReviewApprovalsRepositoriesPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/code_review/approvals/repositories/${id}/`
}

/**
 * Per-repository auto-approval settings: enable or disable review, GitHub App installation, policy overrides.
 */
export const codeReviewApprovalsRepositoriesPartialUpdate = async (
    projectId: string,
    id: string,
    patchedCodeReviewApprovalRepositoryWriteApi?: PatchedCodeReviewApprovalRepositoryWriteApi,
    options?: RequestInit
): Promise<CodeReviewApprovalRepositoryApi> => {
    return apiMutator<CodeReviewApprovalRepositoryApi>(
        getCodeReviewApprovalsRepositoriesPartialUpdateUrl(projectId, id),
        {
            ...options,
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(patchedCodeReviewApprovalRepositoryWriteApi),
        }
    )
}

export const getCodeReviewApprovalsRepositoriesDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/code_review/approvals/repositories/${id}/`
}

/**
 * Per-repository auto-approval settings: enable or disable review, GitHub App installation, policy overrides.
 */
export const codeReviewApprovalsRepositoriesDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getCodeReviewApprovalsRepositoriesDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getCodeReviewApprovalsRepositoriesOwnersFileRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/code_review/approvals/repositories/${id}/owners_file/`
}

/**
 * Check whether the repository's default branch has a root owners.yaml. Reviewer requests (routing_mode) read the code owners from it. Makes one GitHub call, so ask only when needed.
 */
export const codeReviewApprovalsRepositoriesOwnersFileRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<CodeReviewApprovalOwnersFileApi> => {
    return apiMutator<CodeReviewApprovalOwnersFileApi>(
        getCodeReviewApprovalsRepositoriesOwnersFileRetrieveUrl(projectId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getCodeReviewApprovalsRepositoriesAddRepositoryCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/code_review/approvals/repositories/add_repository/`
}

/**
 * Turn reviews on for a repository from the project's connected GitHub installations. Creates the repo config, or turns an existing one back on. Needs the editor level on code review auto-approval.
 */
export const codeReviewApprovalsRepositoriesAddRepositoryCreate = async (
    projectId: string,
    codeReviewApprovalAddRepositoryApi: CodeReviewApprovalAddRepositoryApi,
    options?: RequestInit
): Promise<CodeReviewApprovalRepositoryApi> => {
    return apiMutator<CodeReviewApprovalRepositoryApi>(
        getCodeReviewApprovalsRepositoriesAddRepositoryCreateUrl(projectId),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(codeReviewApprovalAddRepositoryApi),
        }
    )
}

export const getCodeReviewApprovalsRepositoriesAvailableRepositoriesRetrieveUrl = (
    projectId: string,
    params?: CodeReviewApprovalsRepositoriesAvailableRepositoriesRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/code_review/approvals/repositories/available_repositories/?${stringifiedParams}`
        : `/api/projects/${projectId}/code_review/approvals/repositories/available_repositories/`
}

/**
 * List repositories from the project's connected GitHub installations that are not added to auto-approval yet, so they can be added with add_repository.
 */
export const codeReviewApprovalsRepositoriesAvailableRepositoriesRetrieve = async (
    projectId: string,
    params?: CodeReviewApprovalsRepositoriesAvailableRepositoriesRetrieveParams,
    options?: RequestInit
): Promise<CodeReviewApprovalAvailableRepositoriesApi> => {
    return apiMutator<CodeReviewApprovalAvailableRepositoriesApi>(
        getCodeReviewApprovalsRepositoriesAvailableRepositoriesRetrieveUrl(projectId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getCodeReviewApprovalsRepositoriesInstallInfoRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/code_review/approvals/repositories/install_info/`
}

/**
 * Per-repository auto-approval settings: enable or disable review, GitHub App installation, policy overrides.
 */
export const codeReviewApprovalsRepositoriesInstallInfoRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<CodeReviewApprovalInstallInfoApi> => {
    return apiMutator<CodeReviewApprovalInstallInfoApi>(
        getCodeReviewApprovalsRepositoriesInstallInfoRetrieveUrl(projectId),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getCodeReviewApprovalsRepositoriesSyncInstallationCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/code_review/approvals/repositories/sync_installation/`
}

/**
 * Per-repository auto-approval settings: enable or disable review, GitHub App installation, policy overrides.
 */
export const codeReviewApprovalsRepositoriesSyncInstallationCreate = async (
    projectId: string,
    codeReviewApprovalSyncInstallationRequestApi: CodeReviewApprovalSyncInstallationRequestApi,
    options?: RequestInit
): Promise<CodeReviewApprovalSyncInstallationResponseApi> => {
    return apiMutator<CodeReviewApprovalSyncInstallationResponseApi>(
        getCodeReviewApprovalsRepositoriesSyncInstallationCreateUrl(projectId),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(codeReviewApprovalSyncInstallationRequestApi),
        }
    )
}

export const getCodeReviewApprovalsReviewerRoutingListUrl = (
    projectId: string,
    params?: CodeReviewApprovalsReviewerRoutingListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/code_review/approvals/reviewer_routing/?${stringifiedParams}`
        : `/api/projects/${projectId}/code_review/approvals/reviewer_routing/`
}

/**
 * List reviewer routing runs, newest first. Each run holds its decision for every owner of the changed code: requested, cut, or not asked, with the reason. Filter by owner to answer why a team or person was or was not asked to review. Get one run for the files each owner owns.
 */
export const codeReviewApprovalsReviewerRoutingList = async (
    projectId: string,
    params?: CodeReviewApprovalsReviewerRoutingListParams,
    options?: RequestInit
): Promise<PaginatedCodeReviewApprovalRoutingRunListApi> => {
    return apiMutator<PaginatedCodeReviewApprovalRoutingRunListApi>(
        getCodeReviewApprovalsReviewerRoutingListUrl(projectId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getCodeReviewApprovalsReviewerRoutingRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/code_review/approvals/reviewer_routing/${id}/`
}

/**
 * One reviewer routing run, with every changed file each owner owns.
 */
export const codeReviewApprovalsReviewerRoutingRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<CodeReviewApprovalRoutingRunDetailApi> => {
    return apiMutator<CodeReviewApprovalRoutingRunDetailApi>(
        getCodeReviewApprovalsReviewerRoutingRetrieveUrl(projectId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getCodeReviewApprovalsRunsListUrl = (projectId: string, params?: CodeReviewApprovalsRunsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/code_review/approvals/runs/?${stringifiedParams}`
        : `/api/projects/${projectId}/code_review/approvals/runs/`
}

/**
 * History of auto-approval review runs, filterable by repository, PR number, and status, plus manual review requests.
 */
export const codeReviewApprovalsRunsList = async (
    projectId: string,
    params?: CodeReviewApprovalsRunsListParams,
    options?: RequestInit
): Promise<PaginatedReviewRunListApi> => {
    return apiMutator<PaginatedReviewRunListApi>(getCodeReviewApprovalsRunsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getCodeReviewApprovalsRunsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/code_review/approvals/runs/`
}

/**
 * History of auto-approval review runs, filterable by repository, PR number, and status, plus manual review requests.
 */
export const codeReviewApprovalsRunsCreate = async (
    projectId: string,
    reviewRequestApi: ReviewRequestApi,
    options?: RequestInit
): Promise<ReviewRequestResponseApi> => {
    return apiMutator<ReviewRequestResponseApi>(getCodeReviewApprovalsRunsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(reviewRequestApi),
    })
}

export const getCodeReviewApprovalsRunsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/code_review/approvals/runs/${id}/`
}

/**
 * History of auto-approval review runs, filterable by repository, PR number, and status, plus manual review requests.
 */
export const codeReviewApprovalsRunsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<ReviewRunApi> => {
    return apiMutator<ReviewRunApi>(getCodeReviewApprovalsRunsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}
