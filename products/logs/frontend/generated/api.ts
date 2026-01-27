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
    ExplainRequestApi,
    PaginatedPluginLogEntryListApi,
    PluginConfigsLogsList2Params,
    PluginConfigsLogsListParams,
} from './api.schemas'

export type hogFlowTemplatesLogsRetrieveResponse200 = {
    data: void
    status: 200
}

export type hogFlowTemplatesLogsRetrieveResponseSuccess = hogFlowTemplatesLogsRetrieveResponse200 & {
    headers: Headers
}
export type hogFlowTemplatesLogsRetrieveResponse = hogFlowTemplatesLogsRetrieveResponseSuccess

export const getHogFlowTemplatesLogsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/hog_flow_templates/${id}/logs/`
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
    return `/api/environments/${projectId}/hog_flows/${id}/logs/`
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
    return `/api/environments/${projectId}/hog_functions/${id}/logs/`
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
    return `/api/environments/${projectId}/logs/attributes/`
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

/**
 * Explain a log entry using AI.

POST /api/environments/:id/logs/explainLogWithAI/
 */
export type logsExplainLogWithAICreateResponse201 = {
    data: ExplainRequestApi
    status: 201
}

export type logsExplainLogWithAICreateResponseSuccess = logsExplainLogWithAICreateResponse201 & {
    headers: Headers
}
export type logsExplainLogWithAICreateResponse = logsExplainLogWithAICreateResponseSuccess

export const getLogsExplainLogWithAICreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/logs/explainLogWithAI/`
}

