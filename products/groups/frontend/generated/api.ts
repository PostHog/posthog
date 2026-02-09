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
    CreateGroupApi,
    GroupApi,
    GroupsActivityRetrieve2Params,
    GroupsActivityRetrieveParams,
    GroupsDeletePropertyCreate2Params,
    GroupsDeletePropertyCreateParams,
    GroupsFindRetrieve2Params,
    GroupsFindRetrieveParams,
    GroupsList2Params,
    GroupsListParams,
    GroupsRelatedRetrieve2Params,
    GroupsRelatedRetrieveParams,
    GroupsUpdatePropertyCreate2Params,
    GroupsUpdatePropertyCreateParams,
    PaginatedGroupListApi,
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

/**
 * List all groups of a specific group type. You must pass ?group_type_index= in the URL. To get a list of valid group types, call /api/:project_id/groups_types/
 */
export const getGroupsListUrl = (projectId: string, params: GroupsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/groups/?${stringifiedParams}`
        : `/api/environments/${projectId}/groups/`
}

export const groupsList = async (
    projectId: string,
    params: GroupsListParams,
    options?: RequestInit
): Promise<PaginatedGroupListApi> => {
    return apiMutator<PaginatedGroupListApi>(getGroupsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getGroupsCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/groups/`
}

export const groupsCreate = async (
    projectId: string,
    createGroupApi: CreateGroupApi,
    options?: RequestInit
): Promise<GroupApi> => {
    return apiMutator<GroupApi>(getGroupsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(createGroupApi),
    })
}

export const getGroupsActivityRetrieveUrl = (projectId: string, params: GroupsActivityRetrieveParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/groups/activity/?${stringifiedParams}`
        : `/api/environments/${projectId}/groups/activity/`
}

export const groupsActivityRetrieve = async (
    projectId: string,
    params: GroupsActivityRetrieveParams,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getGroupsActivityRetrieveUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getGroupsDeletePropertyCreateUrl = (projectId: string, params: GroupsDeletePropertyCreateParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/groups/delete_property/?${stringifiedParams}`
        : `/api/environments/${projectId}/groups/delete_property/`
}

export const groupsDeletePropertyCreate = async (
    projectId: string,
    groupApi: NonReadonly<GroupApi>,
    params: GroupsDeletePropertyCreateParams,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getGroupsDeletePropertyCreateUrl(projectId, params), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(groupApi),
    })
}

export const getGroupsFindRetrieveUrl = (projectId: string, params: GroupsFindRetrieveParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/groups/find/?${stringifiedParams}`
        : `/api/environments/${projectId}/groups/find/`
}

export const groupsFindRetrieve = async (
    projectId: string,
    params: GroupsFindRetrieveParams,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getGroupsFindRetrieveUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getGroupsPropertyDefinitionsRetrieveUrl = (projectId: string) => {
    return `/api/environments/${projectId}/groups/property_definitions/`
}

export const groupsPropertyDefinitionsRetrieve = async (projectId: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getGroupsPropertyDefinitionsRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getGroupsPropertyValuesRetrieveUrl = (projectId: string) => {
    return `/api/environments/${projectId}/groups/property_values/`
}

export const groupsPropertyValuesRetrieve = async (projectId: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getGroupsPropertyValuesRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getGroupsRelatedRetrieveUrl = (projectId: string, params: GroupsRelatedRetrieveParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/groups/related/?${stringifiedParams}`
        : `/api/environments/${projectId}/groups/related/`
}

