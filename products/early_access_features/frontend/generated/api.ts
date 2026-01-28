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
    EarlyAccessFeatureApi,
    EarlyAccessFeatureListParams,
    EarlyAccessFeatureSerializerCreateOnlyApi,
    PaginatedEarlyAccessFeatureListApi,
    PatchedEarlyAccessFeatureApi,
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

export const getEarlyAccessFeatureListUrl = (projectId: string, params?: EarlyAccessFeatureListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/early_access_feature/?${stringifiedParams}`
        : `/api/projects/${projectId}/early_access_feature/`
}

export const earlyAccessFeatureList = async (
    projectId: string,
    params?: EarlyAccessFeatureListParams,
    options?: RequestInit
): Promise<PaginatedEarlyAccessFeatureListApi> => {
    return apiMutator<PaginatedEarlyAccessFeatureListApi>(getEarlyAccessFeatureListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getEarlyAccessFeatureCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/early_access_feature/`
}

export const earlyAccessFeatureCreate = async (
    projectId: string,
    earlyAccessFeatureSerializerCreateOnlyApi: NonReadonly<EarlyAccessFeatureSerializerCreateOnlyApi>,
    options?: RequestInit
): Promise<EarlyAccessFeatureSerializerCreateOnlyApi> => {
    return apiMutator<EarlyAccessFeatureSerializerCreateOnlyApi>(getEarlyAccessFeatureCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(earlyAccessFeatureSerializerCreateOnlyApi),
    })
}

export const getEarlyAccessFeatureRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/early_access_feature/${id}/`
}

export const earlyAccessFeatureRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<EarlyAccessFeatureApi> => {
    return apiMutator<EarlyAccessFeatureApi>(getEarlyAccessFeatureRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getEarlyAccessFeatureUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/early_access_feature/${id}/`
}

export const earlyAccessFeatureUpdate = async (
    projectId: string,
    id: string,
    earlyAccessFeatureApi: NonReadonly<EarlyAccessFeatureApi>,
    options?: RequestInit
): Promise<EarlyAccessFeatureApi> => {
    return apiMutator<EarlyAccessFeatureApi>(getEarlyAccessFeatureUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(earlyAccessFeatureApi),
    })
}

export const getEarlyAccessFeaturePartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/early_access_feature/${id}/`
}

export const earlyAccessFeaturePartialUpdate = async (
    projectId: string,
    id: string,
    patchedEarlyAccessFeatureApi: NonReadonly<PatchedEarlyAccessFeatureApi>,
    options?: RequestInit
): Promise<EarlyAccessFeatureApi> => {
    return apiMutator<EarlyAccessFeatureApi>(getEarlyAccessFeaturePartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedEarlyAccessFeatureApi),
    })
}

export const getEarlyAccessFeatureDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/early_access_feature/${id}/`
}

export const earlyAccessFeatureDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getEarlyAccessFeatureDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}
