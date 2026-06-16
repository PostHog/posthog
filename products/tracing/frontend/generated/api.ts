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
    _HasSpansResponseApi,
    _TracingAggregationRequestApi,
    _TracingAttributeBreakdownRequestApi,
    _TracingAttributesResponseApi,
    _TracingCountRequestApi,
    _TracingCountResponseApi,
    _TracingQueryRequestApi,
    _TracingTimeseriesRequestApi,
    _TracingTraceRequestApi,
    _TracingTreeRequestApi,
} from './api.schemas'

export const getTracingSpansAggregateCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/tracing/spans/aggregate/`
}

export const tracingSpansAggregateCreate = async (
    projectId: string,
    _tracingAggregationRequestApi: _TracingAggregationRequestApi,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getTracingSpansAggregateCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(_tracingAggregationRequestApi),
    })
}

export const getTracingSpansAttributeBreakdownCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/tracing/spans/attribute-breakdown/`
}

export const tracingSpansAttributeBreakdownCreate = async (
    projectId: string,
    _tracingAttributeBreakdownRequestApi: _TracingAttributeBreakdownRequestApi,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getTracingSpansAttributeBreakdownCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(_tracingAttributeBreakdownRequestApi),
    })
}

export const getTracingSpansAttributesRetrieveUrl = (
    projectId: string,
    params?: TracingSpansAttributesRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/tracing/spans/attributes/?${stringifiedParams}`
        : `/api/projects/${projectId}/tracing/spans/attributes/`
}

export const tracingSpansAttributesRetrieve = async (
    projectId: string,
    params?: TracingSpansAttributesRetrieveParams,
    options?: RequestInit
): Promise<_TracingAttributesResponseApi> => {
    return apiMutator<_TracingAttributesResponseApi>(getTracingSpansAttributesRetrieveUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getTracingSpansCountCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/tracing/spans/count/`
}

export const tracingSpansCountCreate = async (
    projectId: string,
    _tracingCountRequestApi: _TracingCountRequestApi,
    options?: RequestInit
): Promise<_TracingCountResponseApi> => {
    return apiMutator<_TracingCountResponseApi>(getTracingSpansCountCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(_tracingCountRequestApi),
    })
}

export const getTracingSpansDurationHistogramCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/tracing/spans/duration-histogram/`
}

export const tracingSpansDurationHistogramCreate = async (
    projectId: string,
    _tracingTimeseriesRequestApi: _TracingTimeseriesRequestApi,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getTracingSpansDurationHistogramCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(_tracingTimeseriesRequestApi),
    })
}

export const getTracingSpansHasSpansRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/tracing/spans/has_spans/`
}

export const tracingSpansHasSpansRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<_HasSpansResponseApi> => {
    return apiMutator<_HasSpansResponseApi>(getTracingSpansHasSpansRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getTracingSpansQueryCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/tracing/spans/query/`
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
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/tracing/spans/service-names/?${stringifiedParams}`
        : `/api/projects/${projectId}/tracing/spans/service-names/`
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
    return `/api/projects/${projectId}/tracing/spans/sparkline/`
}

export const tracingSpansSparklineCreate = async (
    projectId: string,
    _tracingTimeseriesRequestApi: _TracingTimeseriesRequestApi,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getTracingSpansSparklineCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(_tracingTimeseriesRequestApi),
    })
}

export const getTracingSpansTraceCreateUrl = (projectId: string, traceId: string) => {
    return `/api/projects/${projectId}/tracing/spans/trace/${traceId}/`
}

export const tracingSpansTraceCreate = async (
    projectId: string,
    traceId: string,
    _tracingTraceRequestApi?: _TracingTraceRequestApi,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getTracingSpansTraceCreateUrl(projectId, traceId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(_tracingTraceRequestApi),
    })
}

export const getTracingSpansTreeCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/tracing/spans/tree/`
}

export const tracingSpansTreeCreate = async (
    projectId: string,
    _tracingTreeRequestApi: _TracingTreeRequestApi,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getTracingSpansTreeCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(_tracingTreeRequestApi),
    })
}

export const getTracingSpansValuesRetrieveUrl = (projectId: string, params: TracingSpansValuesRetrieveParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/tracing/spans/values/?${stringifiedParams}`
        : `/api/projects/${projectId}/tracing/spans/values/`
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
