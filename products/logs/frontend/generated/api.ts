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
    ExplainRequestApi,
    LogsAlertConfigurationApi,
    LogsAlertCreateDestinationApi,
    LogsAlertDeleteDestinationApi,
    LogsAlertDestinationResponseApi,
    LogsAlertSimulateRequestApi,
    LogsAlertSimulateResponseApi,
    LogsAlertsEventsListParams,
    LogsAlertsListParams,
    LogsAttributesRetrieveParams,
    LogsExportCreate201,
    LogsHasLogsRetrieve200,
    LogsValuesRetrieveParams,
    LogsViewApi,
    LogsViewsListParams,
    PaginatedLogsAlertConfigurationListApi,
    PaginatedLogsAlertEventListApi,
    PaginatedLogsViewListApi,
    PaginatedPluginLogEntryListApi,
    PatchedLogsAlertConfigurationApi,
    PatchedLogsViewApi,
    PluginConfigsLogsListParams,
    _LogsAttributesResponseApi,
    _LogsCountRangesRequestApi,
    _LogsCountRangesResponseApi,
    _LogsCountRequestApi,
    _LogsCountResponseApi,
    _LogsQueryRequestApi,
    _LogsQueryResponseApi,
    _LogsServicesRequestApi,
    _LogsServicesResponseApi,
    _LogsSparklineRequestApi,
    _LogsSparklineResponseApi,
    _LogsValuesResponseApi,
} from './api.schemas'

// https://stackoverflow.com/questions/49579094/typescript-conditional-types-filter-out-readonly-properties-pick-only-requir/49579497#49579497
type IfEquals<X, Y, A = X, B = never> = (<T>() => T extends X ? 1 : 2) extends <T>() => T extends Y ? 1 : 2 ? A : B

type WritableKeys<T> = {
    [P in keyof T]-?: IfEquals<{ [Q in P]: T[P] }, { -readonly [Q in P]: T[P] }, P>
}[keyof T]

type UnionToIntersection<U> = (U extends any ? (k: U) => void : never) extends (k: infer I) => void ? I : never
type DistributeReadOnlyOverUnions<T> = T extends any ? NonReadonly<T> : never

type Writable<T> = Pick<T, WritableKeys<T>>
type NonReadonly<T> = [T] extends [UnionToIntersection<T>]
    ? {
          [P in keyof Writable<T>]: T[P] extends object ? NonReadonly<NonNullable<T[P]>> : T[P]
      }
    : DistributeReadOnlyOverUnions<T>

/**
 * Explain a log entry using AI.

POST /api/environments/:id/logs/explainLogWithAI/
 */
export const getLogsExplainLogWithAICreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/logs/explainLogWithAI/`
}

export const logsExplainLogWithAICreate = async (
    projectId: string,
    explainRequestApi: ExplainRequestApi,
    options?: RequestInit
): Promise<ExplainRequestApi> => {
    return apiMutator<ExplainRequestApi>(getLogsExplainLogWithAICreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(explainRequestApi),
    })
}

export const getLogsViewsListUrl = (projectId: string, params?: LogsViewsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/logs/views/?${stringifiedParams}`
        : `/api/environments/${projectId}/logs/views/`
}

