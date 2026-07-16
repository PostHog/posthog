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
    DigestChannelApi,
    DigestRunApi,
    PaginatedDigestChannelListApi,
    PaginatedDigestRunListApi,
    PaginatedReviewRunListApi,
    PaginatedStamphogPullRequestListApi,
    PaginatedStamphogRepoConfigListApi,
    PatchedDigestChannelApi,
    PatchedStamphogRepoConfigApi,
    ReviewRunApi,
    StamphogDigestChannelsListParams,
    StamphogDigestRunsListParams,
    StamphogInstallInfoApi,
    StamphogPullRequestApi,
    StamphogPullRequestsListParams,
    StamphogRepoConfigApi,
    StamphogRepoConfigsListParams,
    StamphogReviewRunsListParams,
    StamphogSyncInstallationRequestApi,
    StamphogSyncInstallationResponseApi,
} from './api.schemas'

// https://stackoverflow.com/questions/49579094/typescript-conditional-types-filter-out-readonly-properties-pick-only-requir/49579497#49579497
type IfEquals<X, Y, A = X, B = never> = (<T>() => T extends X ? 1 : 2) extends <T>() => T extends Y ? 1 : 2 ? A : B

type WritableKeys<T> = {
    [P in keyof T]-?: IfEquals<{ [Q in P]: T[P] }, { -readonly [Q in P]: T[P] }, P>
}[keyof T]

type UnionToIntersection<U> = (U extends any ? (k: U) => void : never) extends (k: infer I) => void ? I : never
type DistributeReadOnlyOverUnions<T> = T extends any ? NonReadonly<T> : never

type Writable<T> = Pick<T, WritableKeys<T>>
type NonReadonly<T> = [T] extends [UnionToIntersection<T>]
    ? {
          [P in keyof Writable<T>]: T[P] extends object ? NonReadonly<NonNullable<T[P]>> : T[P]
      }
    : DistributeReadOnlyOverUnions<T>

export const getStamphogDigestChannelsListUrl = (projectId: string, params?: StamphogDigestChannelsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/stamphog/digest_channels/?${stringifiedParams}`
        : `/api/projects/${projectId}/stamphog/digest_channels/`
}

/**
 * Per-audience Slack destinations for the daily merged-PR digest.
 */
export const stamphogDigestChannelsList = async (
    projectId: string,
    params?: StamphogDigestChannelsListParams,
    options?: RequestInit
): Promise<PaginatedDigestChannelListApi> => {
    return apiMutator<PaginatedDigestChannelListApi>(getStamphogDigestChannelsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getStamphogDigestChannelsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/stamphog/digest_channels/`
}

/**
 * Per-audience Slack destinations for the daily merged-PR digest.
 */
export const stamphogDigestChannelsCreate = async (
    projectId: string,
    digestChannelApi: NonReadonly<DigestChannelApi>,
    options?: RequestInit
): Promise<DigestChannelApi> => {
    return apiMutator<DigestChannelApi>(getStamphogDigestChannelsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(digestChannelApi),
    })
}

export const getStamphogDigestChannelsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/stamphog/digest_channels/${id}/`
}

/**
 * Per-audience Slack destinations for the daily merged-PR digest.
 */
export const stamphogDigestChannelsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<DigestChannelApi> => {
    return apiMutator<DigestChannelApi>(getStamphogDigestChannelsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getStamphogDigestChannelsUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/stamphog/digest_channels/${id}/`
}

/**
 * Per-audience Slack destinations for the daily merged-PR digest.
 */
export const stamphogDigestChannelsUpdate = async (
    projectId: string,
    id: string,
    digestChannelApi: NonReadonly<DigestChannelApi>,
    options?: RequestInit
): Promise<DigestChannelApi> => {
    return apiMutator<DigestChannelApi>(getStamphogDigestChannelsUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(digestChannelApi),
    })
}

export const getStamphogDigestChannelsPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/stamphog/digest_channels/${id}/`
}

/**
 * Per-audience Slack destinations for the daily merged-PR digest.
 */
export const stamphogDigestChannelsPartialUpdate = async (
    projectId: string,
    id: string,
    patchedDigestChannelApi?: NonReadonly<PatchedDigestChannelApi>,
    options?: RequestInit
): Promise<DigestChannelApi> => {
    return apiMutator<DigestChannelApi>(getStamphogDigestChannelsPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedDigestChannelApi),
    })
}

export const getStamphogDigestChannelsDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/stamphog/digest_channels/${id}/`
}

/**
 * Per-audience Slack destinations for the daily merged-PR digest.
 */
export const stamphogDigestChannelsDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getStamphogDigestChannelsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

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
 * Read-only history of posted (or attempted) digests, filterable by digest channel.
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
 * Read-only history of posted (or attempted) digests, filterable by digest channel.
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
    stamphogRepoConfigApi: NonReadonly<StamphogRepoConfigApi>,
    options?: RequestInit
): Promise<StamphogRepoConfigApi> => {
    return apiMutator<StamphogRepoConfigApi>(getStamphogRepoConfigsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(stamphogRepoConfigApi),
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
    stamphogRepoConfigApi: NonReadonly<StamphogRepoConfigApi>,
    options?: RequestInit
): Promise<StamphogRepoConfigApi> => {
    return apiMutator<StamphogRepoConfigApi>(getStamphogRepoConfigsUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(stamphogRepoConfigApi),
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
    patchedStamphogRepoConfigApi?: NonReadonly<PatchedStamphogRepoConfigApi>,
    options?: RequestInit
): Promise<StamphogRepoConfigApi> => {
    return apiMutator<StamphogRepoConfigApi>(getStamphogRepoConfigsPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedStamphogRepoConfigApi),
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
 * Read-only history of stamphog review runs, filterable by repository, PR number, and status.
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

export const getStamphogReviewRunsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/stamphog/review_runs/${id}/`
}

/**
 * Read-only history of stamphog review runs, filterable by repository, PR number, and status.
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
