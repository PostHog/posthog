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
    AppMetricsResponseApi,
    AppMetricsTotalsResponseApi,
    MetricsAttributeValuesRetrieveParams,
    MetricsAttributesRetrieveParams,
    MetricsValuesRetrieveParams,
    MetricsViewApi,
    MetricsViewsListParams,
    PaginatedMetricsViewListApi,
    PatchedMetricsViewApi,
    _HasMetricsResponseApi,
    _MetricAnomalyReportApi,
    _MetricAnomalyRequestApi,
    _MetricAttributeKeysResponseApi,
    _MetricAttributeValuesResponseApi,
    _MetricNamesResponseApi,
    _MetricQueryRequestApi,
    _MetricQueryResponseApi,
    _MetricSamplesRequestApi,
    _MetricSamplesResponseApi,
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

export const getEventFilterMetricsRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/event_filter/metrics/`
}

/**
 * Single event filter per team.
 * GET  /event_filter/ — returns the config (or null if not yet created)
 * POST /event_filter/ — creates or updates the config (upsert)
 * GET  /event_filter/metrics/ — time-series metrics
 * GET  /event_filter/metrics/totals/ — aggregate totals
 */
export const eventFilterMetricsRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<AppMetricsResponseApi> => {
    return apiMutator<AppMetricsResponseApi>(getEventFilterMetricsRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getEventFilterMetricsTotalsRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/event_filter/metrics/totals/`
}

/**
 * Single event filter per team.
 * GET  /event_filter/ — returns the config (or null if not yet created)
 * POST /event_filter/ — creates or updates the config (upsert)
 * GET  /event_filter/metrics/ — time-series metrics
 * GET  /event_filter/metrics/totals/ — aggregate totals
 */
export const eventFilterMetricsTotalsRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<AppMetricsTotalsResponseApi> => {
    return apiMutator<AppMetricsTotalsResponseApi>(getEventFilterMetricsTotalsRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getMetricsAttributeValuesRetrieveUrl = (
    projectId: string,
    params: MetricsAttributeValuesRetrieveParams
) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/metrics/attribute_values/?${stringifiedParams}`
        : `/api/projects/${projectId}/metrics/attribute_values/`
}

/**
 * Observed values for one metric attribute key, most frequent first.
 * Backs the filter bar's value autocomplete.
 */
export const metricsAttributeValuesRetrieve = async (
    projectId: string,
    params: MetricsAttributeValuesRetrieveParams,
    options?: RequestInit
): Promise<_MetricAttributeValuesResponseApi> => {
    return apiMutator<_MetricAttributeValuesResponseApi>(getMetricsAttributeValuesRetrieveUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getMetricsAttributesRetrieveUrl = (projectId: string, params?: MetricsAttributesRetrieveParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/metrics/attributes/?${stringifiedParams}`
        : `/api/projects/${projectId}/metrics/attributes/`
}

/**
 * Distinct attribute keys seen on the team's metrics (datapoint and
 * resource attributes merged), most frequent first. Backs the filter
 * bar's key autocomplete.
 */
export const metricsAttributesRetrieve = async (
    projectId: string,
    params?: MetricsAttributesRetrieveParams,
    options?: RequestInit
): Promise<_MetricAttributeKeysResponseApi> => {
    return apiMutator<_MetricAttributeKeysResponseApi>(getMetricsAttributesRetrieveUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getMetricsCharacterizeCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/metrics/characterize/`
}

/**
 * Characterize a metric anomaly: compare an anomaly window against a
 * baseline, find the onset, and rank which label values moved.
 */
export const metricsCharacterizeCreate = async (
    projectId: string,
    _metricAnomalyRequestApi: _MetricAnomalyRequestApi,
    options?: RequestInit
): Promise<_MetricAnomalyReportApi> => {
    return apiMutator<_MetricAnomalyReportApi>(getMetricsCharacterizeCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(_metricAnomalyRequestApi),
    })
}

export const getMetricsHasMetricsRetrieveUrl = (projectId: string) => {
    return `/api/projects/${projectId}/metrics/has_metrics/`
}

export const metricsHasMetricsRetrieve = async (
    projectId: string,
    options?: RequestInit
): Promise<_HasMetricsResponseApi> => {
    return apiMutator<_HasMetricsResponseApi>(getMetricsHasMetricsRetrieveUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getMetricsQueryCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/metrics/query/`
}

export const metricsQueryCreate = async (
    projectId: string,
    _metricQueryRequestApi: _MetricQueryRequestApi,
    options?: RequestInit
): Promise<_MetricQueryResponseApi> => {
    return apiMutator<_MetricQueryResponseApi>(getMetricsQueryCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(_metricQueryRequestApi),
    })
}

export const getMetricsSamplesCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/metrics/samples/`
}

/**
 * Raw individual emissions for a metric (the events model), newest
 * first — backs the Samples view and the metric->trace pivot.
 */
export const metricsSamplesCreate = async (
    projectId: string,
    _metricSamplesRequestApi: _MetricSamplesRequestApi,
    options?: RequestInit
): Promise<_MetricSamplesResponseApi> => {
    return apiMutator<_MetricSamplesResponseApi>(getMetricsSamplesCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(_metricSamplesRequestApi),
    })
}

export const getMetricsValuesRetrieveUrl = (projectId: string, params?: MetricsValuesRetrieveParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/metrics/values/?${stringifiedParams}`
        : `/api/projects/${projectId}/metrics/values/`
}

