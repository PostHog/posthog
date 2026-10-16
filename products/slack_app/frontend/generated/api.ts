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
import type { SlackAppWorkspaceSetupApi } from './api.schemas'

export const getSlackAppWorkspaceSetupRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/slack_app_workspace_setup/${id}/`
}

/**
 * @summary Get the workspace setup steps for a Slack app install
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
