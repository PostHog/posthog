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

export const getHogFlowTemplatesLogsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/hog_flow_templates/${id}/logs/`
}

export const hogFlowTemplatesLogsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getHogFlowTemplatesLogsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getHogFlowsLogsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/hog_flows/${id}/logs/`
}

export const hogFlowsLogsRetrieve = async (projectId: string, id: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getHogFlowsLogsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getHogFunctionsLogsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/environments/${projectId}/hog_functions/${id}/logs/`
}

export const hogFunctionsLogsRetrieve = async (projectId: string, id: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getHogFunctionsLogsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getLogsAttributesRetrieveUrl = (projectId: string) => {
    return `/api/environments/${projectId}/logs/attributes/`
}

export const logsAttributesRetrieve = async (projectId: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getLogsAttributesRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

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

export const getLogsHasLogsRetrieveUrl = (projectId: string) => {
    return `/api/environments/${projectId}/logs/has_logs/`
}

export const logsHasLogsRetrieve = async (projectId: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getLogsHasLogsRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getLogsQueryCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/logs/query/`
}

export const logsQueryCreate = async (projectId: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getLogsQueryCreateUrl(projectId), {
        ...options,
        method: 'POST',
    })
}

export const getLogsSparklineCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/logs/sparkline/`
}

export const logsSparklineCreate = async (projectId: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getLogsSparklineCreateUrl(projectId), {
        ...options,
        method: 'POST',
    })
}

export const getLogsValuesRetrieveUrl = (projectId: string) => {
    return `/api/environments/${projectId}/logs/values/`
}

export const logsValuesRetrieve = async (projectId: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getLogsValuesRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

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
): Promise<PaginatedPluginLogEntryListApi> => {
    return apiMutator<PaginatedPluginLogEntryListApi>(getPluginConfigsLogsListUrl(projectId, pluginConfigId, params), {
        ...options,
        method: 'GET',
    })
}

export const getHogFlowTemplatesLogsRetrieve2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/hog_flow_templates/${id}/logs/`
}

export const hogFlowTemplatesLogsRetrieve2 = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getHogFlowTemplatesLogsRetrieve2Url(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getHogFlowsLogsRetrieve2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/hog_flows/${id}/logs/`
}

export const hogFlowsLogsRetrieve2 = async (projectId: string, id: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getHogFlowsLogsRetrieve2Url(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getHogFunctionsLogsRetrieve2Url = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/hog_functions/${id}/logs/`
}

export const hogFunctionsLogsRetrieve2 = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getHogFunctionsLogsRetrieve2Url(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getLogsAttributesRetrieve2Url = (projectId: string) => {
    return `/api/projects/${projectId}/logs/attributes/`
}

export const logsAttributesRetrieve2 = async (projectId: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getLogsAttributesRetrieve2Url(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getLogsHasLogsRetrieve2Url = (projectId: string) => {
    return `/api/projects/${projectId}/logs/has_logs/`
}

export const logsHasLogsRetrieve2 = async (projectId: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getLogsHasLogsRetrieve2Url(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getLogsQueryCreate2Url = (projectId: string) => {
    return `/api/projects/${projectId}/logs/query/`
}

export const logsQueryCreate2 = async (projectId: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getLogsQueryCreate2Url(projectId), {
        ...options,
        method: 'POST',
    })
}

export const getLogsSparklineCreate2Url = (projectId: string) => {
    return `/api/projects/${projectId}/logs/sparkline/`
}

export const logsSparklineCreate2 = async (projectId: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getLogsSparklineCreate2Url(projectId), {
        ...options,
        method: 'POST',
    })
}

export const getLogsValuesRetrieve2Url = (projectId: string) => {
    return `/api/projects/${projectId}/logs/values/`
}

export const logsValuesRetrieve2 = async (projectId: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getLogsValuesRetrieve2Url(projectId), {
        ...options,
        method: 'GET',
    })
}

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
): Promise<PaginatedPluginLogEntryListApi> => {
    return apiMutator<PaginatedPluginLogEntryListApi>(getPluginConfigsLogsList2Url(projectId, pluginConfigId, params), {
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