export const logsViewsList = async (
    projectId: string,
    params?: LogsViewsListParams,
    options?: RequestInit
): Promise<PaginatedLogsViewListApi> => {
    return apiMutator<PaginatedLogsViewListApi>(getLogsViewsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getLogsViewsCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/logs/views/`
}

export const logsViewsCreate = async (
    projectId: string,
    logsViewApi: NonReadonly<LogsViewApi>,
    options?: RequestInit
): Promise<LogsViewApi> => {
    return apiMutator<LogsViewApi>(getLogsViewsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(logsViewApi),
    })
}

export const getLogsViewsRetrieveUrl = (projectId: string, shortId: string) => {
    return `/api/environments/${projectId}/logs/views/${shortId}/`
}

export const logsViewsRetrieve = async (
    projectId: string,
    shortId: string,
    options?: RequestInit
): Promise<LogsViewApi> => {
    return apiMutator<LogsViewApi>(getLogsViewsRetrieveUrl(projectId, shortId), {
        ...options,
        method: 'GET',
    })
}

export const getLogsViewsUpdateUrl = (projectId: string, shortId: string) => {
    return `/api/environments/${projectId}/logs/views/${shortId}/`
}

export const logsViewsUpdate = async (
    projectId: string,
    shortId: string,
    logsViewApi: NonReadonly<LogsViewApi>,
    options?: RequestInit
): Promise<LogsViewApi> => {
    return apiMutator<LogsViewApi>(getLogsViewsUpdateUrl(projectId, shortId), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(logsViewApi),
    })
}

export const getLogsViewsPartialUpdateUrl = (projectId: string, shortId: string) => {
    return `/api/environments/${projectId}/logs/views/${shortId}/`
}

export const logsViewsPartialUpdate = async (
    projectId: string,
    shortId: string,
    patchedLogsViewApi: NonReadonly<PatchedLogsViewApi>,
    options?: RequestInit
): Promise<LogsViewApi> => {
    return apiMutator<LogsViewApi>(getLogsViewsPartialUpdateUrl(projectId, shortId), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedLogsViewApi),
    })
}

export const getLogsViewsDestroyUrl = (projectId: string, shortId: string) => {
    return `/api/environments/${projectId}/logs/views/${shortId}/`
}

export const logsViewsDestroy = async (projectId: string, shortId: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getLogsViewsDestroyUrl(projectId, shortId), {
        ...options,
        method: 'DELETE',
    })
}

export const getDomainsScimLogsRetrieveUrl = (organizationId: string, id: string) => {
    return `/api/organizations/${organizationId}/domains/${id}/scim/logs/`
}

export const domainsScimLogsRetrieve = async (
    organizationId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getDomainsScimLogsRetrieveUrl(organizationId, id), {
        ...options,
        method: 'GET',
    })
}

export const getLogsAlertsListUrl = (projectId: string, params?: LogsAlertsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/logs/alerts/?${stringifiedParams}`
        : `/api/projects/${projectId}/logs/alerts/`
}

export const logsAlertsList = async (
    projectId: string,
    params?: LogsAlertsListParams,
    options?: RequestInit
): Promise<PaginatedLogsAlertConfigurationListApi> => {
    return apiMutator<PaginatedLogsAlertConfigurationListApi>(getLogsAlertsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getLogsAlertsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/logs/alerts/`
}

export const logsAlertsCreate = async (
    projectId: string,
    logsAlertConfigurationApi: NonReadonly<LogsAlertConfigurationApi>,
    options?: RequestInit
): Promise<LogsAlertConfigurationApi> => {
    return apiMutator<LogsAlertConfigurationApi>(getLogsAlertsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(logsAlertConfigurationApi),
    })
}

export const getLogsAlertsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/logs/alerts/${id}/`
}

export const logsAlertsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<LogsAlertConfigurationApi> => {
    return apiMutator<LogsAlertConfigurationApi>(getLogsAlertsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getLogsAlertsUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/logs/alerts/${id}/`
}

export const logsAlertsUpdate = async (
    projectId: string,
    id: string,
    logsAlertConfigurationApi: NonReadonly<LogsAlertConfigurationApi>,
    options?: RequestInit
): Promise<LogsAlertConfigurationApi> => {
    return apiMutator<LogsAlertConfigurationApi>(getLogsAlertsUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(logsAlertConfigurationApi),
    })
}

export const getLogsAlertsPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/logs/alerts/${id}/`
}

export const logsAlertsPartialUpdate = async (
    projectId: string,
    id: string,
    patchedLogsAlertConfigurationApi: NonReadonly<PatchedLogsAlertConfigurationApi>,
    options?: RequestInit
): Promise<LogsAlertConfigurationApi> => {
    return apiMutator<LogsAlertConfigurationApi>(getLogsAlertsPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedLogsAlertConfigurationApi),
    })
}

export const getLogsAlertsDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/logs/alerts/${id}/`
}

export const logsAlertsDestroy = async (projectId: string, id: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getLogsAlertsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

/**
 * Create a notification destination for this alert. One HogFunction is created per alert event kind (firing, resolved, ...) atomically.
 */
export const getLogsAlertsDestinationsCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/logs/alerts/${id}/destinations/`
}

