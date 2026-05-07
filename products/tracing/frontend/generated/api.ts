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
    TracingSpansAttributesRetrieveParams,
    TracingSpansServiceNamesRetrieveParams,
    TracingSpansValuesRetrieveParams,
    _TracingQueryRequestApi,
    _TracingTraceRequestApi,
} from './api.schemas'

export const getTracingSpansAttributesRetrieveUrl = (
    projectId: string,
    params?: TracingSpansAttributesRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/tracing/spans/attributes/?${stringifiedParams}`
        : `/api/environments/${projectId}/tracing/spans/attributes/`
}

export const tracingSpansAttributesRetrieve = async (
    projectId: string,
    params?: TracingSpansAttributesRetrieveParams,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getTracingSpansAttributesRetrieveUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getTracingSpansQueryCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/tracing/spans/query/`
}

export const tracingSpansQueryCreate = async (
    projectId: string,
    _tracingQueryRequestApi: _TracingQueryRequestApi,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getTracingSpansQueryCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(_tracingQueryRequestApi),
    })
}

export const getTracingSpansServiceNamesRetrieveUrl = (
    projectId: string,
    params?: TracingSpansServiceNamesRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/tracing/spans/service-names/?${stringifiedParams}`
        : `/api/environments/${projectId}/tracing/spans/service-names/`
}

export const tracingSpansServiceNamesRetrieve = async (
    projectId: string,
    params?: TracingSpansServiceNamesRetrieveParams,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getTracingSpansServiceNamesRetrieveUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getTracingSpansSparklineCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/tracing/spans/sparkline/`
}

export const tracingSpansSparklineCreate = async (
    projectId: string,
    _tracingQueryRequestApi: _TracingQueryRequestApi,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getTracingSpansSparklineCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(_tracingQueryRequestApi),
    })
}

export const getTracingSpansTraceCreateUrl = (projectId: string, traceId: string) => {
    return `/api/environments/${projectId}/tracing/spans/trace/${traceId}/`
}

export const tracingSpansTraceCreate = async (
    projectId: string,
    traceId: string,
    _tracingTraceRequestApi: _TracingTraceRequestApi,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getTracingSpansTraceCreateUrl(projectId, traceId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(_tracingTraceRequestApi),
    })
}

export const getTracingSpansValuesRetrieveUrl = (projectId: string, params: TracingSpansValuesRetrieveParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : value.toString())
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/environments/${projectId}/tracing/spans/values/?${stringifiedParams}`
        : `/api/environments/${projectId}/tracing/spans/values/`
}

export const tracingSpansValuesRetrieve = async (
    projectId: string,
    params: TracingSpansValuesRetrieveParams,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getTracingSpansValuesRetrieveUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}
