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
    ObserveRequestApi,
    ObserveResponseApi,
    PaginatedReplayObservationListApi,
    PaginatedReplayScannerListApi,
    PatchedReplayScannerApi,
    ReplayObservationApi,
    ReplayScannerApi,
    VisionObservationsListParams,
    VisionScannersListParams,
    VisionScannersObservationsListParams,
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

export const getVisionObservationsListUrl = (projectId: string, params: VisionObservationsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/vision/observations/?${stringifiedParams}`
        : `/api/environments/${projectId}/vision/observations/`
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
    return `/api/environments/${projectId}/vision/observations/${id}/`
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

export const getVisionScannersListUrl = (projectId: string, params?: VisionScannersListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/vision/scanners/?${stringifiedParams}`
        : `/api/environments/${projectId}/vision/scanners/`
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
    return `/api/environments/${projectId}/vision/scanners/`
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
    return `/api/environments/${projectId}/vision/scanners/${id}/`
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
    return `/api/environments/${projectId}/vision/scanners/${id}/`
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
    return `/api/environments/${projectId}/vision/scanners/${id}/`
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
    return `/api/environments/${projectId}/vision/scanners/${id}/observe/`
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
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/vision/scanners/${scannerId}/observations/?${stringifiedParams}`
        : `/api/environments/${projectId}/vision/scanners/${scannerId}/observations/`
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
    return `/api/environments/${projectId}/vision/scanners/${scannerId}/observations/${id}/`
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

export const getVisionScannersEstimateCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/vision/scanners/estimate/`
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
