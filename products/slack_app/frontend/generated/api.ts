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
import type { SlackAppDefaultProjectApi, SlackAppWorkspaceSetupApi } from './api.schemas'

export const getSlackAppWorkspaceSetupRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/slack_app_workspace_setup/${id}/`
}

/**
 * @summary Get the web setup steps for a Slack app install
 */
export const slackAppWorkspaceSetupRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<SlackAppWorkspaceSetupApi> => {
    return apiMutator<SlackAppWorkspaceSetupApi>(getSlackAppWorkspaceSetupRetrieveUrl(projectId, id), {
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
