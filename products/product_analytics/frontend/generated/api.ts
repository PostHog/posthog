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
    ColumnConfigurationApi,
    ColumnConfigurationsListParams,
    ElementApi,
    ElementsList2Params,
    ElementsListParams,
    PaginatedColumnConfigurationListApi,
    PaginatedElementListApi,
    PatchedColumnConfigurationApi,
    PatchedElementApi,
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

export const getColumnConfigurationsListUrl = (projectId: string, params?: ColumnConfigurationsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/column_configurations/?${stringifiedParams}`
        : `/api/environments/${projectId}/column_configurations/`
}

export const columnConfigurationsList = async (
    projectId: string,
    params?: ColumnConfigurationsListParams,
    options?: RequestInit
): Promise<PaginatedColumnConfigurationListApi> => {
    return apiMutator<PaginatedColumnConfigurationListApi>(getColumnConfigurationsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getColumnConfigurationsCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/column_configurations/`
}

export const columnConfigurationsCreate = async (
    projectId: string,
    columnConfigurationApi: NonReadonly<ColumnConfigurationApi>,
    options?: RequestInit
): Promise<ColumnConfigurationApi> => {
    return apiMutator<ColumnConfigurationApi>(getColumnConfigurationsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(columnConfigurationApi),
    })
}

export const getColumnConfigurationsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/column_configurations/${id}/`
}

export const columnConfigurationsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<ColumnConfigurationApi> => {
    return apiMutator<ColumnConfigurationApi>(getColumnConfigurationsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getColumnConfigurationsUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/column_configurations/${id}/`
}

export const columnConfigurationsUpdate = async (
    projectId: string,
    id: string,
    columnConfigurationApi: NonReadonly<ColumnConfigurationApi>,
    options?: RequestInit
): Promise<ColumnConfigurationApi> => {
    return apiMutator<ColumnConfigurationApi>(getColumnConfigurationsUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(columnConfigurationApi),
    })
}

export const getColumnConfigurationsPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/column_configurations/${id}/`
}

export const columnConfigurationsPartialUpdate = async (
    projectId: string,
    id: string,
    patchedColumnConfigurationApi: NonReadonly<PatchedColumnConfigurationApi>,
    options?: RequestInit
): Promise<ColumnConfigurationApi> => {
    return apiMutator<ColumnConfigurationApi>(getColumnConfigurationsPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedColumnConfigurationApi),
    })
}

export const getColumnConfigurationsDestroyUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/column_configurations/${id}/`
}

export const columnConfigurationsDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getColumnConfigurationsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getElementsListUrl = (projectId: string, params?: ElementsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/elements/?${stringifiedParams}`
        : `/api/environments/${projectId}/elements/`
}

export const elementsList = async (
    projectId: string,
    params?: ElementsListParams,
    options?: RequestInit
): Promise<PaginatedElementListApi> => {
    return apiMutator<PaginatedElementListApi>(getElementsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getElementsCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/elements/`
}

export const elementsCreate = async (
    projectId: string,
    elementApi: ElementApi,
    options?: RequestInit
): Promise<ElementApi> => {
    return apiMutator<ElementApi>(getElementsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(elementApi),
    })
}

export const getElementsRetrieveUrl = (projectId: string, id: number) => {
    return `/api/environments/${projectId}/elements/${id}/`
}

export const elementsRetrieve = async (projectId: string, id: number, options?: RequestInit): Promise<ElementApi> => {
    return apiMutator<ElementApi>(getElementsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getElementsUpdateUrl = (projectId: string, id: number) => {
    return `/api/environments/${projectId}/elements/${id}/`
}

export const elementsUpdate = async (
    projectId: string,
    id: number,
    elementApi: ElementApi,
    options?: RequestInit
): Promise<ElementApi> => {
    return apiMutator<ElementApi>(getElementsUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(elementApi),
    })
}

export const getElementsPartialUpdateUrl = (projectId: string, id: number) => {
    return `/api/environments/${projectId}/elements/${id}/`
}

export const elementsPartialUpdate = async (
    projectId: string,
    id: number,
    patchedElementApi: PatchedElementApi,
    options?: RequestInit
): Promise<ElementApi> => {
    return apiMutator<ElementApi>(getElementsPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedElementApi),
    })
}

