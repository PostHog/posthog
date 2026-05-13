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
    BulkCreateMonitorApi,
    CreateMonitorApi,
    MonitorDTOApi,
    PaginatedMonitorDTOListApi,
    PaginatedMonitorSummaryDTOListApi,
    PaginatedPingDTOListApi,
    PaginatedSuggestedUrlDTOListApi,
    PatchedUpdateMonitorApi,
    UptimeMonitorsBulkCreateCreateParams,
    UptimeMonitorsListParams,
    UptimeMonitorsPingsListParams,
    UptimeMonitorsSuggestedUrlsListParams,
    UptimeMonitorsSummaryListParams,
} from './api.schemas'

export const getUptimeMonitorsListUrl = (projectId: string, params?: UptimeMonitorsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/uptime/monitors/?${stringifiedParams}`
        : `/api/projects/${projectId}/uptime/monitors/`
}

export const uptimeMonitorsList = async (
    projectId: string,
    params?: UptimeMonitorsListParams,
    options?: RequestInit
): Promise<PaginatedMonitorDTOListApi> => {
    return apiMutator<PaginatedMonitorDTOListApi>(getUptimeMonitorsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getUptimeMonitorsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/uptime/monitors/`
}

export const uptimeMonitorsCreate = async (
    projectId: string,
    createMonitorApi: CreateMonitorApi,
    options?: RequestInit
): Promise<MonitorDTOApi> => {
    return apiMutator<MonitorDTOApi>(getUptimeMonitorsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(createMonitorApi),
    })
}

export const getUptimeMonitorsPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/uptime/monitors/${id}/`
}

export const uptimeMonitorsPartialUpdate = async (
    projectId: string,
    id: string,
    patchedUpdateMonitorApi?: PatchedUpdateMonitorApi,
    options?: RequestInit
): Promise<MonitorDTOApi> => {
    return apiMutator<MonitorDTOApi>(getUptimeMonitorsPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedUpdateMonitorApi),
    })
}

export const getUptimeMonitorsDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/uptime/monitors/${id}/`
}

export const uptimeMonitorsDestroy = async (projectId: string, id: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getUptimeMonitorsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getUptimeMonitorsPingNowCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/uptime/monitors/${id}/ping_now/`
}

export const uptimeMonitorsPingNowCreate = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getUptimeMonitorsPingNowCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
    })
}

export const getUptimeMonitorsPingsListUrl = (
    projectId: string,
    id: string,
    params?: UptimeMonitorsPingsListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/uptime/monitors/${id}/pings/?${stringifiedParams}`
        : `/api/projects/${projectId}/uptime/monitors/${id}/pings/`
}

export const uptimeMonitorsPingsList = async (
    projectId: string,
    id: string,
    params?: UptimeMonitorsPingsListParams,
    options?: RequestInit
): Promise<PaginatedPingDTOListApi> => {
    return apiMutator<PaginatedPingDTOListApi>(getUptimeMonitorsPingsListUrl(projectId, id, params), {
        ...options,
        method: 'GET',
    })
}

export const getUptimeMonitorsBulkCreateCreateUrl = (
    projectId: string,
    params?: UptimeMonitorsBulkCreateCreateParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/uptime/monitors/bulk_create/?${stringifiedParams}`
        : `/api/projects/${projectId}/uptime/monitors/bulk_create/`
}

/**
 * Create multiple monitors in a single atomic transaction. Used by the URL-suggester bulk add.
 */
export const uptimeMonitorsBulkCreateCreate = async (
    projectId: string,
    bulkCreateMonitorApi: BulkCreateMonitorApi,
    params?: UptimeMonitorsBulkCreateCreateParams,
    options?: RequestInit
): Promise<PaginatedMonitorDTOListApi> => {
    return apiMutator<PaginatedMonitorDTOListApi>(getUptimeMonitorsBulkCreateCreateUrl(projectId, params), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(bulkCreateMonitorApi),
    })
}

export const getUptimeMonitorsSuggestedUrlsListUrl = (
    projectId: string,
    params?: UptimeMonitorsSuggestedUrlsListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/uptime/monitors/suggested_urls/?${stringifiedParams}`
        : `/api/projects/${projectId}/uptime/monitors/suggested_urls/`
}

/**
 * Suggest pingable URLs derived from $pageview events, excluding hosts already monitored.
 */
export const uptimeMonitorsSuggestedUrlsList = async (
    projectId: string,
    params?: UptimeMonitorsSuggestedUrlsListParams,
    options?: RequestInit
): Promise<PaginatedSuggestedUrlDTOListApi> => {
    return apiMutator<PaginatedSuggestedUrlDTOListApi>(getUptimeMonitorsSuggestedUrlsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getUptimeMonitorsSummaryListUrl = (projectId: string, params?: UptimeMonitorsSummaryListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/uptime/monitors/summary/?${stringifiedParams}`
        : `/api/projects/${projectId}/uptime/monitors/summary/`
}

/**
 * Per-monitor status, 30-day uptime, 24h latency, last ping, and 30 daily status buckets.
 */
export const uptimeMonitorsSummaryList = async (
    projectId: string,
    params?: UptimeMonitorsSummaryListParams,
    options?: RequestInit
): Promise<PaginatedMonitorSummaryDTOListApi> => {
    return apiMutator<PaginatedMonitorSummaryDTOListApi>(getUptimeMonitorsSummaryListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}
