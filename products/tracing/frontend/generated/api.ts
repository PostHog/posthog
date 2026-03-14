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

export const getTracingSpansRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/tracing/spans/`
}

export const tracingSpansRetrieve = async (projectId: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getTracingSpansRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getTracingSpansSparklineRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/tracing/spans/sparkline/`
}

export const tracingSpansSparklineRetrieve = async (projectId: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getTracingSpansSparklineRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getTracingSpansTraceRetrieveUrl = (projectId: string, traceId: string) => {
    return `/api/projects/${projectId}/tracing/spans/trace/${traceId}/`
}

export const tracingSpansTraceRetrieve = async (
    projectId: string,
    traceId: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getTracingSpansTraceRetrieveUrl(projectId, traceId), {
        ...options,
        method: 'GET',
    })
}