export const getElementsDestroyUrl = (projectId: string, id: number) => {
    return `/api/environments/${projectId}/elements/${id}/`
}

export const elementsDestroy = async (projectId: string, id: number, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getElementsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

/**
 * The original version of this API always and only returned $autocapture elements
If no include query parameter is sent this remains true.
Now, you can pass a combination of include query parameters to get different types of elements
Currently only $autocapture and $rageclick and $dead_click are supported
 */
export const getElementsStatsRetrieveUrl = (projectId: string) => {
    return `/api/environments/${projectId}/elements/stats/`
}

export const elementsStatsRetrieve = async (projectId: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getElementsStatsRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getElementsValuesRetrieveUrl = (projectId: string) => {
    return `/api/environments/${projectId}/elements/values/`
}

export const elementsValuesRetrieve = async (projectId: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getElementsValuesRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getElementsList2Url = (projectId: string, params?: ElementsList2Params) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/elements/?${stringifiedParams}`
        : `/api/projects/${projectId}/elements/`
}

export const elementsList2 = async (
    projectId: string,
    params?: ElementsList2Params,
    options?: RequestInit
): Promise<PaginatedElementListApi> => {
    return apiMutator<PaginatedElementListApi>(getElementsList2Url(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getElementsCreate2Url = (projectId: string) => {
    return `/api/projects/${projectId}/elements/`
}

export const elementsCreate2 = async (
    projectId: string,
    elementApi: ElementApi,
    options?: RequestInit
): Promise<ElementApi> => {
    return apiMutator<ElementApi>(getElementsCreate2Url(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(elementApi),
    })
}

export const getElementsRetrieve2Url = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/elements/${id}/`
}

export const elementsRetrieve2 = async (projectId: string, id: number, options?: RequestInit): Promise<ElementApi> => {
    return apiMutator<ElementApi>(getElementsRetrieve2Url(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getElementsUpdate2Url = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/elements/${id}/`
}

export const elementsUpdate2 = async (
    projectId: string,
    id: number,
    elementApi: ElementApi,
    options?: RequestInit
): Promise<ElementApi> => {
    return apiMutator<ElementApi>(getElementsUpdate2Url(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(elementApi),
    })
}

export const getElementsPartialUpdate2Url = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/elements/${id}/`
}

export const elementsPartialUpdate2 = async (
    projectId: string,
    id: number,
    patchedElementApi: PatchedElementApi,
    options?: RequestInit
): Promise<ElementApi> => {
    return apiMutator<ElementApi>(getElementsPartialUpdate2Url(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedElementApi),
    })
}

export const getElementsDestroy2Url = (projectId: string, id: number) => {
    return `/api/projects/${projectId}/elements/${id}/`
}

export const elementsDestroy2 = async (projectId: string, id: number, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getElementsDestroy2Url(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

/**
 * The original version of this API always and only returned $autocapture elements
If no include query parameter is sent this remains true.
Now, you can pass a combination of include query parameters to get different types of elements
Currently only $autocapture and $rageclick and $dead_click are supported
 */
export const getElementsStatsRetrieve2Url = (projectId: string) => {
    return `/api/projects/${projectId}/elements/stats/`
}

export const elementsStatsRetrieve2 = async (projectId: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getElementsStatsRetrieve2Url(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getElementsValuesRetrieve2Url = (projectId: string) => {
    return `/api/projects/${projectId}/elements/values/`
}

export const elementsValuesRetrieve2 = async (projectId: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getElementsValuesRetrieve2Url(projectId), {
        ...options,
        method: 'GET',
    })
}
