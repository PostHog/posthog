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
    EngineeringAnalyticsPrLifecycleParams,
    EngineeringAnalyticsTimeToMergeParams,
    EngineeringAnalyticsWorkflowReportParams,
    PRLifecycleApi,
    TimeToMergeApi,
    WorkflowReportApi,
} from './api.schemas'

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

export const getEngineeringAnalyticsTimeToMergeUrl = (
    projectId: string,
    params?: EngineeringAnalyticsTimeToMergeParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/engineering_analytics/time_to_merge/?${stringifiedParams}`
        : `/api/projects/${projectId}/engineering_analytics/time_to_merge/`
}

/**
 * How long pull requests take from open to merge. Returns median and p95 seconds and a PR count, either overall or split per author. Bots and drafts are excluded. This is a coarse metric: it combines draft and ready-for-review time, since the warehouse holds current state, not a transition history.
 */
export const engineeringAnalyticsTimeToMerge = async (
    projectId: string,
    params?: EngineeringAnalyticsTimeToMergeParams,
    options?: RequestInit
): Promise<TimeToMergeApi> => {
    return apiMutator<TimeToMergeApi>(getEngineeringAnalyticsTimeToMergeUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getEngineeringAnalyticsWorkflowReportUrl = (
    projectId: string,
    params?: EngineeringAnalyticsWorkflowReportParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/engineering_analytics/workflow_report/?${stringifiedParams}`
        : `/api/projects/${projectId}/engineering_analytics/workflow_report/`
}

/**
 * Which CI workflows are the long poles right now. Returns each GitHub Actions workflow with its run count, success rate, median and p95 duration, and last failure, slowest median first. Use this to answer 'what's slow in CI this week' or to check whether a known long-pole workflow is holding up a PR.
 */
export const engineeringAnalyticsWorkflowReport = async (
    projectId: string,
    params?: EngineeringAnalyticsWorkflowReportParams,
    options?: RequestInit
): Promise<WorkflowReportApi> => {
    return apiMutator<WorkflowReportApi>(getEngineeringAnalyticsWorkflowReportUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}
