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
    CreateUptimeMonitorInputApi,
    PaginatedUptimeMonitorListApi,
    PatchedUpdateUptimeMonitorInputApi,
    UptimeMonitorApi,
    UptimeMonitorsListParams,
} from './api.schemas'

export const getUptimeMonitorsListUrl = (projectId: string, params?: UptimeMonitorsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/uptime_monitors/?${stringifiedParams}`
        : `/api/projects/${projectId}/uptime_monitors/`
}

/**
 * List the project's uptime monitors, newest first.
 */
export const uptimeMonitorsList = async (
    projectId: string,
    params?: UptimeMonitorsListParams,
    options?: RequestInit
): Promise<PaginatedUptimeMonitorListApi> => {
    return apiMutator<PaginatedUptimeMonitorListApi>(getUptimeMonitorsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getUptimeMonitorsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/uptime_monitors/`
}

/**
 * Create an uptime monitor.
 */
export const uptimeMonitorsCreate = async (
    projectId: string,
    createUptimeMonitorInputApi: CreateUptimeMonitorInputApi,
    options?: RequestInit
): Promise<UptimeMonitorApi> => {
    return apiMutator<UptimeMonitorApi>(getUptimeMonitorsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(createUptimeMonitorInputApi),
    })
}

export const getUptimeMonitorsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/uptime_monitors/${id}/`
}

/**
 * Get an uptime monitor.
 */
export const uptimeMonitorsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<UptimeMonitorApi> => {
    return apiMutator<UptimeMonitorApi>(getUptimeMonitorsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getUptimeMonitorsPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/uptime_monitors/${id}/`
}

/**
 * Change some fields of an uptime monitor.
 */
export const uptimeMonitorsPartialUpdate = async (
    projectId: string,
    id: string,
    patchedUpdateUptimeMonitorInputApi?: PatchedUpdateUptimeMonitorInputApi,
    options?: RequestInit
): Promise<UptimeMonitorApi> => {
    return apiMutator<UptimeMonitorApi>(getUptimeMonitorsPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedUpdateUptimeMonitorInputApi),
    })
}

export const getUptimeMonitorsDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/uptime_monitors/${id}/`
}

/**
 * Delete an uptime monitor.
 */
export const uptimeMonitorsDestroy = async (projectId: string, id: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getUptimeMonitorsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}
