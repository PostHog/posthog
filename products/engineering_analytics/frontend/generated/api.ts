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
    CICardSummaryApi,
    EngineeringAnalyticsPrLifecycleParams,
    EngineeringAnalyticsPullRequestsParams,
    EngineeringAnalyticsQuarantineParams,
    EngineeringAnalyticsWorkflowHealthParams,
    PRLifecycleApi,
    PullRequestListApi,
    QuarantineFileApi,
    WorkflowHealthItemApi,
} from './api.schemas'

export const getEngineeringAnalyticsCiCardsUrl = (projectId: string) => {
    return `/api/projects/${projectId}/engineering_analytics/ci_cards/`
}

/**
 * Headline counts for the open-PR backlog: open PRs, distinct repos, stuck PRs (open, non-draft, non-bot, older than 7 days), and PRs with failing CI. The failing-CI count rests on the head-SHA join and can lag until late CI completions settle.
 */
export const engineeringAnalyticsCiCards = async (
    projectId: string,
    options?: RequestInit
): Promise<CICardSummaryApi> => {
    return apiMutator<CICardSummaryApi>(getEngineeringAnalyticsCiCardsUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getEngineeringAnalyticsPrLifecycleUrl = (
    projectId: string,
    params: EngineeringAnalyticsPrLifecycleParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
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

export const getEngineeringAnalyticsPullRequestsUrl = (
    projectId: string,
    params?: EngineeringAnalyticsPullRequestsParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/engineering_analytics/pull_requests/?${stringifiedParams}`
        : `/api/projects/${projectId}/engineering_analytics/pull_requests/`
}

/**
 * Open pull requests plus any merged or closed since date_from (default -30d), newest first, each with its head-SHA CI rollup. The list is capped; when more match, `truncated` is true and the ci_cards counts can exceed it. open_to_merge_seconds is coarse — it fuses draft and ready-for-review time; CI counts can lag until late completions settle.
 */
export const engineeringAnalyticsPullRequests = async (
    projectId: string,
    params?: EngineeringAnalyticsPullRequestsParams,
    options?: RequestInit
): Promise<PullRequestListApi> => {
    return apiMutator<PullRequestListApi>(getEngineeringAnalyticsPullRequestsUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getEngineeringAnalyticsQuarantineUrl = (
    projectId: string,
    params?: EngineeringAnalyticsQuarantineParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/engineering_analytics/quarantine/?${stringifiedParams}`
        : `/api/projects/${projectId}/engineering_analytics/quarantine/`
}

/**
 * The repository's checked-in .test_quarantine.json: flaky tests temporarily quarantined with a hard expiry, classified by urgency (overdue, in grace, expiring soon, active). `available` is false when the repo has no quarantine file — that is not an error. Parsing is fail-open: malformed entries are reported in parse_errors while well-formed ones are kept.
 * @summary Flaky-test quarantine file
 */
export const engineeringAnalyticsQuarantine = async (
    projectId: string,
    params?: EngineeringAnalyticsQuarantineParams,
    options?: RequestInit
): Promise<QuarantineFileApi> => {
    return apiMutator<QuarantineFileApi>(getEngineeringAnalyticsQuarantineUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getEngineeringAnalyticsWorkflowHealthUrl = (
    projectId: string,
    params?: EngineeringAnalyticsWorkflowHealthParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/engineering_analytics/workflow_health/?${stringifiedParams}`
        : `/api/projects/${projectId}/engineering_analytics/workflow_health/`
}

/**
 * Per-workflow CI health over a window (default last 30 days, maximum 366 days): run count, success rate, p50/p95 duration over completed runs, last failure time, and a zero-filled daily run history. Use this for 'is CI getting slower' and 'which workflow is the long pole'; compare two windows to get a trend.
 */
export const engineeringAnalyticsWorkflowHealth = async (
    projectId: string,
    params?: EngineeringAnalyticsWorkflowHealthParams,
    options?: RequestInit
): Promise<WorkflowHealthItemApi[]> => {
    return apiMutator<WorkflowHealthItemApi[]>(getEngineeringAnalyticsWorkflowHealthUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}