export const groupsRelatedRetrieve = async (
    projectId: string,
    params: GroupsRelatedRetrieveParams,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getGroupsRelatedRetrieveUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getGroupsUpdatePropertyCreateUrl = (projectId: string, params: GroupsUpdatePropertyCreateParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/groups/update_property/?${stringifiedParams}`
        : `/api/environments/${projectId}/groups/update_property/`
}

export const groupsUpdatePropertyCreate = async (
    projectId: string,
    groupApi: NonReadonly<GroupApi>,
    params: GroupsUpdatePropertyCreateParams,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getGroupsUpdatePropertyCreateUrl(projectId, params), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(groupApi),
    })
}

/**
 * List all groups of a specific group type. You must pass ?group_type_index= in the URL. To get a list of valid group types, call /api/:project_id/groups_types/
 */
export const getGroupsList2Url = (projectId: string, params: GroupsList2Params) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/groups/?${stringifiedParams}`
        : `/api/projects/${projectId}/groups/`
}

export const groupsList2 = async (
    projectId: string,
    params: GroupsList2Params,
    options?: RequestInit
): Promise<PaginatedGroupListApi> => {
    return apiMutator<PaginatedGroupListApi>(getGroupsList2Url(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getGroupsCreate2Url = (projectId: string) => {
    return `/api/projects/${projectId}/groups/`
}

export const groupsCreate2 = async (
    projectId: string,
    createGroupApi: CreateGroupApi,
    options?: RequestInit
): Promise<GroupApi> => {
    return apiMutator<GroupApi>(getGroupsCreate2Url(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(createGroupApi),
    })
}

export const getGroupsActivityRetrieve2Url = (projectId: string, params: GroupsActivityRetrieve2Params) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/groups/activity/?${stringifiedParams}`
        : `/api/projects/${projectId}/groups/activity/`
}

export const groupsActivityRetrieve2 = async (
    projectId: string,
    params: GroupsActivityRetrieve2Params,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getGroupsActivityRetrieve2Url(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getGroupsDeletePropertyCreate2Url = (projectId: string, params: GroupsDeletePropertyCreate2Params) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/groups/delete_property/?${stringifiedParams}`
        : `/api/projects/${projectId}/groups/delete_property/`
}

export const groupsDeletePropertyCreate2 = async (
    projectId: string,
    groupApi: NonReadonly<GroupApi>,
    params: GroupsDeletePropertyCreate2Params,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getGroupsDeletePropertyCreate2Url(projectId, params), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(groupApi),
    })
}

export const getGroupsFindRetrieve2Url = (projectId: string, params: GroupsFindRetrieve2Params) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/groups/find/?${stringifiedParams}`
        : `/api/projects/${projectId}/groups/find/`
}

export const groupsFindRetrieve2 = async (
    projectId: string,
    params: GroupsFindRetrieve2Params,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getGroupsFindRetrieve2Url(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getGroupsPropertyDefinitionsRetrieve2Url = (projectId: string) => {
    return `/api/projects/${projectId}/groups/property_definitions/`
}

export const groupsPropertyDefinitionsRetrieve2 = async (projectId: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getGroupsPropertyDefinitionsRetrieve2Url(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getGroupsPropertyValuesRetrieve2Url = (projectId: string) => {
    return `/api/projects/${projectId}/groups/property_values/`
}

export const groupsPropertyValuesRetrieve2 = async (projectId: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getGroupsPropertyValuesRetrieve2Url(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getGroupsRelatedRetrieve2Url = (projectId: string, params: GroupsRelatedRetrieve2Params) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/groups/related/?${stringifiedParams}`
        : `/api/projects/${projectId}/groups/related/`
}

export const groupsRelatedRetrieve2 = async (
    projectId: string,
    params: GroupsRelatedRetrieve2Params,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getGroupsRelatedRetrieve2Url(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getGroupsUpdatePropertyCreate2Url = (projectId: string, params: GroupsUpdatePropertyCreate2Params) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/groups/update_property/?${stringifiedParams}`
        : `/api/projects/${projectId}/groups/update_property/`
}

export const groupsUpdatePropertyCreate2 = async (
    projectId: string,
    groupApi: NonReadonly<GroupApi>,
    params: GroupsUpdatePropertyCreate2Params,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getGroupsUpdatePropertyCreate2Url(projectId, params), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(groupApi),
    })
}
