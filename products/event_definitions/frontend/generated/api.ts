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
    EnterpriseEventDefinitionApi,
    EventDefinitionApi,
    EventDefinitionsByNameRetrieveParams,
    EventDefinitionsListParams,
    PaginatedEnterpriseEventDefinitionListApi,
    PatchedEnterpriseEventDefinitionApi,
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

export const getEventDefinitionsListUrl = (projectId: string, params?: EventDefinitionsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/event_definitions/?${stringifiedParams}`
        : `/api/projects/${projectId}/event_definitions/`
}

export const eventDefinitionsList = async (
    projectId: string,
    params?: EventDefinitionsListParams,
    options?: RequestInit
): Promise<PaginatedEnterpriseEventDefinitionListApi> => {
    return apiMutator<PaginatedEnterpriseEventDefinitionListApi>(getEventDefinitionsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getEventDefinitionsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/event_definitions/`
}

export const eventDefinitionsCreate = async (
    projectId: string,
    enterpriseEventDefinitionApi: NonReadonly<EnterpriseEventDefinitionApi>,
    options?: RequestInit
): Promise<EnterpriseEventDefinitionApi> => {
    return apiMutator<EnterpriseEventDefinitionApi>(getEventDefinitionsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(enterpriseEventDefinitionApi),
    })
}

export const getEventDefinitionsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/event_definitions/${id}/`
}

export const eventDefinitionsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<EnterpriseEventDefinitionApi> => {
    return apiMutator<EnterpriseEventDefinitionApi>(getEventDefinitionsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getEventDefinitionsUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/event_definitions/${id}/`
}

export const eventDefinitionsUpdate = async (
    projectId: string,
    id: string,
    enterpriseEventDefinitionApi: NonReadonly<EnterpriseEventDefinitionApi>,
    options?: RequestInit
): Promise<EnterpriseEventDefinitionApi> => {
    return apiMutator<EnterpriseEventDefinitionApi>(getEventDefinitionsUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(enterpriseEventDefinitionApi),
    })
}

export const getEventDefinitionsPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/event_definitions/${id}/`
}

export const eventDefinitionsPartialUpdate = async (
    projectId: string,
    id: string,
    patchedEnterpriseEventDefinitionApi: NonReadonly<PatchedEnterpriseEventDefinitionApi>,
    options?: RequestInit
): Promise<EnterpriseEventDefinitionApi> => {
    return apiMutator<EnterpriseEventDefinitionApi>(getEventDefinitionsPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedEnterpriseEventDefinitionApi),
    })
}

export const getEventDefinitionsDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/event_definitions/${id}/`
}

export const eventDefinitionsDestroy = async (projectId: string, id: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getEventDefinitionsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getEventDefinitionsMetricsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/event_definitions/${id}/metrics/`
}

export const eventDefinitionsMetricsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getEventDefinitionsMetricsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

/**
 * Get event definition by exact name
 */
export const getEventDefinitionsByNameRetrieveUrl = (
    projectId: string,
    params: EventDefinitionsByNameRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/event_definitions/by_name/?${stringifiedParams}`
        : `/api/projects/${projectId}/event_definitions/by_name/`
}

export const eventDefinitionsByNameRetrieve = async (
    projectId: string,
    params: EventDefinitionsByNameRetrieveParams,
    options?: RequestInit
): Promise<EventDefinitionApi> => {
    return apiMutator<EventDefinitionApi>(getEventDefinitionsByNameRetrieveUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getEventDefinitionsGolangRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/event_definitions/golang/`
}

export const eventDefinitionsGolangRetrieve = async (projectId: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getEventDefinitionsGolangRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getEventDefinitionsPythonRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/event_definitions/python/`
}

export const eventDefinitionsPythonRetrieve = async (projectId: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getEventDefinitionsPythonRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getEventDefinitionsTypescriptRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/event_definitions/typescript/`
}

export const eventDefinitionsTypescriptRetrieve = async (projectId: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getEventDefinitionsTypescriptRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}