export const logsExplainLogWithAICreate = async (
    projectId: string,
    explainRequestApi: ExplainRequestApi,
    options?: RequestInit
): Promise<logsExplainLogWithAICreateResponse> => {
    return apiMutator<logsExplainLogWithAICreateResponse>(getLogsExplainLogWithAICreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(explainRequestApi),
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
    return `/api/environments/${projectId}/logs/has_logs/`
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
    return `/api/environments/${projectId}/logs/query/`
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
    return `/api/environments/${projectId}/logs/sparkline/`
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
    return `/api/environments/${projectId}/logs/values/`
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
        ? `/api/environments/${projectId}/plugin_configs/${pluginConfigId}/logs/?${stringifiedParams}`
        : `/api/environments/${projectId}/plugin_configs/${pluginConfigId}/logs/`
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

export type hogFlowTemplatesLogsRetrieve2Response200 = {
    data: void
    status: 200
}

export type hogFlowTemplatesLogsRetrieve2ResponseSuccess = hogFlowTemplatesLogsRetrieve2Response200 & {
    headers: Headers
}
export type hogFlowTemplatesLogsRetrieve2Response = hogFlowTemplatesLogsRetrieve2ResponseSuccess

export const getHogFlowTemplatesLogsRetrieve2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/hog_flow_templates/${id}/logs/`
}

export const hogFlowTemplatesLogsRetrieve2 = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<hogFlowTemplatesLogsRetrieve2Response> => {
    return apiMutator<hogFlowTemplatesLogsRetrieve2Response>(getHogFlowTemplatesLogsRetrieve2Url(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export type hogFlowsLogsRetrieve2Response200 = {
    data: void
    status: 200
}

export type hogFlowsLogsRetrieve2ResponseSuccess = hogFlowsLogsRetrieve2Response200 & {
    headers: Headers
}
export type hogFlowsLogsRetrieve2Response = hogFlowsLogsRetrieve2ResponseSuccess

export const getHogFlowsLogsRetrieve2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/hog_flows/${id}/logs/`
}

export const hogFlowsLogsRetrieve2 = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<hogFlowsLogsRetrieve2Response> => {
    return apiMutator<hogFlowsLogsRetrieve2Response>(getHogFlowsLogsRetrieve2Url(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export type hogFunctionsLogsRetrieve2Response200 = {
    data: void
    status: 200
}

export type hogFunctionsLogsRetrieve2ResponseSuccess = hogFunctionsLogsRetrieve2Response200 & {
    headers: Headers
}
export type hogFunctionsLogsRetrieve2Response = hogFunctionsLogsRetrieve2ResponseSuccess

export const getHogFunctionsLogsRetrieve2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/hog_functions/${id}/logs/`
}

export const hogFunctionsLogsRetrieve2 = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<hogFunctionsLogsRetrieve2Response> => {
    return apiMutator<hogFunctionsLogsRetrieve2Response>(getHogFunctionsLogsRetrieve2Url(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export type logsAttributesRetrieve2Response200 = {
    data: void
    status: 200
}

export type logsAttributesRetrieve2ResponseSuccess = logsAttributesRetrieve2Response200 & {
    headers: Headers
}
export type logsAttributesRetrieve2Response = logsAttributesRetrieve2ResponseSuccess

export const getLogsAttributesRetrieve2Url = (projectId: string) => {
    return `/api/projects/${projectId}/logs/attributes/`
}

export const logsAttributesRetrieve2 = async (
    projectId: string,
    options?: RequestInit
): Promise<logsAttributesRetrieve2Response> => {
    return apiMutator<logsAttributesRetrieve2Response>(getLogsAttributesRetrieve2Url(projectId), {
        ...options,
        method: 'GET',
    })
}

export type logsHasLogsRetrieve2Response200 = {
    data: void
    status: 200
}

export type logsHasLogsRetrieve2ResponseSuccess = logsHasLogsRetrieve2Response200 & {
    headers: Headers
}
export type logsHasLogsRetrieve2Response = logsHasLogsRetrieve2ResponseSuccess

export const getLogsHasLogsRetrieve2Url = (projectId: string) => {
    return `/api/projects/${projectId}/logs/has_logs/`
}

export const logsHasLogsRetrieve2 = async (
    projectId: string,
    options?: RequestInit
): Promise<logsHasLogsRetrieve2Response> => {
    return apiMutator<logsHasLogsRetrieve2Response>(getLogsHasLogsRetrieve2Url(projectId), {
        ...options,
        method: 'GET',
    })
}

export type logsQueryCreate2Response200 = {
    data: void
    status: 200
}

export type logsQueryCreate2ResponseSuccess = logsQueryCreate2Response200 & {
    headers: Headers
}
export type logsQueryCreate2Response = logsQueryCreate2ResponseSuccess

export const getLogsQueryCreate2Url = (projectId: string) => {
    return `/api/projects/${projectId}/logs/query/`
}

export const logsQueryCreate2 = async (projectId: string, options?: RequestInit): Promise<logsQueryCreate2Response> => {
    return apiMutator<logsQueryCreate2Response>(getLogsQueryCreate2Url(projectId), {
        ...options,
        method: 'POST',
    })
}

export type logsSparklineCreate2Response200 = {
    data: void
    status: 200
}

export type logsSparklineCreate2ResponseSuccess = logsSparklineCreate2Response200 & {
    headers: Headers
}
export type logsSparklineCreate2Response = logsSparklineCreate2ResponseSuccess

export const getLogsSparklineCreate2Url = (projectId: string) => {
    return `/api/projects/${projectId}/logs/sparkline/`
}

export const logsSparklineCreate2 = async (
    projectId: string,
    options?: RequestInit
): Promise<logsSparklineCreate2Response> => {
    return apiMutator<logsSparklineCreate2Response>(getLogsSparklineCreate2Url(projectId), {
        ...options,
        method: 'POST',
    })
}

export type logsValuesRetrieve2Response200 = {
    data: void
    status: 200
}

export type logsValuesRetrieve2ResponseSuccess = logsValuesRetrieve2Response200 & {
    headers: Headers
}
export type logsValuesRetrieve2Response = logsValuesRetrieve2ResponseSuccess

export const getLogsValuesRetrieve2Url = (projectId: string) => {
    return `/api/projects/${projectId}/logs/values/`
}

export const logsValuesRetrieve2 = async (
    projectId: string,
    options?: RequestInit
): Promise<logsValuesRetrieve2Response> => {
    return apiMutator<logsValuesRetrieve2Response>(getLogsValuesRetrieve2Url(projectId), {
        ...options,
        method: 'GET',
    })
}

export type pluginConfigsLogsList2Response200 = {
    data: PaginatedPluginLogEntryListApi
    status: 200
}

export type pluginConfigsLogsList2ResponseSuccess = pluginConfigsLogsList2Response200 & {
    headers: Headers
}
export type pluginConfigsLogsList2Response = pluginConfigsLogsList2ResponseSuccess

export const getPluginConfigsLogsList2Url = (
    projectId: string,
    pluginConfigId: string,
    params?: PluginConfigsLogsList2Params
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

export const pluginConfigsLogsList2 = async (
    projectId: string,
    pluginConfigId: string,
    params?: PluginConfigsLogsList2Params,
    options?: RequestInit
): Promise<pluginConfigsLogsList2Response> => {
    return apiMutator<pluginConfigsLogsList2Response>(getPluginConfigsLogsList2Url(projectId, pluginConfigId, params), {
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
