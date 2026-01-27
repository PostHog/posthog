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
        ? `/api/environments/${projectId}/groups/?${stringifiedParams}`
        : `/api/environments/${projectId}/groups/`
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
    return `/api/environments/${projectId}/groups/`
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
        ? `/api/environments/${projectId}/groups/activity/?${stringifiedParams}`
        : `/api/environments/${projectId}/groups/activity/`
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
        ? `/api/environments/${projectId}/groups/delete_property/?${stringifiedParams}`
        : `/api/environments/${projectId}/groups/delete_property/`
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
        ? `/api/environments/${projectId}/groups/find/?${stringifiedParams}`
        : `/api/environments/${projectId}/groups/find/`
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
    return `/api/environments/${projectId}/groups/property_definitions/`
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
    return `/api/environments/${projectId}/groups/property_values/`
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
        ? `/api/environments/${projectId}/groups/related/?${stringifiedParams}`
        : `/api/environments/${projectId}/groups/related/`
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
        ? `/api/environments/${projectId}/groups/update_property/?${stringifiedParams}`
        : `/api/environments/${projectId}/groups/update_property/`
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

/**
 * List all groups of a specific group type. You must pass ?group_type_index= in the URL. To get a list of valid group types, call /api/:project_id/groups_types/
 */
export type groupsList2Response200 = {
    data: PaginatedGroupListApi
    status: 200
}

export type groupsList2ResponseSuccess = groupsList2Response200 & {
    headers: Headers
}
export type groupsList2Response = groupsList2ResponseSuccess

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
): Promise<groupsList2Response> => {
    return apiMutator<groupsList2Response>(getGroupsList2Url(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export type groupsCreate2Response201 = {
    data: GroupApi
    status: 201
}

export type groupsCreate2ResponseSuccess = groupsCreate2Response201 & {
    headers: Headers
}
export type groupsCreate2Response = groupsCreate2ResponseSuccess

export const getGroupsCreate2Url = (projectId: string) => {
    return `/api/projects/${projectId}/groups/`
}

export const groupsCreate2 = async (
    projectId: string,
    createGroupApi: CreateGroupApi,
    options?: RequestInit
): Promise<groupsCreate2Response> => {
    return apiMutator<groupsCreate2Response>(getGroupsCreate2Url(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(createGroupApi),
    })
}

export type groupsActivityRetrieve2Response200 = {
    data: void
    status: 200
}

export type groupsActivityRetrieve2ResponseSuccess = groupsActivityRetrieve2Response200 & {
    headers: Headers
}
export type groupsActivityRetrieve2Response = groupsActivityRetrieve2ResponseSuccess

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
): Promise<groupsActivityRetrieve2Response> => {
    return apiMutator<groupsActivityRetrieve2Response>(getGroupsActivityRetrieve2Url(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export type groupsDeletePropertyCreate2Response200 = {
    data: void
    status: 200
}

export type groupsDeletePropertyCreate2ResponseSuccess = groupsDeletePropertyCreate2Response200 & {
    headers: Headers
}
export type groupsDeletePropertyCreate2Response = groupsDeletePropertyCreate2ResponseSuccess

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
): Promise<groupsDeletePropertyCreate2Response> => {
    return apiMutator<groupsDeletePropertyCreate2Response>(getGroupsDeletePropertyCreate2Url(projectId, params), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(groupApi),
    })
}

export type groupsFindRetrieve2Response200 = {
    data: void
    status: 200
}

export type groupsFindRetrieve2ResponseSuccess = groupsFindRetrieve2Response200 & {
    headers: Headers
}
export type groupsFindRetrieve2Response = groupsFindRetrieve2ResponseSuccess

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
): Promise<groupsFindRetrieve2Response> => {
    return apiMutator<groupsFindRetrieve2Response>(getGroupsFindRetrieve2Url(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export type groupsPropertyDefinitionsRetrieve2Response200 = {
    data: void
    status: 200
}

export type groupsPropertyDefinitionsRetrieve2ResponseSuccess = groupsPropertyDefinitionsRetrieve2Response200 & {
    headers: Headers
}
export type groupsPropertyDefinitionsRetrieve2Response = groupsPropertyDefinitionsRetrieve2ResponseSuccess

export const getGroupsPropertyDefinitionsRetrieve2Url = (projectId: string) => {
    return `/api/projects/${projectId}/groups/property_definitions/`
}

export const groupsPropertyDefinitionsRetrieve2 = async (
    projectId: string,
    options?: RequestInit
): Promise<groupsPropertyDefinitionsRetrieve2Response> => {
    return apiMutator<groupsPropertyDefinitionsRetrieve2Response>(getGroupsPropertyDefinitionsRetrieve2Url(projectId), {
        ...options,
        method: 'GET',
    })
}

export type groupsPropertyValuesRetrieve2Response200 = {
    data: void
    status: 200
}

export type groupsPropertyValuesRetrieve2ResponseSuccess = groupsPropertyValuesRetrieve2Response200 & {
    headers: Headers
}
export type groupsPropertyValuesRetrieve2Response = groupsPropertyValuesRetrieve2ResponseSuccess

export const getGroupsPropertyValuesRetrieve2Url = (projectId: string) => {
    return `/api/projects/${projectId}/groups/property_values/`
}

export const groupsPropertyValuesRetrieve2 = async (
    projectId: string,
    options?: RequestInit
): Promise<groupsPropertyValuesRetrieve2Response> => {
    return apiMutator<groupsPropertyValuesRetrieve2Response>(getGroupsPropertyValuesRetrieve2Url(projectId), {
        ...options,
        method: 'GET',
    })
}

export type groupsRelatedRetrieve2Response200 = {
    data: void
    status: 200
}

export type groupsRelatedRetrieve2ResponseSuccess = groupsRelatedRetrieve2Response200 & {
    headers: Headers
}
export type groupsRelatedRetrieve2Response = groupsRelatedRetrieve2ResponseSuccess

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
): Promise<groupsRelatedRetrieve2Response> => {
    return apiMutator<groupsRelatedRetrieve2Response>(getGroupsRelatedRetrieve2Url(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export type groupsUpdatePropertyCreate2Response200 = {
    data: void
    status: 200
}

export type groupsUpdatePropertyCreate2ResponseSuccess = groupsUpdatePropertyCreate2Response200 & {
    headers: Headers
}
export type groupsUpdatePropertyCreate2Response = groupsUpdatePropertyCreate2ResponseSuccess

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
): Promise<groupsUpdatePropertyCreate2Response> => {
    return apiMutator<groupsUpdatePropertyCreate2Response>(getGroupsUpdatePropertyCreate2Url(projectId, params), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(groupApi),
    })
}
