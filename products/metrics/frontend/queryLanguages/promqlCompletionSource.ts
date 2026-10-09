import {
    metricsAttributeValuesRetrieve,
    metricsAttributesRetrieve,
    metricsNamesRetrieve,
} from 'products/metrics/frontend/generated/api'

import type { PromQLCompletionSource, PromQLMetricName } from './promqlCompletion'

const CACHE_TTL_MS = 60_000
const LIMIT = 100
// The most names the API returns in one request.
const NAMES_PAGE = 1000
// Every series carries the service name, and Snuffle exposes it under this label.
const SERVICE_LABEL = 'service_name'
// Snuffle's virtual series of histogram buckets: `<name>_bucket` with an `le` label.
const BUCKET_SUFFIX = '_bucket'

/** Suggestions from the metrics API, cached briefly so each keystroke does not refetch the same list. */
export function createMetricsPromQLCompletionSource(projectId: string): PromQLCompletionSource {
    const cache = new Map<string, { at: number; value: Promise<unknown> }>()
    const cached = <T>(key: string, load: () => Promise<T>): Promise<T> => {
        const hit = cache.get(key)
        if (hit && Date.now() - hit.at < CACHE_TTL_MS) {
            return hit.value as Promise<T>
        }
        const value = load()
        cache.set(key, { at: Date.now(), value })
        // A failed request must not stay cached.
        value.catch(() => cache.delete(key))
        return value
    }
    const fetchNames = async (search: string): Promise<PromQLMetricName[]> => {
        const response = await metricsNamesRetrieve(projectId, {
            limit: NAMES_PAGE,
            ...(search ? { value: search } : {}),
        })
        return response.results.map((result) => ({ name: result.name, type: result.metric_type }))
    }
    const baseMetricName = (metricName: string | undefined): string | undefined =>
        metricName?.endsWith(BUCKET_SUFFIX) ? metricName.slice(0, -BUCKET_SUFFIX.length) : metricName

    return {
        metricNames: async (search) => {
            // Like Grafana, load the names once and filter here, so typing does not wait on the network.
            // A team with more names than one page gets a server-side search instead.
            const all = await cached('names', () => fetchNames(''))
            if (all.length < NAMES_PAGE) {
                const needle = search.toLowerCase()
                return all.filter((metric) => metric.name.toLowerCase().includes(needle))
            }
            return search ? cached(`names:${search}`, () => fetchNames(search)) : all
        },
        labelNames: (metricName, search) =>
            cached(`labels:${metricName ?? ''}:${search}`, async () => {
                const metric = baseMetricName(metricName)
                const response = await metricsAttributesRetrieve(projectId, {
                    limit: LIMIT,
                    ...(metric ? { metricName: metric } : {}),
                    ...(search ? { search } : {}),
                })
                const names = response.results
                    .map((result) => result.name)
                    .filter((name) => name !== 'service.name' && name !== SERVICE_LABEL)
                const extra = [
                    ...(SERVICE_LABEL.includes(search) ? [SERVICE_LABEL] : []),
                    ...(metricName?.endsWith(BUCKET_SUFFIX) && 'le'.includes(search) ? ['le'] : []),
                ]
                return [...extra, ...names]
            }),
        labelValues: (labelName, _metricName, search) =>
            labelName === 'le' || labelName === '__name__'
                ? Promise.resolve([])
                : cached(`values:${labelName}:${search}`, async () => {
                      const response = await metricsAttributeValuesRetrieve(projectId, {
                          key: labelName,
                          limit: LIMIT,
                          ...(search ? { value: search } : {}),
                      })
                      return response.results.map((result) => result.name)
                  }),
    }
}
