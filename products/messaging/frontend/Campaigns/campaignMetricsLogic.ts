import { actions, kea, key, listeners, path, props, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { MetricsFilters } from 'scenes/hog-functions/metrics/hogFunctionMetricsLogic'

import { hogql } from '~/queries/utils'

import type { campaignMetricsLogicType } from './campaignMetricsLogicType'

export type CampaignMetricsLogicProps = {
    id: string
}

export const ALL_METRIC_TYPES = [
    { label: 'Succeeded', value: 'succeeded' },
    { label: 'Failed', value: 'failed' },
    { label: 'Filtered', value: 'filtered' },
    { label: 'Disabled temporarily', value: 'disabled_temporarily' },
    { label: 'Disabled permanently', value: 'disabled_permanently' },
    { label: 'Masked', value: 'masked' },
    { label: 'Filtering failed', value: 'filtering_failed' },
    { label: 'Inputs failed', value: 'inputs_failed' },
    { label: 'Fetch', value: 'fetch' },
]

const DEFAULT_FILTERS: MetricsFilters = {
    before: undefined,
    after: '-7d',
    interval: 'day',
    name: ALL_METRIC_TYPES.filter(({ value }) => value !== 'filtered')
        .map(({ value }) => value)
        .join(','),
}

export type CampaignMetricsDetails = {
    name: string
    labels: string[]
    values: number[]
    total: number
}

export const campaignMetricsLogic = kea<campaignMetricsLogicType>([
    props({} as CampaignMetricsLogicProps),
    key(({ id }: CampaignMetricsLogicProps) => id),
    path((id) => ['messaging', 'campaigns', 'campaignMetricsLogic', id]),
    actions({
        setFilters: (filters: Partial<MetricsFilters>) => ({ filters }),
    }),
    loaders(({ values, props }) => ({
        metricsByKind: [
            null as Record<string, CampaignMetricsDetails> | null,
            {
                loadMetricsByKind: async () => {
                    const { before, after, interval } = values.filters

                    const dateClause =
                        interval === 'day'
                            ? 'toStartOfDay(timestamp)'
                            : interval === 'week'
                            ? 'toStartOfWeek(timestamp)'
                            : 'toStartOfHour(timestamp)'

                    const query = hogql`SELECT ${hogql.raw(
                        dateClause
                    )} AS timestamp, metric_name, count() AS total_count
                        FROM app_metrics
                        WHERE app_source = 'hog_flow'
                        AND app_source_id = ${props.id}
                        AND timestamp >= {filters.dateRange.from}
                        AND timestamp <= {filters.dateRange.to}
                        GROUP BY timestamp, metric_name
                        ORDER BY timestamp, metric_name`

                    const response = await api.queryHogQL(query, {
                        refresh: 'force_blocking',
                        filtersOverride: {
                            date_from: after ?? '-7d',
                            date_to: before,
                        },
                    })

                    const byKind: Record<string, CampaignMetricsDetails> = {}

                    // TODO: The results don't include empty values in the sense that they aren't creating a full time series.
                    for (const result of response.results) {
                        const [time, name, count] = result

                        if (!byKind[name]) {
                            byKind[name] = {
                                name,
                                labels: [],
                                values: [],
                                total: 0,
                            }
                        }

                        byKind[name].labels.push(time)
                        byKind[name].values.push(count)
                        byKind[name].total += count
                    }

                    return byKind
                },
            },
        ],
    })),
    reducers({
        filters: [
            DEFAULT_FILTERS,
            {
                setFilters: (state, { filters }) => ({ ...state, ...filters }),
            },
        ],
    }),
    listeners(({ actions }) => ({
        setFilters: async (_, breakpoint) => {
            await breakpoint(100)
            actions.loadMetricsByKind()
        },
    })),
])
