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
    ObserveRequestApi,
    ObserveResponseApi,
    PaginatedReplayLensListApi,
    PaginatedReplayObservationListApi,
    PatchedReplayLensApi,
    ReplayLensApi,
    ReplayObservationApi,
    VisionLensesListParams,
    VisionLensesObservationsListParams,
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

export const getVisionLensesListUrl = (projectId: string, params?: VisionLensesListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/vision/lenses/?${stringifiedParams}`
        : `/api/environments/${projectId}/vision/lenses/`
}

/**
 * CRUD for Replay Vision lenses.
 */
export const visionLensesList = async (
    projectId: string,
    params?: VisionLensesListParams,
    options?: RequestInit
): Promise<PaginatedReplayLensListApi> => {
    return apiMutator<PaginatedReplayLensListApi>(getVisionLensesListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getVisionLensesCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/vision/lenses/`
}

/**
 * CRUD for Replay Vision lenses.
 */
export const visionLensesCreate = async (
    projectId: string,
    replayLensApi: NonReadonly<ReplayLensApi>,
    options?: RequestInit
): Promise<ReplayLensApi> => {
    return apiMutator<ReplayLensApi>(getVisionLensesCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(replayLensApi),
    })
}

export const getVisionLensesObservationsListUrl = (
    projectId: string,
    lensId: string,
    params?: VisionLensesObservationsListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/vision/lenses/${lensId}/observations/?${stringifiedParams}`
        : `/api/environments/${projectId}/vision/lenses/${lensId}/observations/`
}

/**
 * Read-only access to observations produced by a lens.
 */
export const visionLensesObservationsList = async (
    projectId: string,
    lensId: string,
    params?: VisionLensesObservationsListParams,
    options?: RequestInit
): Promise<PaginatedReplayObservationListApi> => {
    return apiMutator<PaginatedReplayObservationListApi>(
        getVisionLensesObservationsListUrl(projectId, lensId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getVisionLensesObservationsRetrieveUrl = (projectId: string, lensId: string, id: string) => {
    return `/api/environments/${projectId}/vision/lenses/${lensId}/observations/${id}/`
}

/**
 * Read-only access to observations produced by a lens.
 */
export const visionLensesObservationsRetrieve = async (
    projectId: string,
    lensId: string,
    id: string,
    options?: RequestInit
): Promise<ReplayObservationApi> => {
    return apiMutator<ReplayObservationApi>(getVisionLensesObservationsRetrieveUrl(projectId, lensId, id), {
        ...options,
        method: 'GET',
    })
}

export const getVisionLensesRetrieveUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/vision/lenses/${id}/`
}

/**
 * CRUD for Replay Vision lenses.
 */
export const visionLensesRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<ReplayLensApi> => {
    return apiMutator<ReplayLensApi>(getVisionLensesRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getVisionLensesPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/vision/lenses/${id}/`
}

/**
 * CRUD for Replay Vision lenses.
 */
export const visionLensesPartialUpdate = async (
    projectId: string,
    id: string,
    patchedReplayLensApi?: NonReadonly<PatchedReplayLensApi>,
    options?: RequestInit
): Promise<ReplayLensApi> => {
    return apiMutator<ReplayLensApi>(getVisionLensesPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedReplayLensApi),
    })
}

export const getVisionLensesDestroyUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/vision/lenses/${id}/`
}

/**
 * CRUD for Replay Vision lenses.
 */
export const visionLensesDestroy = async (projectId: string, id: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getVisionLensesDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getVisionLensesObserveCreateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/vision/lenses/${id}/observe/`
}

/**
 * Apply this lens to one specific session, on demand. Returns 202 with the workflow handle.
 */
export const visionLensesObserveCreate = async (
    projectId: string,
    id: string,
    observeRequestApi: ObserveRequestApi,
    options?: RequestInit
): Promise<ObserveResponseApi> => {
    return apiMutator<ObserveResponseApi>(getVisionLensesObserveCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(observeRequestApi),
    })
}
