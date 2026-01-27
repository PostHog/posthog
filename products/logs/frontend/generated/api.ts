/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import { apiMutator } from '../../../../frontend/src/lib/api-orval-mutator'
import type {
    EnvironmentsPluginConfigsLogsListParams,
    ExplainRequestApi,
    PaginatedPluginLogEntryListApi,
    PluginConfigsLogsListParams,
} from './api.schemas'

export type environmentsHogFlowTemplatesLogsRetrieveResponse200 = {
    data: void
    status: 200
}

export type environmentsHogFlowTemplatesLogsRetrieveResponseSuccess =
    environmentsHogFlowTemplatesLogsRetrieveResponse200 & {
        headers: Headers
    }
export type environmentsHogFlowTemplatesLogsRetrieveResponse = environmentsHogFlowTemplatesLogsRetrieveResponseSuccess

export const getEnvironmentsHogFlowTemplatesLogsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/hog_flow_templates/${id}/logs/`
}

export const environmentsHogFlowTemplatesLogsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<environmentsHogFlowTemplatesLogsRetrieveResponse> => {
    return apiMutator<environmentsHogFlowTemplatesLogsRetrieveResponse>(
        getEnvironmentsHogFlowTemplatesLogsRetrieveUrl(projectId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}

export type environmentsHogFlowsLogsRetrieveResponse200 = {
    data: void
    status: 200
}

export type environmentsHogFlowsLogsRetrieveResponseSuccess = environmentsHogFlowsLogsRetrieveResponse200 & {
    headers: Headers
}
export type environmentsHogFlowsLogsRetrieveResponse = environmentsHogFlowsLogsRetrieveResponseSuccess

export const getEnvironmentsHogFlowsLogsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/hog_flows/${id}/logs/`
}

export const environmentsHogFlowsLogsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<environmentsHogFlowsLogsRetrieveResponse> => {
    return apiMutator<environmentsHogFlowsLogsRetrieveResponse>(getEnvironmentsHogFlowsLogsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export type environmentsHogFunctionsLogsRetrieveResponse200 = {
    data: void
    status: 200
}

export type environmentsHogFunctionsLogsRetrieveResponseSuccess = environmentsHogFunctionsLogsRetrieveResponse200 & {
    headers: Headers
}
export type environmentsHogFunctionsLogsRetrieveResponse = environmentsHogFunctionsLogsRetrieveResponseSuccess

export const getEnvironmentsHogFunctionsLogsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/hog_functions/${id}/logs/`
}

export const environmentsHogFunctionsLogsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<environmentsHogFunctionsLogsRetrieveResponse> => {
    return apiMutator<environmentsHogFunctionsLogsRetrieveResponse>(
        getEnvironmentsHogFunctionsLogsRetrieveUrl(projectId, id),
        {
            ...options,
            method: 'GET',
        }
    )
}

export type environmentsLogsAttributesRetrieveResponse200 = {
    data: void
    status: 200
}

export type environmentsLogsAttributesRetrieveResponseSuccess = environmentsLogsAttributesRetrieveResponse200 & {
    headers: Headers
}
export type environmentsLogsAttributesRetrieveResponse = environmentsLogsAttributesRetrieveResponseSuccess

export const getEnvironmentsLogsAttributesRetrieveUrl = (projectId: string) => {
    return `/api/environments/${projectId}/logs/attributes/`
}

export const environmentsLogsAttributesRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<environmentsLogsAttributesRetrieveResponse> => {
    return apiMutator<environmentsLogsAttributesRetrieveResponse>(getEnvironmentsLogsAttributesRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

/**
 * Explain a log entry using AI.

POST /api/environments/:id/logs/explainLogWithAI/
 */
export type environmentsLogsExplainLogWithAICreateResponse201 = {
    data: ExplainRequestApi
    status: 201
}

export type environmentsLogsExplainLogWithAICreateResponseSuccess =
    environmentsLogsExplainLogWithAICreateResponse201 & {
        headers: Headers
    }
export type environmentsLogsExplainLogWithAICreateResponse = environmentsLogsExplainLogWithAICreateResponseSuccess

export const getEnvironmentsLogsExplainLogWithAICreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/logs/explainLogWithAI/`
}

export const environmentsLogsExplainLogWithAICreate = async (
    projectId: string,
    explainRequestApi: ExplainRequestApi,
    options?: RequestInit
): Promise<environmentsLogsExplainLogWithAICreateResponse> => {
    return apiMutator<environmentsLogsExplainLogWithAICreateResponse>(
        getEnvironmentsLogsExplainLogWithAICreateUrl(projectId),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(explainRequestApi),
        }
    )
}

