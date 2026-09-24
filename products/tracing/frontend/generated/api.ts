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
    LogsRetentionRuleNameSuggestionApi,
    LogsRetentionRuleReorderApi,
    LogsRetentionRuleSuggestNameApi,
    PaginatedTracesRetentionRuleListApi,
    PaginatedTracingViewListApi,
    PatchedTeamTracingConfigApi,
    PatchedTracesRetentionRuleApi,
    PatchedTracingViewApi,
    TeamTracingConfigApi,
    TracesRetentionRuleApi,
    TracingRetentionRulesListParams,
    TracingRetentionRulesReorderCreateParams,
    TracingSpansAttributesRetrieveParams,
    TracingSpansServiceNamesRetrieveParams,
    TracingSpansValuesRetrieveParams,
    TracingViewApi,
    TracingViewsListParams,
    _HasSpansResponseApi,
    _SymbolStatsRequestApi,
    _SymbolStatsResponseApi,
    _TracingAggregationRequestApi,
    _TracingAggregationResponseApi,
    _TracingAttributeBreakdownRequestApi,
    _TracingAttributeBreakdownResponseApi,
    _TracingAttributesResponseApi,
    _TracingCountRequestApi,
    _TracingCountResponseApi,
    _TracingDurationHistogramRequestApi,
    _TracingDurationHistogramResponseApi,
    _TracingErrorCountsRequestApi,
    _TracingErrorCountsResponseApi,
    _TracingImpactRequestApi,
    _TracingImpactResponseApi,
    _TracingLatencyHeatmapRequestApi,
    _TracingLatencyHeatmapResponseApi,
    _TracingQueryRequestApi,
    _TracingQueryResponseApi,
    _TracingServiceNamesResponseApi,
    _TracingSparklineRequestApi,
    _TracingSparklineResponseApi,
    _TracingTraceRequestApi,
    _TracingTraceResponseApi,
    _TracingTreeRequestApi,
    _TracingTreeResponseApi,
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

export const getOrganizationsProjectsTracingConfigRetrieveUrl = (organizationId: string, id: number) => {
    return `/api/organizations/${organizationId}/projects/${id}/tracing_config/`
}

/**
 * Manage tracing product configuration for this project's canonical environment.
 * Members can read; writing requires project admin, matching the admin-only
 * settings UI. Mirrors the env-router action so /api/projects/:id/tracing_config/
 * resolves alongside the legacy /api/environments/:id/tracing_config/ alias.
 */
export const organizationsProjectsTracingConfigRetrieve = async (
    organizationId: string,
    id: number,
    options?: RequestInit
): Promise<TeamTracingConfigApi> => {
    return apiMutator<TeamTracingConfigApi>(getOrganizationsProjectsTracingConfigRetrieveUrl(organizationId, id), {
        ...options,
        method: 'GET',
    })
}

export const getOrganizationsProjectsTracingConfigPartialUpdateUrl = (organizationId: string, id: number) => {
    return `/api/organizations/${organizationId}/projects/${id}/tracing_config/`
}

/**
 * Manage tracing product configuration for this project's canonical environment.
 * Members can read; writing requires project admin, matching the admin-only
 * settings UI. Mirrors the env-router action so /api/projects/:id/tracing_config/
 * resolves alongside the legacy /api/environments/:id/tracing_config/ alias.
 */
export const organizationsProjectsTracingConfigPartialUpdate = async (
    organizationId: string,
    id: number,
    patchedTeamTracingConfigApi?: NonReadonly<PatchedTeamTracingConfigApi>,
    options?: RequestInit
): Promise<TeamTracingConfigApi> => {
    return apiMutator<TeamTracingConfigApi>(getOrganizationsProjectsTracingConfigPartialUpdateUrl(organizationId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedTeamTracingConfigApi),
    })
}

