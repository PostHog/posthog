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
    CreateIncidentApi,
    CreateMonitorApi,
    IncidentDTOApi,
    MonitorDTOApi,
    MonitorSummaryDTOApi,
    PaginatedIncidentDTOListApi,
    PaginatedMonitorDTOListApi,
    PaginatedMonitorSummaryDTOListApi,
    PaginatedOutageDTOListApi,
    PaginatedPingDTOListApi,
    PaginatedStatusPageDTOListApi,
    PaginatedSuggestedUrlDTOListApi,
    PatchedUpdateIncidentApi,
    PatchedUpdateMonitorApi,
    PatchedUpdateStatusPageApi,
    ReorderMonitorsApi,
    ResolveIncidentApi,
    StatusPageDTOApi,
    UptimeIncidentsListParams,
    UptimeMonitorsBulkCreateCreateParams,
    UptimeMonitorsListParams,
    UptimeMonitorsOutagesListParams,
    UptimeMonitorsPingsListParams,
    UptimeMonitorsSuggestedUrlsListParams,
    UptimeMonitorsSummaryListParams,
    UptimeStatusPagesListParams,
} from './api.schemas'

export const getUptimeIncidentsListUrl = (projectId: string, params?: UptimeIncidentsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/uptime/incidents/?${stringifiedParams}`
        : `/api/projects/${projectId}/uptime/incidents/`
}

/**
 * Incidents for the team, ongoing first, then most recently started.
 */
export const uptimeIncidentsList = async (
    projectId: string,
    params?: UptimeIncidentsListParams,
    options?: RequestInit
): Promise<PaginatedIncidentDTOListApi> => {
    return apiMutator<PaginatedIncidentDTOListApi>(getUptimeIncidentsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getUptimeIncidentsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/uptime/incidents/`
}

export const uptimeIncidentsCreate = async (
    projectId: string,
    createIncidentApi: CreateIncidentApi,
    options?: RequestInit
): Promise<IncidentDTOApi> => {
    return apiMutator<IncidentDTOApi>(getUptimeIncidentsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(createIncidentApi),
    })
}

export const getUptimeIncidentsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/uptime/incidents/${id}/`
}

export const uptimeIncidentsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<IncidentDTOApi> => {
    return apiMutator<IncidentDTOApi>(getUptimeIncidentsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getUptimeIncidentsPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/uptime/incidents/${id}/`
}

export const uptimeIncidentsPartialUpdate = async (
    projectId: string,
    id: string,
    patchedUpdateIncidentApi?: PatchedUpdateIncidentApi,
    options?: RequestInit
): Promise<IncidentDTOApi> => {
    return apiMutator<IncidentDTOApi>(getUptimeIncidentsPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedUpdateIncidentApi),
    })
}

export const getUptimeIncidentsDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/uptime/incidents/${id}/`
}

export const uptimeIncidentsDestroy = async (projectId: string, id: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getUptimeIncidentsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getUptimeIncidentsReopenCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/uptime/incidents/${id}/reopen/`
}

/**
 * Reopen the incident, clearing resolved_at and the resolution note so it shows as ongoing again.
 */
export const uptimeIncidentsReopenCreate = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<IncidentDTOApi> => {
    return apiMutator<IncidentDTOApi>(getUptimeIncidentsReopenCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
    })
}

export const getUptimeIncidentsResolveCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/uptime/incidents/${id}/resolve/`
}

/**
 * Mark the incident as resolved with a required resolution note. The note is shown on the public status page.
 */
export const uptimeIncidentsResolveCreate = async (
    projectId: string,
    id: string,
    resolveIncidentApi: ResolveIncidentApi,
    options?: RequestInit
): Promise<IncidentDTOApi> => {
    return apiMutator<IncidentDTOApi>(getUptimeIncidentsResolveCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(resolveIncidentApi),
    })
}

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

export const getUptimeMonitorsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/uptime/monitors/${id}/`
}

/**
 * Same data as the summary list, but for one monitor by id.
 */