export type environmentsLogsHasLogsRetrieveResponse200 = {
    data: void
    status: 200
}

export type environmentsLogsHasLogsRetrieveResponseSuccess = environmentsLogsHasLogsRetrieveResponse200 & {
    headers: Headers
}
export type environmentsLogsHasLogsRetrieveResponse = environmentsLogsHasLogsRetrieveResponseSuccess

export const getEnvironmentsLogsHasLogsRetrieveUrl = (projectId: string) => {
    return `/api/environments/${projectId}/logs/has_logs/`
}

export const environmentsLogsHasLogsRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<environmentsLogsHasLogsRetrieveResponse> => {
    return apiMutator<environmentsLogsHasLogsRetrieveResponse>(getEnvironmentsLogsHasLogsRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export type environmentsLogsQueryCreateResponse200 = {
    data: void
    status: 200
}

export type environmentsLogsQueryCreateResponseSuccess = environmentsLogsQueryCreateResponse200 & {
    headers: Headers
}
export type environmentsLogsQueryCreateResponse = environmentsLogsQueryCreateResponseSuccess

export const getEnvironmentsLogsQueryCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/logs/query/`
}

export const environmentsLogsQueryCreate = async (
    projectId: string,
    options?: RequestInit
): Promise<environmentsLogsQueryCreateResponse> => {
    return apiMutator<environmentsLogsQueryCreateResponse>(getEnvironmentsLogsQueryCreateUrl(projectId), {
        ...options,
        method: 'POST',
    })
}

export type environmentsLogsSparklineCreateResponse200 = {
    data: void
    status: 200
}

export type environmentsLogsSparklineCreateResponseSuccess = environmentsLogsSparklineCreateResponse200 & {
    headers: Headers
}
export type environmentsLogsSparklineCreateResponse = environmentsLogsSparklineCreateResponseSuccess

export const getEnvironmentsLogsSparklineCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/logs/sparkline/`
}

export const environmentsLogsSparklineCreate = async (
    projectId: string,
    options?: RequestInit
): Promise<environmentsLogsSparklineCreateResponse> => {
    return apiMutator<environmentsLogsSparklineCreateResponse>(getEnvironmentsLogsSparklineCreateUrl(projectId), {
        ...options,
        method: 'POST',
    })
}

export type environmentsLogsValuesRetrieveResponse200 = {
    data: void
    status: 200
}

export type environmentsLogsValuesRetrieveResponseSuccess = environmentsLogsValuesRetrieveResponse200 & {
    headers: Headers
}
export type environmentsLogsValuesRetrieveResponse = environmentsLogsValuesRetrieveResponseSuccess

export const getEnvironmentsLogsValuesRetrieveUrl = (projectId: string) => {
    return `/api/environments/${projectId}/logs/values/`
}

export const environmentsLogsValuesRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<environmentsLogsValuesRetrieveResponse> => {
    return apiMutator<environmentsLogsValuesRetrieveResponse>(getEnvironmentsLogsValuesRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export type environmentsPluginConfigsLogsListResponse200 = {
    data: PaginatedPluginLogEntryListApi
    status: 200
}

export type environmentsPluginConfigsLogsListResponseSuccess = environmentsPluginConfigsLogsListResponse200 & {
    headers: Headers
}
export type environmentsPluginConfigsLogsListResponse = environmentsPluginConfigsLogsListResponseSuccess

export const getEnvironmentsPluginConfigsLogsListUrl = (
    projectId: string,
    pluginConfigId: string,
    params?: EnvironmentsPluginConfigsLogsListParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/plugin_configs/${pluginConfigId}/logs/?${stringifiedParams}`
        : `/api/environments/${projectId}/plugin_configs/${pluginConfigId}/logs/`
}

export const environmentsPluginConfigsLogsList = async (
    projectId: string,
    pluginConfigId: string,
    params?: EnvironmentsPluginConfigsLogsListParams,
    options?: RequestInit
): Promise<environmentsPluginConfigsLogsListResponse> => {
    return apiMutator<environmentsPluginConfigsLogsListResponse>(
        getEnvironmentsPluginConfigsLogsListUrl(projectId, pluginConfigId, params),
        {
            ...options,
            method: 'GET',
        }
    )
}

export type hogFlowTemplatesLogsRetrieveResponse200 = {
    data: void
    status: 200
}

export type hogFlowTemplatesLogsRetrieveResponseSuccess = hogFlowTemplatesLogsRetrieveResponse200 & {
    headers: Headers
}
export type hogFlowTemplatesLogsRetrieveResponse = hogFlowTemplatesLogsRetrieveResponseSuccess

export const getHogFlowTemplatesLogsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/hog_flow_templates/${id}/logs/`
}

export const hogFlowTemplatesLogsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<hogFlowTemplatesLogsRetrieveResponse> => {
    return apiMutator<hogFlowTemplatesLogsRetrieveResponse>(getHogFlowTemplatesLogsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export type hogFlowsLogsRetrieveResponse200 = {
    data: void
    status: 200
}

export type hogFlowsLogsRetrieveResponseSuccess = hogFlowsLogsRetrieveResponse200 & {
    headers: Headers
}
export type hogFlowsLogsRetrieveResponse = hogFlowsLogsRetrieveResponseSuccess

export const getHogFlowsLogsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/hog_flows/${id}/logs/`
}

export const hogFlowsLogsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<hogFlowsLogsRetrieveResponse> => {
    return apiMutator<hogFlowsLogsRetrieveResponse>(getHogFlowsLogsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export type hogFunctionsLogsRetrieveResponse200 = {
    data: void
    status: 200
}

export type hogFunctionsLogsRetrieveResponseSuccess = hogFunctionsLogsRetrieveResponse200 & {
    headers: Headers
}
export type hogFunctionsLogsRetrieveResponse = hogFunctionsLogsRetrieveResponseSuccess

export const getHogFunctionsLogsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/hog_functions/${id}/logs/`
}

export const hogFunctionsLogsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<hogFunctionsLogsRetrieveResponse> => {
    return apiMutator<hogFunctionsLogsRetrieveResponse>(getHogFunctionsLogsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export type logsAttributesRetrieveResponse200 = {
    data: void
    status: 200
}

export type logsAttributesRetrieveResponseSuccess = logsAttributesRetrieveResponse200 & {
    headers: Headers
}
export type logsAttributesRetrieveResponse = logsAttributesRetrieveResponseSuccess

export const getLogsAttributesRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/logs/attributes/`
}

export const logsAttributesRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<logsAttributesRetrieveResponse> => {
    return apiMutator<logsAttributesRetrieveResponse>(getLogsAttributesRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export type logsHasLogsRetrieveResponse200 = {
    data: void
    status: 200
}

export type logsHasLogsRetrieveResponseSuccess = logsHasLogsRetrieveResponse200 & {
    headers: Headers
}
export type logsHasLogsRetrieveResponse = logsHasLogsRetrieveResponseSuccess

export const getLogsHasLogsRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/logs/has_logs/`
}

export const logsHasLogsRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<logsHasLogsRetrieveResponse> => {
    return apiMutator<logsHasLogsRetrieveResponse>(getLogsHasLogsRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export type logsQueryCreateResponse200 = {
    data: void
    status: 200
}

export type logsQueryCreateResponseSuccess = logsQueryCreateResponse200 & {
    headers: Headers
}
export type logsQueryCreateResponse = logsQueryCreateResponseSuccess

export const getLogsQueryCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/logs/query/`
}

export const logsQueryCreate = async (projectId: string, options?: RequestInit): Promise<logsQueryCreateResponse> => {
    return apiMutator<logsQueryCreateResponse>(getLogsQueryCreateUrl(projectId), {
        ...options,
        method: 'POST',
    })
}

export type logsSparklineCreateResponse200 = {
    data: void
    status: 200
}

export type logsSparklineCreateResponseSuccess = logsSparklineCreateResponse200 & {
    headers: Headers
}
export type logsSparklineCreateResponse = logsSparklineCreateResponseSuccess

export const getLogsSparklineCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/logs/sparkline/`
}

export const logsSparklineCreate = async (
    projectId: string,
    options?: RequestInit
): Promise<logsSparklineCreateResponse> => {
    return apiMutator<logsSparklineCreateResponse>(getLogsSparklineCreateUrl(projectId), {
        ...options,
        method: 'POST',
    })
}

export type logsValuesRetrieveResponse200 = {
    data: void
    status: 200
}

export type logsValuesRetrieveResponseSuccess = logsValuesRetrieveResponse200 & {
    headers: Headers
}
export type logsValuesRetrieveResponse = logsValuesRetrieveResponseSuccess

export const getLogsValuesRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/logs/values/`
}

export const logsValuesRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<logsValuesRetrieveResponse> => {
    return apiMutator<logsValuesRetrieveResponse>(getLogsValuesRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export type pluginConfigsLogsListResponse200 = {
    data: PaginatedPluginLogEntryListApi
    status: 200
}

export type pluginConfigsLogsListResponseSuccess = pluginConfigsLogsListResponse200 & {
    headers: Headers
}
export type pluginConfigsLogsListResponse = pluginConfigsLogsListResponseSuccess

export const getPluginConfigsLogsListUrl = (
    projectId: string,
    pluginConfigId: string,
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
    pluginConfigId: string,
    params?: PluginConfigsLogsListParams,
    options?: RequestInit
): Promise<pluginConfigsLogsListResponse> => {
    return apiMutator<pluginConfigsLogsListResponse>(getPluginConfigsLogsListUrl(projectId, pluginConfigId, params), {
        ...options,
        method: 'GET',
    })
}

/**
 * Fetch the logs for a task run. Returns JSONL formatted log entries.
 * @summary Get task run logs
 */
export type tasksRunsLogsRetrieveResponse200 = {
    data: void
    status: 200
}

export type tasksRunsLogsRetrieveResponse404 = {
    data: void
    status: 404
}

export type tasksRunsLogsRetrieveResponseSuccess = tasksRunsLogsRetrieveResponse200 & {
    headers: Headers
}
export type tasksRunsLogsRetrieveResponseError = tasksRunsLogsRetrieveResponse404 & {
    headers: Headers
}

export type tasksRunsLogsRetrieveResponse = tasksRunsLogsRetrieveResponseSuccess | tasksRunsLogsRetrieveResponseError

export const getTasksRunsLogsRetrieveUrl = (projectId: string, taskId: string, id: string) => {
    return `/api/projects/${projectId}/tasks/${taskId}/runs/${id}/logs/`
}

export const tasksRunsLogsRetrieve = async (
    projectId: string,
    taskId: string,
    id: string,
    options?: RequestInit
): Promise<tasksRunsLogsRetrieveResponse> => {
    return apiMutator<tasksRunsLogsRetrieveResponse>(getTasksRunsLogsRetrieveUrl(projectId, taskId, id), {
        ...options,
        method: 'GET',
    })
}