export const getTracingRetentionRulesListUrl = (projectId: string, params?: TracingRetentionRulesListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/tracing/retention_rules/?${stringifiedParams}`
        : `/api/projects/${projectId}/tracing/retention_rules/`
}

/**
 * Span retention rules.
 *
 * Shares the logs implementation over its own model. Only the model, the access-control scope and
 * the feature flag differ.
 */
export const tracingRetentionRulesList = async (
    projectId: string,
    params?: TracingRetentionRulesListParams,
    options?: RequestInit
): Promise<PaginatedTracesRetentionRuleListApi> => {
    return apiMutator<PaginatedTracesRetentionRuleListApi>(getTracingRetentionRulesListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getTracingRetentionRulesCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/tracing/retention_rules/`
}

/**
 * Span retention rules.
 *
 * Shares the logs implementation over its own model. Only the model, the access-control scope and
 * the feature flag differ.
 */
export const tracingRetentionRulesCreate = async (
    projectId: string,
    tracesRetentionRuleApi: NonReadonly<TracesRetentionRuleApi>,
    options?: RequestInit
): Promise<TracesRetentionRuleApi> => {
    return apiMutator<TracesRetentionRuleApi>(getTracingRetentionRulesCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(tracesRetentionRuleApi),
    })
}

export const getTracingRetentionRulesRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/tracing/retention_rules/${id}/`
}

/**
 * Span retention rules.
 *
 * Shares the logs implementation over its own model. Only the model, the access-control scope and
 * the feature flag differ.
 */
export const tracingRetentionRulesRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<TracesRetentionRuleApi> => {
    return apiMutator<TracesRetentionRuleApi>(getTracingRetentionRulesRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getTracingRetentionRulesUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/tracing/retention_rules/${id}/`
}

/**
 * Span retention rules.
 *
 * Shares the logs implementation over its own model. Only the model, the access-control scope and
 * the feature flag differ.
 */
export const tracingRetentionRulesUpdate = async (
    projectId: string,
    id: string,
    tracesRetentionRuleApi: NonReadonly<TracesRetentionRuleApi>,
    options?: RequestInit
): Promise<TracesRetentionRuleApi> => {
    return apiMutator<TracesRetentionRuleApi>(getTracingRetentionRulesUpdateUrl(projectId, id), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(tracesRetentionRuleApi),
    })
}

export const getTracingRetentionRulesPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/tracing/retention_rules/${id}/`
}

/**
 * Span retention rules.
 *
 * Shares the logs implementation over its own model. Only the model, the access-control scope and
 * the feature flag differ.
 */
export const tracingRetentionRulesPartialUpdate = async (
    projectId: string,
    id: string,
    patchedTracesRetentionRuleApi?: NonReadonly<PatchedTracesRetentionRuleApi>,
    options?: RequestInit
): Promise<TracesRetentionRuleApi> => {
    return apiMutator<TracesRetentionRuleApi>(getTracingRetentionRulesPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedTracesRetentionRuleApi),
    })
}

export const getTracingRetentionRulesDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/tracing/retention_rules/${id}/`
}

/**
 * Span retention rules.
 *
 * Shares the logs implementation over its own model. Only the model, the access-control scope and
 * the feature flag differ.
 */
export const tracingRetentionRulesDestroy = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getTracingRetentionRulesDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getTracingRetentionRulesReorderCreateUrl = (
    projectId: string,
    params?: TracingRetentionRulesReorderCreateParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/tracing/retention_rules/reorder/?${stringifiedParams}`
        : `/api/projects/${projectId}/tracing/retention_rules/reorder/`
}

/**
 * Atomically reassign priorities so the given ID order maps to ascending priorities (0..n-1).
 */
export const tracingRetentionRulesReorderCreate = async (
    projectId: string,
    logsRetentionRuleReorderApi: LogsRetentionRuleReorderApi,
    params?: TracingRetentionRulesReorderCreateParams,
    options?: RequestInit
): Promise<PaginatedTracesRetentionRuleListApi> => {
    return apiMutator<PaginatedTracesRetentionRuleListApi>(
        getTracingRetentionRulesReorderCreateUrl(projectId, params),
        {
            ...options,
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...options?.headers },
            body: JSON.stringify(logsRetentionRuleReorderApi),
        }
    )
}

export const getTracingRetentionRulesSuggestNameCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/tracing/retention_rules/suggest_name/`
}

