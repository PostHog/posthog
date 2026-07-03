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
    EstimateRequestApi,
    EstimateResponseApi,
    ObservationStatsApi,
    ObserveRequestApi,
    ObserveResponseApi,
    PaginatedReplayObservationListApi,
    PaginatedReplayScannerListApi,
    PaginatedVisionActionListApi,
    PaginatedVisionActionRunListListApi,
    PatchedReplayScannerApi,
    PatchedVisionActionApi,
    ReplayObservationApi,
    ReplayScannerApi,
    RetryFailedResponseApi,
    RetryResponseApi,
    ScannerCreatorsResponseApi,
    ScannerStatsResponseApi,
    SuggestTagsRequestApi,
    SuggestTagsResponseApi,
    VisionActionApi,
    VisionActionRunApi,
    VisionActionsListParams,
    VisionActionsRunsListParams,
    VisionObservationsListParams,
    VisionQuotaApi,
    VisionScannersListParams,
    VisionScannersObservationsListParams,
    VisionScannersObservationsStatsRetrieveParams,
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

export const getVisionActionsListUrl = (projectId: string, params?: VisionActionsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/vision/actions/?${stringifiedParams}`
        : `/api/projects/${projectId}/vision/actions/`
}

/**
 * CRUD for Replay Vision actions — scheduled "and then…" automations over a scanner's observations.
 */
export const visionActionsList = async (
    projectId: string,
    params?: VisionActionsListParams,
    options?: RequestInit
): Promise<PaginatedVisionActionListApi> => {
    return apiMutator<PaginatedVisionActionListApi>(getVisionActionsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getVisionActionsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/vision/actions/`
}

/**
 * CRUD for Replay Vision actions — scheduled "and then…" automations over a scanner's observations.
 */
export const visionActionsCreate = async (
    projectId: string,
    visionActionApi: NonReadonly<VisionActionApi>,
    options?: RequestInit
): Promise<VisionActionApi> => {
    return apiMutator<VisionActionApi>(getVisionActionsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(visionActionApi),
    })
}

export const getVisionActionsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/vision/actions/${id}/`
}

/**
 * CRUD for Replay Vision actions — scheduled "and then…" automations over a scanner's observations.
 */
export const visionActionsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<VisionActionApi> => {
    return apiMutator<VisionActionApi>(getVisionActionsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getVisionActionsPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/vision/actions/${id}/`
}

/**
 * CRUD for Replay Vision actions — scheduled "and then…" automations over a scanner's observations.
 */
export const visionActionsPartialUpdate = async (
    projectId: string,
    id: string,
    patchedVisionActionApi?: NonReadonly<PatchedVisionActionApi>,
    options?: RequestInit
): Promise<VisionActionApi> => {
    return apiMutator<VisionActionApi>(getVisionActionsPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedVisionActionApi),
    })
}

export const getVisionActionsDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/vision/actions/${id}/`
}

/**
 * CRUD for Replay Vision actions — scheduled "and then…" automations over a scanner's observations.
 */
export const visionActionsDestroy = async (projectId: string, id: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getVisionActionsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getVisionActionsRunsListUrl = (
    projectId: string,
    visionActionId: string,
    params?: VisionActionsRunsListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/vision/actions/${visionActionId}/runs/?${stringifiedParams}`
        : `/api/projects/${projectId}/vision/actions/${visionActionId}/runs/`
}

/**
 * Read-only run history for a single vision action (nested under /vision/actions/{action_id}/runs/).
 */
