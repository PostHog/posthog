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
    CreateGroupApi,
    FindGroupApi,
    GroupApi,
    GroupDeletePropertyApi,
    GroupUpdatePropertyRequestApi,
    GroupsActivityRetrieveParams,
    GroupsDeletePropertyCreateParams,
    GroupsFindRetrieveParams,
    GroupsListParams,
    GroupsRelatedListParams,
    GroupsUpdatePropertyCreateParams,
    RelatedActorApi,
} from './api.schemas'

export const getGroupsListUrl = (projectId: string, params: GroupsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/groups/?${stringifiedParams}`
        : `/api/projects/${projectId}/groups/`
}

/**
 * List all groups of a specific group type. You must pass ?group_type_index= in the URL.
 * To get a list of valid group types, call /api/:project_id/groups_types/.
 *
 * Uses forward-only keyset pagination via the `cursor` parameter.
 * The `previous` field in the response envelope is always null.
 */
export const groupsList = async (
    projectId: string,
    params: GroupsListParams,
    options?: RequestInit
): Promise<GroupApi[]> => {
    return apiMutator<GroupApi[]>(getGroupsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getGroupsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/groups/`
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
            normalizedParams.append(key, value === null ? 'null' : String(value))
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
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/groups/delete_property/?${stringifiedParams}`
        : `/api/projects/${projectId}/groups/delete_property/`
}

export const groupsDeletePropertyCreate = async (
    projectId: string,
    groupDeletePropertyApi: GroupDeletePropertyApi,
    params: GroupsDeletePropertyCreateParams,
    options?: RequestInit
): Promise<GroupApi> => {
    return apiMutator<GroupApi>(getGroupsDeletePropertyCreateUrl(projectId, params), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(groupDeletePropertyApi),
    })
}

export const getGroupsFindRetrieveUrl = (projectId: string, params: GroupsFindRetrieveParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
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
): Promise<FindGroupApi> => {
    return apiMutator<FindGroupApi>(getGroupsFindRetrieveUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getGroupsPropertyValuesRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/groups/property_values/`
}

export const groupsPropertyValuesRetrieve = async (projectId: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getGroupsPropertyValuesRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getGroupsRelatedListUrl = (projectId: string, params: GroupsRelatedListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/groups/related/?${stringifiedParams}`
        : `/api/projects/${projectId}/groups/related/`
}

export const groupsRelatedList = async (
    projectId: string,
    params: GroupsRelatedListParams,
    options?: RequestInit
): Promise<RelatedActorApi[]> => {
    return apiMutator<RelatedActorApi[]>(getGroupsRelatedListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getGroupsUpdatePropertyCreateUrl = (projectId: string, params: GroupsUpdatePropertyCreateParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/groups/update_property/?${stringifiedParams}`
        : `/api/projects/${projectId}/groups/update_property/`
}

export const groupsUpdatePropertyCreate = async (
    projectId: string,
    groupUpdatePropertyRequestApi: GroupUpdatePropertyRequestApi,
    params: GroupsUpdatePropertyCreateParams,
    options?: RequestInit
): Promise<GroupApi> => {
    return apiMutator<GroupApi>(getGroupsUpdatePropertyCreateUrl(projectId, params), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(groupUpdatePropertyRequestApi),
    })
}