export const uptimeMonitorsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<MonitorSummaryDTOApi> => {
    return apiMutator<MonitorSummaryDTOApi>(getUptimeMonitorsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
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

export const getUptimeMonitorsOutagesListUrl = (
    projectId: string,
    id: string,
    params?: UptimeMonitorsOutagesListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/uptime/monitors/${id}/outages/?${stringifiedParams}`
        : `/api/projects/${projectId}/uptime/monitors/${id}/outages/`
}

/**
 * Outages computed from raw pings: ongoing first, then most recently started resolved outages.
 */
export const uptimeMonitorsOutagesList = async (
    projectId: string,
    id: string,
    params?: UptimeMonitorsOutagesListParams,
    options?: RequestInit
): Promise<PaginatedOutageDTOListApi> => {
    return apiMutator<PaginatedOutageDTOListApi>(getUptimeMonitorsOutagesListUrl(projectId, id, params), {
        ...options,
        method: 'GET',
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

export const getUptimeMonitorsReorderCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/uptime/monitors/reorder/`
}

/**
 * Persist the user-controlled display order. Position 0 renders first.
 */
export const uptimeMonitorsReorderCreate = async (
    projectId: string,
    reorderMonitorsApi: ReorderMonitorsApi,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getUptimeMonitorsReorderCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(reorderMonitorsApi),
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

export const getUptimeStatusPagesListUrl = (projectId: string, params?: UptimeStatusPagesListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/uptime/status_pages/?${stringifiedParams}`
        : `/api/projects/${projectId}/uptime/status_pages/`
}

export const uptimeStatusPagesList = async (
    projectId: string,
    params?: UptimeStatusPagesListParams,
    options?: RequestInit
): Promise<PaginatedStatusPageDTOListApi> => {
    return apiMutator<PaginatedStatusPageDTOListApi>(getUptimeStatusPagesListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getUptimeStatusPagesCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/uptime/status_pages/`
}

/**
 * Create a draft status page with default title, color, and slug. Returns the new draft.
 */
export const uptimeStatusPagesCreate = async (projectId: string, options?: RequestInit): Promise<StatusPageDTOApi> => {
    return apiMutator<StatusPageDTOApi>(getUptimeStatusPagesCreateUrl(projectId), {
        ...options,
        method: 'POST',
    })
}

export const getUptimeStatusPagesRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/uptime/status_pages/${id}/`
}

export const uptimeStatusPagesRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<StatusPageDTOApi> => {
    return apiMutator<StatusPageDTOApi>(getUptimeStatusPagesRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getUptimeStatusPagesPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/uptime/status_pages/${id}/`
}

/**
 * Patch any subset of title, slug, monitor_ids on the page.
 */
export const uptimeStatusPagesPartialUpdate = async (
    projectId: string,
    id: string,
    patchedUpdateStatusPageApi?: PatchedUpdateStatusPageApi,
    options?: RequestInit
): Promise<StatusPageDTOApi> => {
    return apiMutator<StatusPageDTOApi>(getUptimeStatusPagesPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedUpdateStatusPageApi),
    })
}

export const getUptimeStatusPagesDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/uptime/status_pages/${id}/`
}

export const uptimeStatusPagesDestroy = async (projectId: string, id: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getUptimeStatusPagesDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getUptimeStatusPagesPublishCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/uptime/status_pages/${id}/publish/`
}

/**
 * Publish the status page. Makes it accessible at /status/<slug> without authentication.
 */
export const uptimeStatusPagesPublishCreate = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<StatusPageDTOApi> => {
    return apiMutator<StatusPageDTOApi>(getUptimeStatusPagesPublishCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
    })
}

export const getUptimeStatusPagesUnpublishCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/uptime/status_pages/${id}/unpublish/`
}

/**
 * Revert the status page to draft and remove public access.
 */
export const uptimeStatusPagesUnpublishCreate = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<StatusPageDTOApi> => {
    return apiMutator<StatusPageDTOApi>(getUptimeStatusPagesUnpublishCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
    })
}
