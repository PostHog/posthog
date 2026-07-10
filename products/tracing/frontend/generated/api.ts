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
    PaginatedTracingViewListApi,
    PatchedTracingViewApi,
    TracingSpansAttributesRetrieveParams,
    TracingSpansServiceNamesRetrieveParams,
    TracingSpansValuesRetrieveParams,
    TracingViewApi,
    TracingViewsListParams,
    _HasSpansResponseApi,
    _SymbolStatsRequestApi,
    _SymbolStatsResponseApi,
    _TracingAggregationRequestApi,
    _TracingAttributeBreakdownRequestApi,
    _TracingAttributeBreakdownResponseApi,
    _TracingAttributesResponseApi,
    _TracingCountRequestApi,
    _TracingCountResponseApi,
    _TracingDurationHistogramRequestApi,
    _TracingQueryRequestApi,
    _TracingSparklineRequestApi,
    _TracingTraceRequestApi,
    _TracingTreeRequestApi,
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
): Promise<_TracingAttributeBreakdownResponseApi> => {
    return apiMutator<_TracingAttributeBreakdownResponseApi>(getTracingSpansAttributeBreakdownCreateUrl(projectId), {
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
    _tracingDurationHistogramRequestApi: _TracingDurationHistogramRequestApi,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getTracingSpansDurationHistogramCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(_tracingDurationHistogramRequestApi),
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
    _tracingSparklineRequestApi: _TracingSparklineRequestApi,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getTracingSpansSparklineCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(_tracingSparklineRequestApi),
    })
}

export const getTracingSpansSymbolStatsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/tracing/spans/symbol-stats/`
}

export const tracingSpansSymbolStatsCreate = async (
    projectId: string,
    _symbolStatsRequestApi: _SymbolStatsRequestApi,
    options?: RequestInit
): Promise<_SymbolStatsResponseApi> => {
    return apiMutator<_SymbolStatsResponseApi>(getTracingSpansSymbolStatsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(_symbolStatsRequestApi),
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

export const getTracingViewsListUrl = (projectId: string, params?: TracingViewsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/tracing/views/?${stringifiedParams}`
        : `/api/projects/${projectId}/tracing/views/`
}

export const tracingViewsList = async (
    projectId: string,
    params?: TracingViewsListParams,
    options?: RequestInit
): Promise<PaginatedTracingViewListApi> => {
    return apiMutator<PaginatedTracingViewListApi>(getTracingViewsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getTracingViewsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/tracing/views/`
}

export const tracingViewsCreate = async (
    projectId: string,
    tracingViewApi: NonReadonly<TracingViewApi>,
    options?: RequestInit
): Promise<TracingViewApi> => {
    return apiMutator<TracingViewApi>(getTracingViewsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(tracingViewApi),
    })
}

export const getTracingViewsRetrieveUrl = (projectId: string, shortId: string) => {
    return `/api/projects/${projectId}/tracing/views/${shortId}/`
}

export const tracingViewsRetrieve = async (
    projectId: string,
    shortId: string,
    options?: RequestInit
): Promise<TracingViewApi> => {
    return apiMutator<TracingViewApi>(getTracingViewsRetrieveUrl(projectId, shortId), {
        ...options,
        method: 'GET',
    })
}

export const getTracingViewsUpdateUrl = (projectId: string, shortId: string) => {
    return `/api/projects/${projectId}/tracing/views/${shortId}/`
}

export const tracingViewsUpdate = async (
    projectId: string,
    shortId: string,
    tracingViewApi: NonReadonly<TracingViewApi>,
    options?: RequestInit
): Promise<TracingViewApi> => {
    return apiMutator<TracingViewApi>(getTracingViewsUpdateUrl(projectId, shortId), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(tracingViewApi),
    })
}

export const getTracingViewsPartialUpdateUrl = (projectId: string, shortId: string) => {
    return `/api/projects/${projectId}/tracing/views/${shortId}/`
}

export const tracingViewsPartialUpdate = async (
    projectId: string,
    shortId: string,
    patchedTracingViewApi?: NonReadonly<PatchedTracingViewApi>,
    options?: RequestInit
): Promise<TracingViewApi> => {
    return apiMutator<TracingViewApi>(getTracingViewsPartialUpdateUrl(projectId, shortId), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedTracingViewApi),
    })
}

export const getTracingViewsDestroyUrl = (projectId: string, shortId: string) => {
    return `/api/projects/${projectId}/tracing/views/${shortId}/`
}

export const tracingViewsDestroy = async (projectId: string, shortId: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getTracingViewsDestroyUrl(projectId, shortId), {
        ...options,
        method: 'DELETE',
    })
}