/**
 * Distinct metric names for the team. Backs the picker UI.
 */
export const metricsValuesRetrieve = async (
    projectId: string,
    params?: MetricsValuesRetrieveParams,
    options?: RequestInit
): Promise<_MetricNamesResponseApi> => {
    return apiMutator<_MetricNamesResponseApi>(getMetricsValuesRetrieveUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getMetricsViewsListUrl = (projectId: string, params?: MetricsViewsListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/metrics/views/?${stringifiedParams}`
        : `/api/projects/${projectId}/metrics/views/`
}

export const metricsViewsList = async (
    projectId: string,
    params?: MetricsViewsListParams,
    options?: RequestInit
): Promise<PaginatedMetricsViewListApi> => {
    return apiMutator<PaginatedMetricsViewListApi>(getMetricsViewsListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getMetricsViewsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/metrics/views/`
}

export const metricsViewsCreate = async (
    projectId: string,
    metricsViewApi: NonReadonly<MetricsViewApi>,
    options?: RequestInit
): Promise<MetricsViewApi> => {
    return apiMutator<MetricsViewApi>(getMetricsViewsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(metricsViewApi),
    })
}

export const getMetricsViewsRetrieveUrl = (projectId: string, shortId: string) => {
    return `/api/projects/${projectId}/metrics/views/${shortId}/`
}

export const metricsViewsRetrieve = async (
    projectId: string,
    shortId: string,
    options?: RequestInit
): Promise<MetricsViewApi> => {
    return apiMutator<MetricsViewApi>(getMetricsViewsRetrieveUrl(projectId, shortId), {
        ...options,
        method: 'GET',
    })
}

export const getMetricsViewsUpdateUrl = (projectId: string, shortId: string) => {
    return `/api/projects/${projectId}/metrics/views/${shortId}/`
}

export const metricsViewsUpdate = async (
    projectId: string,
    shortId: string,
    metricsViewApi: NonReadonly<MetricsViewApi>,
    options?: RequestInit
): Promise<MetricsViewApi> => {
    return apiMutator<MetricsViewApi>(getMetricsViewsUpdateUrl(projectId, shortId), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(metricsViewApi),
    })
}

export const getMetricsViewsPartialUpdateUrl = (projectId: string, shortId: string) => {
    return `/api/projects/${projectId}/metrics/views/${shortId}/`
}

export const metricsViewsPartialUpdate = async (
    projectId: string,
    shortId: string,
    patchedMetricsViewApi?: NonReadonly<PatchedMetricsViewApi>,
    options?: RequestInit
): Promise<MetricsViewApi> => {
    return apiMutator<MetricsViewApi>(getMetricsViewsPartialUpdateUrl(projectId, shortId), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedMetricsViewApi),
    })
}

export const getMetricsViewsDestroyUrl = (projectId: string, shortId: string) => {
    return `/api/projects/${projectId}/metrics/views/${shortId}/`
}

export const metricsViewsDestroy = async (projectId: string, shortId: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getMetricsViewsDestroyUrl(projectId, shortId), {
        ...options,
        method: 'DELETE',
    })
}
