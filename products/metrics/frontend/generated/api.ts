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
    GroupUsageMetricApi,
    GroupsTypesMetricsListParams,
    PaginatedGroupUsageMetricListApi,
    PatchedGroupUsageMetricApi,
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

export const getGroupsTypesMetricsListUrl = (
    projectId: string,
    groupTypeIndex: number,
    params?: GroupsTypesMetricsListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/groups_types/${groupTypeIndex}/metrics/?${stringifiedParams}`
        : `/api/projects/${projectId}/groups_types/${groupTypeIndex}/metrics/`
}

export const groupsTypesMetricsList = async (
    projectId: string,
    groupTypeIndex: number,
    params?: GroupsTypesMetricsListParams,
    options?: RequestInit
): Promise<PaginatedGroupUsageMetricListApi> => {
    return apiMutator<PaginatedGroupUsageMetricListApi>(
        getGroupsTypesMetricsListUrl(projectId, groupTypeIndex, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export const getGroupsTypesMetricsCreateUrl = (projectId: string, groupTypeIndex: number) => {
    return `/api/projects/${projectId}/groups_types/${groupTypeIndex}/metrics/`
}

export const groupsTypesMetricsCreate = async (
    projectId: string,
    groupTypeIndex: number,
    groupUsageMetricApi: NonReadonly<GroupUsageMetricApi>,
    options?: RequestInit
): Promise<GroupUsageMetricApi> => {
    return apiMutator<GroupUsageMetricApi>(getGroupsTypesMetricsCreateUrl(projectId, groupTypeIndex), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(groupUsageMetricApi),
    })
}

export const getGroupsTypesMetricsRetrieveUrl = (projectId: string, groupTypeIndex: number, id: string) => {
    return `/api/projects/${projectId}/groups_types/${groupTypeIndex}/metrics/${id}/`
}

export const groupsTypesMetricsRetrieve = async (
    projectId: string,
    groupTypeIndex: number,
    id: string,
    options?: RequestInit
): Promise<GroupUsageMetricApi> => {
    return apiMutator<GroupUsageMetricApi>(getGroupsTypesMetricsRetrieveUrl(projectId, groupTypeIndex, id), {
        ...options,
        method: 'GET',
    })
}

export const getGroupsTypesMetricsUpdateUrl = (projectId: string, groupTypeIndex: number, id: string) => {
    return `/api/projects/${projectId}/groups_types/${groupTypeIndex}/metrics/${id}/`
}

export const groupsTypesMetricsUpdate = async (
    projectId: string,
    groupTypeIndex: number,
    id: string,
    groupUsageMetricApi: NonReadonly<GroupUsageMetricApi>,
    options?: RequestInit
): Promise<GroupUsageMetricApi> => {
    return apiMutator<GroupUsageMetricApi>(getGroupsTypesMetricsUpdateUrl(projectId, groupTypeIndex, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(groupUsageMetricApi),
    })
}

export const getGroupsTypesMetricsPartialUpdateUrl = (projectId: string, groupTypeIndex: number, id: string) => {
    return `/api/projects/${projectId}/groups_types/${groupTypeIndex}/metrics/${id}/`
}

export const groupsTypesMetricsPartialUpdate = async (
    projectId: string,
    groupTypeIndex: number,
    id: string,
    patchedGroupUsageMetricApi: NonReadonly<PatchedGroupUsageMetricApi>,
    options?: RequestInit
): Promise<GroupUsageMetricApi> => {
    return apiMutator<GroupUsageMetricApi>(getGroupsTypesMetricsPartialUpdateUrl(projectId, groupTypeIndex, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedGroupUsageMetricApi),
    })
}

export const getGroupsTypesMetricsDestroyUrl = (projectId: string, groupTypeIndex: number, id: string) => {
    return `/api/projects/${projectId}/groups_types/${groupTypeIndex}/metrics/${id}/`
}

export const groupsTypesMetricsDestroy = async (
    projectId: string,
    groupTypeIndex: number,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getGroupsTypesMetricsDestroyUrl(projectId, groupTypeIndex, id), {
        ...options,
        method: 'DELETE',
    })
}
