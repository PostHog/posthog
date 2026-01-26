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
    EnvironmentsGroupsActivityRetrieveParams,
    EnvironmentsGroupsDeletePropertyCreateParams,
    EnvironmentsGroupsFindRetrieveParams,
    EnvironmentsGroupsListParams,
    EnvironmentsGroupsRelatedRetrieveParams,
    EnvironmentsGroupsUpdatePropertyCreateParams,
    GroupApi,
    GroupsActivityRetrieveParams,
    GroupsDeletePropertyCreateParams,
    GroupsFindRetrieveParams,
    GroupsListParams,
    GroupsRelatedRetrieveParams,
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
export type environmentsGroupsListResponse200 = {
    data: PaginatedGroupListApi
    status: 200
}

export type environmentsGroupsListResponseSuccess = environmentsGroupsListResponse200 & {
    headers: Headers
}
export type environmentsGroupsListResponse = environmentsGroupsListResponseSuccess

export const getEnvironmentsGroupsListUrl = (projectId: string, params: EnvironmentsGroupsListParams) => {
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

export const environmentsGroupsList = async (
    projectId: string,
    params: EnvironmentsGroupsListParams,
    options?: RequestInit
): Promise<environmentsGroupsListResponse> => {
    return apiMutator<environmentsGroupsListResponse>(getEnvironmentsGroupsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export type environmentsGroupsCreateResponse201 = {
    data: GroupApi
    status: 201
}

export type environmentsGroupsCreateResponseSuccess = environmentsGroupsCreateResponse201 & {
    headers: Headers
}
export type environmentsGroupsCreateResponse = environmentsGroupsCreateResponseSuccess

export const getEnvironmentsGroupsCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/groups/`
}

export const environmentsGroupsCreate = async (
    projectId: string,
    createGroupApi: CreateGroupApi,
    options?: RequestInit
): Promise<environmentsGroupsCreateResponse> => {
    return apiMutator<environmentsGroupsCreateResponse>(getEnvironmentsGroupsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(createGroupApi),
    })
}

export type environmentsGroupsActivityRetrieveResponse200 = {
    data: void
    status: 200
}

export type environmentsGroupsActivityRetrieveResponseSuccess = environmentsGroupsActivityRetrieveResponse200 & {
    headers: Headers
}
export type environmentsGroupsActivityRetrieveResponse = environmentsGroupsActivityRetrieveResponseSuccess

export const getEnvironmentsGroupsActivityRetrieveUrl = (
    projectId: string,
    params: EnvironmentsGroupsActivityRetrieveParams
) => {
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

export const environmentsGroupsActivityRetrieve = async (
    projectId: string,
    params: EnvironmentsGroupsActivityRetrieveParams,
    options?: RequestInit
): Promise<environmentsGroupsActivityRetrieveResponse> => {
    return apiMutator<environmentsGroupsActivityRetrieveResponse>(
        getEnvironmentsGroupsActivityRetrieveUrl(projectId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export type environmentsGroupsDeletePropertyCreateResponse200 = {
    data: void
    status: 200
}

export type environmentsGroupsDeletePropertyCreateResponseSuccess =
    environmentsGroupsDeletePropertyCreateResponse200 & {
        headers: Headers
    }
export type environmentsGroupsDeletePropertyCreateResponse = environmentsGroupsDeletePropertyCreateResponseSuccess

export const getEnvironmentsGroupsDeletePropertyCreateUrl = (
    projectId: string,
    params: EnvironmentsGroupsDeletePropertyCreateParams
) => {
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

export const environmentsGroupsDeletePropertyCreate = async (
    projectId: string,
    groupApi: NonReadonly<GroupApi>,
    params: EnvironmentsGroupsDeletePropertyCreateParams,
    options?: RequestInit
): Promise<environmentsGroupsDeletePropertyCreateResponse> => {
    return apiMutator<environmentsGroupsDeletePropertyCreateResponse>(
        getEnvironmentsGroupsDeletePropertyCreateUrl(projectId, params),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(groupApi),
        }
    )
}

export type environmentsGroupsFindRetrieveResponse200 = {
    data: void
    status: 200
}

export type environmentsGroupsFindRetrieveResponseSuccess = environmentsGroupsFindRetrieveResponse200 & {
    headers: Headers
}
export type environmentsGroupsFindRetrieveResponse = environmentsGroupsFindRetrieveResponseSuccess

export const getEnvironmentsGroupsFindRetrieveUrl = (
    projectId: string,
    params: EnvironmentsGroupsFindRetrieveParams
) => {
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

export const environmentsGroupsFindRetrieve = async (
    projectId: string,
    params: EnvironmentsGroupsFindRetrieveParams,
    options?: RequestInit
): Promise<environmentsGroupsFindRetrieveResponse> => {
    return apiMutator<environmentsGroupsFindRetrieveResponse>(getEnvironmentsGroupsFindRetrieveUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export type environmentsGroupsPropertyDefinitionsRetrieveResponse200 = {
    data: void
    status: 200
}

export type environmentsGroupsPropertyDefinitionsRetrieveResponseSuccess =
    environmentsGroupsPropertyDefinitionsRetrieveResponse200 & {
        headers: Headers
    }
export type environmentsGroupsPropertyDefinitionsRetrieveResponse =
    environmentsGroupsPropertyDefinitionsRetrieveResponseSuccess

export const getEnvironmentsGroupsPropertyDefinitionsRetrieveUrl = (projectId: string) => {
    return `/api/environments/${projectId}/groups/property_definitions/`
}

export const environmentsGroupsPropertyDefinitionsRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<environmentsGroupsPropertyDefinitionsRetrieveResponse> => {
    return apiMutator<environmentsGroupsPropertyDefinitionsRetrieveResponse>(
        getEnvironmentsGroupsPropertyDefinitionsRetrieveUrl(projectId),
        {
            ...options,
            method: 'GET',
        }
    )
}

export type environmentsGroupsPropertyValuesRetrieveResponse200 = {
    data: void
    status: 200
}

export type environmentsGroupsPropertyValuesRetrieveResponseSuccess =
    environmentsGroupsPropertyValuesRetrieveResponse200 & {
        headers: Headers
    }
export type environmentsGroupsPropertyValuesRetrieveResponse = environmentsGroupsPropertyValuesRetrieveResponseSuccess

export const getEnvironmentsGroupsPropertyValuesRetrieveUrl = (projectId: string) => {
    return `/api/environments/${projectId}/groups/property_values/`
}

export const environmentsGroupsPropertyValuesRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<environmentsGroupsPropertyValuesRetrieveResponse> => {
    return apiMutator<environmentsGroupsPropertyValuesRetrieveResponse>(
        getEnvironmentsGroupsPropertyValuesRetrieveUrl(projectId),
        {
            ...options,
            method: 'GET',
        }
    )
}

export type environmentsGroupsRelatedRetrieveResponse200 = {
    data: void
    status: 200
}

export type environmentsGroupsRelatedRetrieveResponseSuccess = environmentsGroupsRelatedRetrieveResponse200 & {
    headers: Headers
}
export type environmentsGroupsRelatedRetrieveResponse = environmentsGroupsRelatedRetrieveResponseSuccess

export const getEnvironmentsGroupsRelatedRetrieveUrl = (
    projectId: string,
    params: EnvironmentsGroupsRelatedRetrieveParams
) => {
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

export const environmentsGroupsRelatedRetrieve = async (
    projectId: string,
    params: EnvironmentsGroupsRelatedRetrieveParams,
    options?: RequestInit
): Promise<environmentsGroupsRelatedRetrieveResponse> => {
    return apiMutator<environmentsGroupsRelatedRetrieveResponse>(
        getEnvironmentsGroupsRelatedRetrieveUrl(projectId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export type environmentsGroupsUpdatePropertyCreateResponse200 = {
    data: void
    status: 200
}

export type environmentsGroupsUpdatePropertyCreateResponseSuccess =
    environmentsGroupsUpdatePropertyCreateResponse200 & {
        headers: Headers
    }
export type environmentsGroupsUpdatePropertyCreateResponse = environmentsGroupsUpdatePropertyCreateResponseSuccess

export const getEnvironmentsGroupsUpdatePropertyCreateUrl = (
    projectId: string,
    params: EnvironmentsGroupsUpdatePropertyCreateParams
) => {
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

export const environmentsGroupsUpdatePropertyCreate = async (
    projectId: string,
    groupApi: NonReadonly<GroupApi>,
    params: EnvironmentsGroupsUpdatePropertyCreateParams,
    options?: RequestInit
): Promise<environmentsGroupsUpdatePropertyCreateResponse> => {
    return apiMutator<environmentsGroupsUpdatePropertyCreateResponse>(
        getEnvironmentsGroupsUpdatePropertyCreateUrl(projectId, params),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(groupApi),
        }
    )
}

/**
 * List all groups of a specific group type. You must pass ?group_type_index= in the URL. To get a list of valid group types, call /api/:project_id/groups_types/
 */
export type groupsListResponse200 = {
    data: PaginatedGroupListApi
    status: 200
}

export type groupsListResponseSuccess = groupsListResponse200 & {
    headers: Headers
}
export type groupsListResponse = groupsListResponseSuccess

export const getGroupsListUrl = (projectId: string, params: GroupsListParams) => {
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

export const groupsList = async (
    projectId: string,
    params: GroupsListParams,
    options?: RequestInit
): Promise<groupsListResponse> => {
    return apiMutator<groupsListResponse>(getGroupsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export type groupsCreateResponse201 = {
    data: GroupApi
    status: 201
}

export type groupsCreateResponseSuccess = groupsCreateResponse201 & {
    headers: Headers
}
export type groupsCreateResponse = groupsCreateResponseSuccess

export const getGroupsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/groups/`
}

export const groupsCreate = async (
    projectId: string,
    createGroupApi: CreateGroupApi,
    options?: RequestInit
): Promise<groupsCreateResponse> => {
    return apiMutator<groupsCreateResponse>(getGroupsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(createGroupApi),
    })
}

export type groupsActivityRetrieveResponse200 = {
    data: void
    status: 200
}

export type groupsActivityRetrieveResponseSuccess = groupsActivityRetrieveResponse200 & {
    headers: Headers
}
export type groupsActivityRetrieveResponse = groupsActivityRetrieveResponseSuccess

export const getGroupsActivityRetrieveUrl = (projectId: string, params: GroupsActivityRetrieveParams) => {
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

export const groupsActivityRetrieve = async (
    projectId: string,
    params: GroupsActivityRetrieveParams,
    options?: RequestInit
): Promise<groupsActivityRetrieveResponse> => {
    return apiMutator<groupsActivityRetrieveResponse>(getGroupsActivityRetrieveUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export type groupsDeletePropertyCreateResponse200 = {
    data: void
    status: 200
}

export type groupsDeletePropertyCreateResponseSuccess = groupsDeletePropertyCreateResponse200 & {
    headers: Headers
}
export type groupsDeletePropertyCreateResponse = groupsDeletePropertyCreateResponseSuccess

export const getGroupsDeletePropertyCreateUrl = (projectId: string, params: GroupsDeletePropertyCreateParams) => {
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

export const groupsDeletePropertyCreate = async (
    projectId: string,
    groupApi: NonReadonly<GroupApi>,
    params: GroupsDeletePropertyCreateParams,
    options?: RequestInit
): Promise<groupsDeletePropertyCreateResponse> => {
    return apiMutator<groupsDeletePropertyCreateResponse>(getGroupsDeletePropertyCreateUrl(projectId, params), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(groupApi),
    })
}

export type groupsFindRetrieveResponse200 = {
    data: void
    status: 200
}

export type groupsFindRetrieveResponseSuccess = groupsFindRetrieveResponse200 & {
    headers: Headers
}
export type groupsFindRetrieveResponse = groupsFindRetrieveResponseSuccess

export const getGroupsFindRetrieveUrl = (projectId: string, params: GroupsFindRetrieveParams) => {
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

export const groupsFindRetrieve = async (
    projectId: string,
    params: GroupsFindRetrieveParams,
    options?: RequestInit
): Promise<groupsFindRetrieveResponse> => {
    return apiMutator<groupsFindRetrieveResponse>(getGroupsFindRetrieveUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export type groupsPropertyDefinitionsRetrieveResponse200 = {
    data: void
    status: 200
}

export type groupsPropertyDefinitionsRetrieveResponseSuccess = groupsPropertyDefinitionsRetrieveResponse200 & {
    headers: Headers
}
export type groupsPropertyDefinitionsRetrieveResponse = groupsPropertyDefinitionsRetrieveResponseSuccess

export const getGroupsPropertyDefinitionsRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/groups/property_definitions/`
}

export const groupsPropertyDefinitionsRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<groupsPropertyDefinitionsRetrieveResponse> => {
    return apiMutator<groupsPropertyDefinitionsRetrieveResponse>(getGroupsPropertyDefinitionsRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export type groupsPropertyValuesRetrieveResponse200 = {
    data: void
    status: 200
}

export type groupsPropertyValuesRetrieveResponseSuccess = groupsPropertyValuesRetrieveResponse200 & {
    headers: Headers
}
export type groupsPropertyValuesRetrieveResponse = groupsPropertyValuesRetrieveResponseSuccess

export const getGroupsPropertyValuesRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/groups/property_values/`
}

export const groupsPropertyValuesRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<groupsPropertyValuesRetrieveResponse> => {
    return apiMutator<groupsPropertyValuesRetrieveResponse>(getGroupsPropertyValuesRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export type groupsRelatedRetrieveResponse200 = {
    data: void
    status: 200
}

export type groupsRelatedRetrieveResponseSuccess = groupsRelatedRetrieveResponse200 & {
    headers: Headers
}
export type groupsRelatedRetrieveResponse = groupsRelatedRetrieveResponseSuccess

export const getGroupsRelatedRetrieveUrl = (projectId: string, params: GroupsRelatedRetrieveParams) => {
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

export const groupsRelatedRetrieve = async (
    projectId: string,
    params: GroupsRelatedRetrieveParams,
    options?: RequestInit
): Promise<groupsRelatedRetrieveResponse> => {
    return apiMutator<groupsRelatedRetrieveResponse>(getGroupsRelatedRetrieveUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export type groupsUpdatePropertyCreateResponse200 = {
    data: void
    status: 200
}

export type groupsUpdatePropertyCreateResponseSuccess = groupsUpdatePropertyCreateResponse200 & {
    headers: Headers
}
export type groupsUpdatePropertyCreateResponse = groupsUpdatePropertyCreateResponseSuccess

export const getGroupsUpdatePropertyCreateUrl = (projectId: string, params: GroupsUpdatePropertyCreateParams) => {
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

export const groupsUpdatePropertyCreate = async (
    projectId: string,
    groupApi: NonReadonly<GroupApi>,
    params: GroupsUpdatePropertyCreateParams,
    options?: RequestInit
): Promise<groupsUpdatePropertyCreateResponse> => {
    return apiMutator<groupsUpdatePropertyCreateResponse>(getGroupsUpdatePropertyCreateUrl(projectId, params), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(groupApi),
    })
}