export const logsAlertsDestinationsCreate = async (
    projectId: string,
    id: string,
    logsAlertCreateDestinationApi: LogsAlertCreateDestinationApi,
    options?: RequestInit
): Promise<LogsAlertDestinationResponseApi> => {
    return apiMutator<LogsAlertDestinationResponseApi>(getLogsAlertsDestinationsCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(logsAlertCreateDestinationApi),
    })
}

/**
 * Delete a notification destination by deleting its HogFunction group atomically.
 */
export const getLogsAlertsDestinationsDeleteCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/logs/alerts/${id}/destinations/delete/`
}

export const logsAlertsDestinationsDeleteCreate = async (
    projectId: string,
    id: string,
    logsAlertDeleteDestinationApi: LogsAlertDeleteDestinationApi,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getLogsAlertsDestinationsDeleteCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(logsAlertDeleteDestinationApi),
    })
}

/**
 * Paginated event history for this alert, newest first. Returns state transitions, errored checks, and user-initiated control-plane rows (reset, enable/disable, snooze/unsnooze, threshold change) — quiet no-op check rows (where state didn't change and there was no error) are filtered out since only the last 10 are kept and they carry no forensic value. Optional `?kind=...` narrows to a single kind.
 */
export const getLogsAlertsEventsListUrl = (projectId: string, id: string, params?: LogsAlertsEventsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/logs/alerts/${id}/events/?${stringifiedParams}`
        : `/api/projects/${projectId}/logs/alerts/${id}/events/`
}

export const logsAlertsEventsList = async (
    projectId: string,
    id: string,
    params?: LogsAlertsEventsListParams,
    options?: RequestInit
): Promise<PaginatedLogsAlertEventListApi> => {
    return apiMutator<PaginatedLogsAlertEventListApi>(getLogsAlertsEventsListUrl(projectId, id, params), {
        ...options,
        method: 'GET',
    })
}

/**
 * Reset a broken alert. Clears the consecutive-failure counter and schedules an immediate recheck.
 */
export const getLogsAlertsResetCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/logs/alerts/${id}/reset/`
}

export const logsAlertsResetCreate = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<LogsAlertConfigurationApi> => {
    return apiMutator<LogsAlertConfigurationApi>(getLogsAlertsResetCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
    })
}

/**
 * Simulate a logs alert on historical data using the full state machine. Read-only — no alert check records are created.
 */
export const getLogsAlertsSimulateCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/logs/alerts/simulate/`
}

export const logsAlertsSimulateCreate = async (
    projectId: string,
    logsAlertSimulateRequestApi: LogsAlertSimulateRequestApi,
    options?: RequestInit
): Promise<LogsAlertSimulateResponseApi> => {
    return apiMutator<LogsAlertSimulateResponseApi>(getLogsAlertsSimulateCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(logsAlertSimulateRequestApi),
    })
}

export const getLogsAttributesRetrieveUrl = (projectId: string, params?: LogsAttributesRetrieveParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/logs/attributes/?${stringifiedParams}`
        : `/api/projects/${projectId}/logs/attributes/`
}

export const logsAttributesRetrieve = async (
    projectId: string,
    params?: LogsAttributesRetrieveParams,
    options?: RequestInit
): Promise<_LogsAttributesResponseApi> => {
    return apiMutator<_LogsAttributesResponseApi>(getLogsAttributesRetrieveUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getLogsCountCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/logs/count/`
}

export const logsCountCreate = async (
    projectId: string,
    _logsCountRequestApi: _LogsCountRequestApi,
    options?: RequestInit
): Promise<_LogsCountResponseApi> => {
    return apiMutator<_LogsCountResponseApi>(getLogsCountCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(_logsCountRequestApi),
    })
}

