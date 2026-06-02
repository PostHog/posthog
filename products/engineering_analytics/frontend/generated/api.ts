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
import type { EngineeringAnalyticsPrLifecycleParams, PRLifecycleApi } from './api.schemas'

export const getEngineeringAnalyticsPrLifecycleUrl = (
    projectId: string,
    params: EngineeringAnalyticsPrLifecycleParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/engineering_analytics/pr_lifecycle/?${stringifiedParams}`
        : `/api/projects/${projectId}/engineering_analytics/pr_lifecycle/`
}

/**
 * The timeline of a single pull request: header plus ordered events (opened, CI started/finished, merged or closed). Use this to answer 'where is this PR stuck and what happened to it'. This is a partial view: review and comment events are not yet available.
 */
export const engineeringAnalyticsPrLifecycle = async (
    projectId: string,
    params: EngineeringAnalyticsPrLifecycleParams,
    options?: RequestInit
): Promise<PRLifecycleApi> => {
    return apiMutator<PRLifecycleApi>(getEngineeringAnalyticsPrLifecycleUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}
