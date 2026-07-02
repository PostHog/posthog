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
    CreateMonitorApi,
    MonitorDTOApi,
    MonitorSummaryDTOApi,
    OutageDTOApi,
    PatchedUpdateMonitorApi,
    PingDTOApi,
    UptimeMonitorsOutagesListParams,
} from './api.schemas'

export const getUptimeMonitorsListUrl = (projectId: string) => {
    return `/api/projects/${projectId}/uptime/monitors/`
}

export const uptimeMonitorsList = async (projectId: string, options?: RequestInit): Promise<MonitorDTOApi[]> => {
    return apiMutator<MonitorDTOApi[]>(getUptimeMonitorsListUrl(projectId), {
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
            normalizedParams.append(key, value === null ? 'null' : String(value))
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
): Promise<OutageDTOApi[]> => {
    return apiMutator<OutageDTOApi[]>(getUptimeMonitorsOutagesListUrl(projectId, id, params), {
        ...options,
        method: 'GET',
    })
}

export const getUptimeMonitorsPingsListUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/uptime/monitors/${id}/pings/`
}

/**
 * The 50 most recent pings for this monitor, newest first.
 */
export const uptimeMonitorsPingsList = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<PingDTOApi[]> => {
    return apiMutator<PingDTOApi[]>(getUptimeMonitorsPingsListUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getUptimeMonitorsSummaryListUrl = (projectId: string) => {
    return `/api/projects/${projectId}/uptime/monitors/summary/`
}

/**
 * Per-monitor status, 90-day uptime, 24h latency, last ping, and 90 daily status buckets.
 */
export const uptimeMonitorsSummaryList = async (
    projectId: string,
    options?: RequestInit
): Promise<MonitorSummaryDTOApi[]> => {
    return apiMutator<MonitorSummaryDTOApi[]>(getUptimeMonitorsSummaryListUrl(projectId), {
        ...options,
        method: 'GET',
    })
}