export const getLogsCountRangesCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/logs/count-ranges/`
}

export const logsCountRangesCreate = async (
    projectId: string,
    _logsCountRangesRequestApi: _LogsCountRangesRequestApi,
    options?: RequestInit
): Promise<_LogsCountRangesResponseApi> => {
    return apiMutator<_LogsCountRangesResponseApi>(getLogsCountRangesCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(_logsCountRangesRequestApi),
    })
}

export const getLogsExportCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/logs/export/`
}

export const logsExportCreate = async (projectId: string, options?: RequestInit): Promise<LogsExportCreate201> => {
    return apiMutator<LogsExportCreate201>(getLogsExportCreateUrl(projectId), {
        ...options,
        method: 'POST',
    })
}

export const getLogsHasLogsRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/logs/has_logs/`
}

export const logsHasLogsRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<LogsHasLogsRetrieve200> => {
    return apiMutator<LogsHasLogsRetrieve200>(getLogsHasLogsRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getLogsQueryCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/logs/query/`
}

export const logsQueryCreate = async (
    projectId: string,
    _logsQueryRequestApi: _LogsQueryRequestApi,
    options?: RequestInit
): Promise<_LogsQueryResponseApi> => {
    return apiMutator<_LogsQueryResponseApi>(getLogsQueryCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(_logsQueryRequestApi),
    })
}

export const getLogsServicesCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/logs/services/`
}

export const logsServicesCreate = async (
    projectId: string,
    _logsServicesRequestApi: _LogsServicesRequestApi,
    options?: RequestInit
): Promise<_LogsServicesResponseApi> => {
    return apiMutator<_LogsServicesResponseApi>(getLogsServicesCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(_logsServicesRequestApi),
    })
}

export const getLogsSparklineCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/logs/sparkline/`
}

export const logsSparklineCreate = async (
    projectId: string,
    _logsSparklineRequestApi: _LogsSparklineRequestApi,
    options?: RequestInit
): Promise<_LogsSparklineResponseApi> => {
    return apiMutator<_LogsSparklineResponseApi>(getLogsSparklineCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(_logsSparklineRequestApi),
    })
}

export const getLogsValuesRetrieveUrl = (projectId: string, params: LogsValuesRetrieveParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/logs/values/?${stringifiedParams}`
        : `/api/projects/${projectId}/logs/values/`
}

export const logsValuesRetrieve = async (
    projectId: string,
    params: LogsValuesRetrieveParams,
    options?: RequestInit
): Promise<_LogsValuesResponseApi> => {
    return apiMutator<_LogsValuesResponseApi>(getLogsValuesRetrieveUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getPluginConfigsLogsListUrl = (
    projectId: string,
    pluginConfigId: number,
    params?: PluginConfigsLogsListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/plugin_configs/${pluginConfigId}/logs/?${stringifiedParams}`
        : `/api/projects/${projectId}/plugin_configs/${pluginConfigId}/logs/`
}

export const pluginConfigsLogsList = async (
    projectId: string,
    pluginConfigId: number,
    params?: PluginConfigsLogsListParams,
    options?: RequestInit
): Promise<PaginatedPluginLogEntryListApi> => {
    return apiMutator<PaginatedPluginLogEntryListApi>(getPluginConfigsLogsListUrl(projectId, pluginConfigId, params), {
        ...options,
        method: 'GET',
    })
}

/**
 * Fetch the logs for a task run. Returns JSONL formatted log entries.
 * @summary Get task run logs
 */
export const getTasksRunsLogsRetrieveUrl = (projectId: string, taskId: string, id: string) => {
    return `/api/projects/${projectId}/tasks/${taskId}/runs/${id}/logs/`
}

export const tasksRunsLogsRetrieve = async (
    projectId: string,
    taskId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getTasksRunsLogsRetrieveUrl(projectId, taskId, id), {
        ...options,
        method: 'GET',
    })
}
