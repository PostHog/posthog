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
    OutcomeDefinitionApi,
    OutcomeLatchApi,
    OutcomesListParams,
    PaginatedOutcomeDefinitionListApi,
    PatchedOutcomeDefinitionApi,
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

export const getOutcomesListUrl = (projectId: string, params?: OutcomesListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/outcomes/?${stringifiedParams}`
        : `/api/projects/${projectId}/outcomes/`
}

/**
 * Create, read, update, and delete outcome definitions, and inspect who reached them.
 */
export const outcomesList = async (
    projectId: string,
    params?: OutcomesListParams,
    options?: RequestInit
): Promise<PaginatedOutcomeDefinitionListApi> => {
    return apiMutator<PaginatedOutcomeDefinitionListApi>(getOutcomesListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getOutcomesCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/outcomes/`
}

/**
 * Create, read, update, and delete outcome definitions, and inspect who reached them.
 */
export const outcomesCreate = async (
    projectId: string,
    outcomeDefinitionApi: NonReadonly<OutcomeDefinitionApi>,
    options?: RequestInit
): Promise<OutcomeDefinitionApi> => {
    return apiMutator<OutcomeDefinitionApi>(getOutcomesCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(outcomeDefinitionApi),
    })
}

export const getOutcomesRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/outcomes/${id}/`
}

/**
 * Create, read, update, and delete outcome definitions, and inspect who reached them.
 */
export const outcomesRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<OutcomeDefinitionApi> => {
    return apiMutator<OutcomeDefinitionApi>(getOutcomesRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getOutcomesUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/outcomes/${id}/`
}

/**
 * Create, read, update, and delete outcome definitions, and inspect who reached them.
 */
export const outcomesUpdate = async (
    projectId: string,
    id: string,
    outcomeDefinitionApi: NonReadonly<OutcomeDefinitionApi>,
    options?: RequestInit
): Promise<OutcomeDefinitionApi> => {
    return apiMutator<OutcomeDefinitionApi>(getOutcomesUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(outcomeDefinitionApi),
    })
}

export const getOutcomesPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/outcomes/${id}/`
}

/**
 * Create, read, update, and delete outcome definitions, and inspect who reached them.
 */
export const outcomesPartialUpdate = async (
    projectId: string,
    id: string,
    patchedOutcomeDefinitionApi?: NonReadonly<PatchedOutcomeDefinitionApi>,
    options?: RequestInit
): Promise<OutcomeDefinitionApi> => {
    return apiMutator<OutcomeDefinitionApi>(getOutcomesPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedOutcomeDefinitionApi),
    })
}

export const getOutcomesDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/outcomes/${id}/`
}

/**
 * Create, read, update, and delete outcome definitions, and inspect who reached them.
 */
export const outcomesDestroy = async (projectId: string, id: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getOutcomesDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getOutcomesCalculateCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/outcomes/${id}/calculate/`
}

/**
 * Enqueue an immediate recalculation of this outcome instead of waiting for the periodic run.
 */
export const outcomesCalculateCreate = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<OutcomeDefinitionApi> => {
    return apiMutator<OutcomeDefinitionApi>(getOutcomesCalculateCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
    })
}

export const getOutcomesReachedListUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/outcomes/${id}/reached/`
}

/**
 * The most recent persons who reached this outcome (up to 100).
 */
export const outcomesReachedList = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<OutcomeLatchApi[]> => {
    return apiMutator<OutcomeLatchApi[]>(getOutcomesReachedListUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}
