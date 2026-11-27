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
    PatchedSlackAppPersonalSettingsUpdateApi,
    PatchedSlackAppWorkspaceSettingsUpdateApi,
    SlackAppChannelOptionsApi,
    SlackAppChannelSettingsApi,
    SlackAppChannelSettingsListApi,
    SlackAppChannelSettingsUpdateApi,
    SlackAppDefaultProjectApi,
    SlackAppJoinChannelsApi,
    SlackAppJoinChannelsResultApi,
    SlackAppRepositoryOptionsApi,
    SlackAppSettingsApi,
    SlackAppWorkspaceSetupApi,
    SlackAppWorkspaceSetupRetrieveParams,
} from './api.schemas'

export const getSlackAppSettingsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/slack_app_settings/${id}/`
}

/**
 * @summary Get the personal and workspace settings of a Slack app install
 */
export const slackAppSettingsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<SlackAppSettingsApi> => {
    return apiMutator<SlackAppSettingsApi>(getSlackAppSettingsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getSlackAppSettingsChannelsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/slack_app_settings/${id}/channels/`
}

/**
 * @summary List the channel settings of a Slack app install
 */
export const slackAppSettingsChannelsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<SlackAppChannelSettingsListApi> => {
    return apiMutator<SlackAppChannelSettingsListApi>(getSlackAppSettingsChannelsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getSlackAppSettingsChannelsUpdateUrl = (projectId: string, id: string, slackChannelId: string) => {
    return `/api/projects/${projectId}/slack_app_settings/${id}/channels/${slackChannelId}/`
}

/**
 * @summary Replace the settings of one channel of a Slack app install
 */
export const slackAppSettingsChannelsUpdate = async (
    projectId: string,
    id: string,
    slackChannelId: string,
    slackAppChannelSettingsUpdateApi: SlackAppChannelSettingsUpdateApi,
    options?: RequestInit
): Promise<SlackAppChannelSettingsApi> => {
    return apiMutator<SlackAppChannelSettingsApi>(getSlackAppSettingsChannelsUpdateUrl(projectId, id, slackChannelId), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(slackAppChannelSettingsUpdateApi),
    })
}

export const getSlackAppSettingsPersonalPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/slack_app_settings/${id}/personal/`
}

/**
 * @summary Change your own settings for a Slack app install
 */
export const slackAppSettingsPersonalPartialUpdate = async (
    projectId: string,
    id: string,
    patchedSlackAppPersonalSettingsUpdateApi?: PatchedSlackAppPersonalSettingsUpdateApi,
    options?: RequestInit
): Promise<SlackAppSettingsApi> => {
    return apiMutator<SlackAppSettingsApi>(getSlackAppSettingsPersonalPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedSlackAppPersonalSettingsUpdateApi),
    })
}

export const getSlackAppSettingsRepositoriesRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/slack_app_settings/${id}/repositories/`
}

/**
 * @summary List the repositories this person can set as a channel's default repository
 */
export const slackAppSettingsRepositoriesRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<SlackAppRepositoryOptionsApi> => {
    return apiMutator<SlackAppRepositoryOptionsApi>(getSlackAppSettingsRepositoriesRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getSlackAppSettingsWorkspacePartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/slack_app_settings/${id}/workspace/`
}

/**
 * @summary Change the workspace settings of a Slack app install
 */
export const slackAppSettingsWorkspacePartialUpdate = async (
    projectId: string,
    id: string,
    patchedSlackAppWorkspaceSettingsUpdateApi?: PatchedSlackAppWorkspaceSettingsUpdateApi,
    options?: RequestInit
): Promise<SlackAppSettingsApi> => {
    return apiMutator<SlackAppSettingsApi>(getSlackAppSettingsWorkspacePartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedSlackAppWorkspaceSettingsUpdateApi),
    })
}

export const getSlackAppWorkspaceSetupRetrieveUrl = (
    projectId: string,
    id: string,
    params?: SlackAppWorkspaceSetupRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/slack_app_workspace_setup/${id}/?${stringifiedParams}`
        : `/api/projects/${projectId}/slack_app_workspace_setup/${id}/`
}

/**
 * @summary Get the web setup steps for a Slack app install
 */
export const slackAppWorkspaceSetupRetrieve = async (
    projectId: string,
    id: string,
    params?: SlackAppWorkspaceSetupRetrieveParams,
    options?: RequestInit
): Promise<SlackAppWorkspaceSetupApi> => {
    return apiMutator<SlackAppWorkspaceSetupApi>(getSlackAppWorkspaceSetupRetrieveUrl(projectId, id, params), {
        ...options,
        method: 'GET',
    })
}

export const getSlackAppWorkspaceSetupChannelsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/slack_app_workspace_setup/${id}/channels/`
}

/**
 * @summary List the public channels that PostHog can join for a Slack app install
 */
export const slackAppWorkspaceSetupChannelsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<SlackAppChannelOptionsApi> => {
    return apiMutator<SlackAppChannelOptionsApi>(getSlackAppWorkspaceSetupChannelsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getSlackAppWorkspaceSetupDefaultProjectCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/slack_app_workspace_setup/${id}/default_project/`
}

/**
 * @summary Set the default project for the Slack workspace of a Slack app install
 */
export const slackAppWorkspaceSetupDefaultProjectCreate = async (
    projectId: string,
    id: string,
    slackAppDefaultProjectApi: SlackAppDefaultProjectApi,
    options?: RequestInit
): Promise<SlackAppWorkspaceSetupApi> => {
    return apiMutator<SlackAppWorkspaceSetupApi>(getSlackAppWorkspaceSetupDefaultProjectCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(slackAppDefaultProjectApi),
    })
}

export const getSlackAppWorkspaceSetupJoinChannelsCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/slack_app_workspace_setup/${id}/join_channels/`
}

/**
 * @summary Add PostHog to public channels of a Slack app install
 */
export const slackAppWorkspaceSetupJoinChannelsCreate = async (
    projectId: string,
    id: string,
    slackAppJoinChannelsApi: SlackAppJoinChannelsApi,
    options?: RequestInit
): Promise<SlackAppJoinChannelsResultApi> => {
    return apiMutator<SlackAppJoinChannelsResultApi>(getSlackAppWorkspaceSetupJoinChannelsCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(slackAppJoinChannelsApi),
    })
}