export const visionActionsRunsList = async (
    projectId: string,
    visionActionId: string,
    params?: VisionActionsRunsListParams,
    options?: RequestInit
): Promise<PaginatedVisionActionRunListListApi> => {
    return apiMutator<PaginatedVisionActionRunListListApi>(
        getVisionActionsRunsListUrl(projectId, visionActionId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getVisionActionsRunsRetrieveUrl = (projectId: string, visionActionId: string, id: string) => {
    return `/api/projects/${projectId}/vision/actions/${visionActionId}/runs/${id}/`
}

/**
 * Read-only run history for a single vision action (nested under /vision/actions/{action_id}/runs/).
 */
export const visionActionsRunsRetrieve = async (
    projectId: string,
    visionActionId: string,
    id: string,
    options?: RequestInit
): Promise<VisionActionRunApi> => {
    return apiMutator<VisionActionRunApi>(getVisionActionsRunsRetrieveUrl(projectId, visionActionId, id), {
        ...options,
        method: 'GET',
    })
}

export const getVisionObservationsListUrl = (projectId: string, params: VisionObservationsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/vision/observations/?${stringifiedParams}`
        : `/api/projects/${projectId}/vision/observations/`
}

/**
 * Read-only access to a session's observations across every scanner the caller can read, for the replay-page dock.
 */
export const visionObservationsList = async (
    projectId: string,
    params: VisionObservationsListParams,
    options?: RequestInit
): Promise<PaginatedReplayObservationListApi> => {
    return apiMutator<PaginatedReplayObservationListApi>(getVisionObservationsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getVisionObservationsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/vision/observations/${id}/`
}

/**
 * Read-only access to a session's observations across every scanner the caller can read, for the replay-page dock.
 */
export const visionObservationsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<ReplayObservationApi> => {
    return apiMutator<ReplayObservationApi>(getVisionObservationsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getVisionObservationsRetryCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/vision/observations/${id}/retry/`
}

/**
 * Delete a failed observation and re-run its scanner on the same recording. Returns 202 with the workflow handle.
 */
export const visionObservationsRetryCreate = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<RetryResponseApi> => {
    return apiMutator<RetryResponseApi>(getVisionObservationsRetryCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
    })
}

export const getVisionObservationsRetryFailedCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/vision/observations/retry_failed/`
}

/**
 * Retry the scanner's failed observations, oldest first, capped per call by the batch limit.
 */
export const visionObservationsRetryFailedCreate = async (
    projectId: string,
    options?: RequestInit
): Promise<RetryFailedResponseApi> => {
    return apiMutator<RetryFailedResponseApi>(getVisionObservationsRetryFailedCreateUrl(projectId), {
        ...options,
        method: 'POST',
    })
}

export const getEnvironmentVisionQuotaRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/vision/quota/`
}

export const environmentVisionQuotaRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<VisionQuotaApi> => {
    return apiMutator<VisionQuotaApi>(getEnvironmentVisionQuotaRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getVisionScannersListUrl = (projectId: string, params?: VisionScannersListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/vision/scanners/?${stringifiedParams}`
        : `/api/projects/${projectId}/vision/scanners/`
}

/**
 * CRUD for Replay Vision scanners.
 */
export const visionScannersList = async (
    projectId: string,
    params?: VisionScannersListParams,
    options?: RequestInit
): Promise<PaginatedReplayScannerListApi> => {
    return apiMutator<PaginatedReplayScannerListApi>(getVisionScannersListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getVisionScannersCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/vision/scanners/`
}

/**
 * CRUD for Replay Vision scanners.
 */
export const visionScannersCreate = async (
    projectId: string,
    replayScannerApi: NonReadonly<ReplayScannerApi>,
    options?: RequestInit
): Promise<ReplayScannerApi> => {
    return apiMutator<ReplayScannerApi>(getVisionScannersCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(replayScannerApi),
    })
}

export const getVisionScannersRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/vision/scanners/${id}/`
}

/**
 * CRUD for Replay Vision scanners.
 */
export const visionScannersRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<ReplayScannerApi> => {
    return apiMutator<ReplayScannerApi>(getVisionScannersRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getVisionScannersPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/vision/scanners/${id}/`
}

/**
 * CRUD for Replay Vision scanners.
 */
export const visionScannersPartialUpdate = async (
    projectId: string,
    id: string,
    patchedReplayScannerApi?: NonReadonly<PatchedReplayScannerApi>,
    options?: RequestInit
): Promise<ReplayScannerApi> => {
    return apiMutator<ReplayScannerApi>(getVisionScannersPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedReplayScannerApi),
    })
}

export const getVisionScannersDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/vision/scanners/${id}/`
}

/**
 * CRUD for Replay Vision scanners.
 */
export const visionScannersDestroy = async (projectId: string, id: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getVisionScannersDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getVisionScannersObserveCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/vision/scanners/${id}/observe/`
}

/**
 * Apply this scanner to one specific session, on demand. Returns 202 with the workflow handle.
 */
export const visionScannersObserveCreate = async (
    projectId: string,
    id: string,
    observeRequestApi: ObserveRequestApi,
    options?: RequestInit
): Promise<ObserveResponseApi> => {
    return apiMutator<ObserveResponseApi>(getVisionScannersObserveCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(observeRequestApi),
    })
}

export const getVisionScannersObservationsListUrl = (
    projectId: string,
    scannerId: string,
    params?: VisionScannersObservationsListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/vision/scanners/${scannerId}/observations/?${stringifiedParams}`
        : `/api/projects/${projectId}/vision/scanners/${scannerId}/observations/`
}

/**
 * Read-only access to observations produced by a scanner.
 */
export const visionScannersObservationsList = async (
    projectId: string,
    scannerId: string,
    params?: VisionScannersObservationsListParams,
    options?: RequestInit
): Promise<PaginatedReplayObservationListApi> => {
    return apiMutator<PaginatedReplayObservationListApi>(
        getVisionScannersObservationsListUrl(projectId, scannerId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getVisionScannersObservationsRetrieveUrl = (projectId: string, scannerId: string, id: string) => {
    return `/api/projects/${projectId}/vision/scanners/${scannerId}/observations/${id}/`
}

/**
 * Read-only access to observations produced by a scanner.
 */
export const visionScannersObservationsRetrieve = async (
    projectId: string,
    scannerId: string,
    id: string,
    options?: RequestInit
): Promise<ReplayObservationApi> => {
    return apiMutator<ReplayObservationApi>(getVisionScannersObservationsRetrieveUrl(projectId, scannerId, id), {
        ...options,
        method: 'GET',
    })
}

export const getVisionScannersObservationsRetryCreateUrl = (projectId: string, scannerId: string, id: string) => {
    return `/api/projects/${projectId}/vision/scanners/${scannerId}/observations/${id}/retry/`
}

/**
 * Delete a failed observation and re-run its scanner on the same recording. Returns 202 with the workflow handle.
 */
export const visionScannersObservationsRetryCreate = async (
    projectId: string,
    scannerId: string,
    id: string,
    options?: RequestInit
): Promise<RetryResponseApi> => {
    return apiMutator<RetryResponseApi>(getVisionScannersObservationsRetryCreateUrl(projectId, scannerId, id), {
        ...options,
        method: 'POST',
    })
}

export const getVisionScannersObservationsRetryFailedCreateUrl = (projectId: string, scannerId: string) => {
    return `/api/projects/${projectId}/vision/scanners/${scannerId}/observations/retry_failed/`
}

/**
 * Retry the scanner's failed observations, oldest first, capped per call by the batch limit.
 */
export const visionScannersObservationsRetryFailedCreate = async (
    projectId: string,
    scannerId: string,
    options?: RequestInit
): Promise<RetryFailedResponseApi> => {
    return apiMutator<RetryFailedResponseApi>(getVisionScannersObservationsRetryFailedCreateUrl(projectId, scannerId), {
        ...options,
        method: 'POST',
    })
}

export const getVisionScannersObservationsStatsRetrieveUrl = (
    projectId: string,
    scannerId: string,
    params?: VisionScannersObservationsStatsRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/vision/scanners/${scannerId}/observations/stats/?${stringifiedParams}`
        : `/api/projects/${projectId}/vision/scanners/${scannerId}/observations/stats/`
}

/**
 * Aggregate counts and per-scanner-type distributions over the filtered observation set. Same filters as the list endpoint apply.
 */
export const visionScannersObservationsStatsRetrieve = async (
    projectId: string,
    scannerId: string,
    params?: VisionScannersObservationsStatsRetrieveParams,
    options?: RequestInit
): Promise<ObservationStatsApi> => {
    return apiMutator<ObservationStatsApi>(
        getVisionScannersObservationsStatsRetrieveUrl(projectId, scannerId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getVisionScannersCreatorsRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/vision/scanners/creators/`
}

/**
 * Distinct creators across the team's scanners — feeds the `Created by` filter dropdown.
 */
export const visionScannersCreatorsRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<ScannerCreatorsResponseApi> => {
    return apiMutator<ScannerCreatorsResponseApi>(getVisionScannersCreatorsRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getVisionScannersEstimateCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/vision/scanners/estimate/`
}

/**
 * Estimate the observation volume a proposed scanner would generate, for the pre-save cost preview.
 */
export const visionScannersEstimateCreate = async (
    projectId: string,
    estimateRequestApi?: EstimateRequestApi,
    options?: RequestInit
): Promise<EstimateResponseApi> => {
    return apiMutator<EstimateResponseApi>(getVisionScannersEstimateCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(estimateRequestApi),
    })
}

export const getVisionScannersStatsRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/vision/scanners/stats/`
}

/**
 * Team-wide scanner counts — independent of list filters, so the overview stays stable.
 */
export const visionScannersStatsRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<ScannerStatsResponseApi> => {
    return apiMutator<ScannerStatsResponseApi>(getVisionScannersStatsRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getVisionScannersSuggestTagsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/vision/scanners/suggest_tags/`
}

/**
 * Suggest classifier tags grounded in the scanner's own observations and the org's product data.
 */
export const visionScannersSuggestTagsCreate = async (
    projectId: string,
    suggestTagsRequestApi: SuggestTagsRequestApi,
    options?: RequestInit
): Promise<SuggestTagsResponseApi> => {
    return apiMutator<SuggestTagsResponseApi>(getVisionScannersSuggestTagsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(suggestTagsRequestApi),
    })
}
