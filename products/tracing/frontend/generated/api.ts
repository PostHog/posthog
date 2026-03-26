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

export const getTracingSpansQueryCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/tracing/spans/query/`
}

export const tracingSpansQueryCreate = async (projectId: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getTracingSpansQueryCreateUrl(projectId), {
        ...options,
        method: 'POST',
    })
}

export const getTracingSpansTraceCreateUrl = (projectId: string, traceId: string) => {
    return `/api/projects/${projectId}/tracing/spans/trace/${traceId}/`
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