/**
 * Suggest a human-readable name for a retention rule from its retention tier and filter group. Used by the create form as an auto-suggest; nothing is persisted. Returns an empty name when a suggestion can't be generated.
 */
export const tracingRetentionRulesSuggestNameCreate = async (
    projectId: string,
    logsRetentionRuleSuggestNameApi: LogsRetentionRuleSuggestNameApi,
    options?: RequestInit
): Promise<LogsRetentionRuleNameSuggestionApi> => {
    return apiMutator<LogsRetentionRuleNameSuggestionApi>(getTracingRetentionRulesSuggestNameCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(logsRetentionRuleSuggestNameApi),
    })
}

export const getTracingSpansAggregateCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/tracing/spans/aggregate/`
}

export const tracingSpansAggregateCreate = async (
    projectId: string,
    _tracingAggregationRequestApi: _TracingAggregationRequestApi,
    options?: RequestInit
): Promise<_TracingAggregationResponseApi> => {
    return apiMutator<_TracingAggregationResponseApi>(getTracingSpansAggregateCreateUrl(projectId), {
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
): Promise<_TracingDurationHistogramResponseApi> => {
    return apiMutator<_TracingDurationHistogramResponseApi>(getTracingSpansDurationHistogramCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(_tracingDurationHistogramRequestApi),
    })
}

export const getTracingSpansErrorCountsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/tracing/spans/error-counts/`
}

/**
 * Count the exceptions the spans in view hit, by trace, by span and by session, for the
 * span list's error badges.
 *
 * A caller asks about the id kinds it has, and each kind is a separate lookup.
 */
export const tracingSpansErrorCountsCreate = async (
    projectId: string,
    _tracingErrorCountsRequestApi: _TracingErrorCountsRequestApi,
    options?: RequestInit
): Promise<_TracingErrorCountsResponseApi> => {
    return apiMutator<_TracingErrorCountsResponseApi>(getTracingSpansErrorCountsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(_tracingErrorCountsRequestApi),
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

export const getTracingSpansImpactCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/tracing/spans/impact/`
}

export const tracingSpansImpactCreate = async (
    projectId: string,
    _tracingImpactRequestApi: _TracingImpactRequestApi,
    options?: RequestInit
): Promise<_TracingImpactResponseApi> => {
    return apiMutator<_TracingImpactResponseApi>(getTracingSpansImpactCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(_tracingImpactRequestApi),
    })
}

export const getTracingSpansLatencyHeatmapCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/tracing/spans/latency-heatmap/`
}

export const tracingSpansLatencyHeatmapCreate = async (
    projectId: string,
    _tracingLatencyHeatmapRequestApi: _TracingLatencyHeatmapRequestApi,
    options?: RequestInit
): Promise<_TracingLatencyHeatmapResponseApi> => {
    return apiMutator<_TracingLatencyHeatmapResponseApi>(getTracingSpansLatencyHeatmapCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(_tracingLatencyHeatmapRequestApi),
    })
}

export const getTracingSpansQueryCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/tracing/spans/query/`
}

export const tracingSpansQueryCreate = async (
    projectId: string,
    _tracingQueryRequestApi: _TracingQueryRequestApi,
    options?: RequestInit
): Promise<_TracingQueryResponseApi> => {
    return apiMutator<_TracingQueryResponseApi>(getTracingSpansQueryCreateUrl(projectId), {
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
): Promise<_TracingServiceNamesResponseApi> => {
    return apiMutator<_TracingServiceNamesResponseApi>(getTracingSpansServiceNamesRetrieveUrl(projectId, params), {
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
): Promise<_TracingSparklineResponseApi> => {
    return apiMutator<_TracingSparklineResponseApi>(getTracingSpansSparklineCreateUrl(projectId), {
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
): Promise<_TracingTraceResponseApi> => {
    return apiMutator<_TracingTraceResponseApi>(getTracingSpansTraceCreateUrl(projectId, traceId), {
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
): Promise<_TracingTreeResponseApi> => {
    return apiMutator<_TracingTreeResponseApi>(getTracingSpansTreeCreateUrl(projectId), {
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
