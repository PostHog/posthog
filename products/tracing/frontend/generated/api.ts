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

export const getTracingSpansAttributesRetrieveUrl = (projectId: string) => {
    return `/api/environments/${projectId}/tracing/spans/attributes/`
}

export const tracingSpansAttributesRetrieve = async (projectId: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getTracingSpansAttributesRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getTracingSpansQueryCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/tracing/spans/query/`
}

export const tracingSpansQueryCreate = async (projectId: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getTracingSpansQueryCreateUrl(projectId), {
        ...options,
        method: 'POST',
    })
}

export const getTracingSpansServiceNamesRetrieveUrl = (projectId: string) => {
    return `/api/environments/${projectId}/tracing/spans/service-names/`
}

export const tracingSpansServiceNamesRetrieve = async (projectId: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getTracingSpansServiceNamesRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getTracingSpansSparklineCreateUrl = (projectId: string) => {
    return `/api/environments/${projectId}/tracing/spans/sparkline/`
}

export const tracingSpansSparklineCreate = async (projectId: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getTracingSpansSparklineCreateUrl(projectId), {
        ...options,
        method: 'POST',
    })
}

export const getTracingSpansTraceCreateUrl = (projectId: string, traceId: string) => {
    return `/api/environments/${projectId}/tracing/spans/trace/${traceId}/`
}

export const tracingSpansTraceCreate = async (
    projectId: string,
    traceId: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getTracingSpansTraceCreateUrl(projectId, traceId), {
        ...options,
        method: 'POST',
    })
}

export const getTracingSpansValuesRetrieveUrl = (projectId: string) => {
    return `/api/environments/${projectId}/tracing/spans/values/`
}

export const tracingSpansValuesRetrieve = async (projectId: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getTracingSpansValuesRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}
