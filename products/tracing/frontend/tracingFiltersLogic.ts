import { actions, kea, path, reducers, selectors } from 'kea'

import { DEFAULT_UNIVERSAL_GROUP_FILTER } from 'lib/components/UniversalFilters/universalFiltersLogic'
import { dayjs } from 'lib/dayjs'

import { DateRange } from '~/queries/schema/schema-general'
import { UniversalFiltersGroup } from '~/types'

import type { tracingFiltersLogicType } from './tracingFiltersLogicType'

export const DEFAULT_DATE_RANGE: DateRange = { date_from: '-1h', date_to: null }
export const DEFAULT_SERVICE_NAMES: string[] = []
export const DEFAULT_ORDER_BY = 'latest' as const
export const DEFAULT_CHART_MODE = 'volume' as const
export const DEFAULT_HEATMAP_Y_SCALE = 'log' as const

export type TracingOrderBy = 'latest' | 'earliest'
export type TracingChartMode = 'volume' | 'latency'
export type TracingHeatmapYScale = 'linear' | 'log'

export interface TracingSelectedRegion {
    time_from: string
    time_to: string
    duration_min_nano: number
    duration_max_nano: number
}

export interface TracingFilters {
    dateRange: DateRange
    serviceNames: string[]
    filterGroup: UniversalFiltersGroup
    orderBy: TracingOrderBy
    chartMode: TracingChartMode
    heatmapYScale: TracingHeatmapYScale
    selectedRegion: TracingSelectedRegion | null
}

export const tracingFiltersLogic = kea<tracingFiltersLogicType>([
    path(['products', 'tracing', 'frontend', 'tracingFiltersLogic']),

    actions({
        setDateRange: (dateRange: DateRange) => ({ dateRange }),
        setServiceNames: (serviceNames: string[]) => ({ serviceNames }),
        setFilterGroup: (filterGroup: UniversalFiltersGroup) => ({ filterGroup }),
        setOrderBy: (orderBy: TracingOrderBy) => ({ orderBy }),
        setFilters: (filters: Partial<TracingFilters>) => ({ filters }),
        setChartMode: (chartMode: TracingChartMode) => ({ chartMode }),
        setHeatmapYScale: (heatmapYScale: TracingHeatmapYScale) => ({ heatmapYScale }),
        setSelectedRegion: (selectedRegion: TracingSelectedRegion | null) => ({ selectedRegion }),
        clearSelectedRegion: true,
    }),

    reducers({
        dateRange: [
            DEFAULT_DATE_RANGE as DateRange,
            {
                setDateRange: (_, { dateRange }) => dateRange,
                setFilters: (state, { filters }) => filters.dateRange ?? state,
            },
        ],
        serviceNames: [
            DEFAULT_SERVICE_NAMES as string[],
            {
                setServiceNames: (_, { serviceNames }) => serviceNames,
                setFilters: (state, { filters }) => filters.serviceNames ?? state,
            },
        ],
        filterGroup: [
            DEFAULT_UNIVERSAL_GROUP_FILTER as UniversalFiltersGroup,
            {
                setFilterGroup: (_, { filterGroup }) =>
                    filterGroup && filterGroup.values ? filterGroup : DEFAULT_UNIVERSAL_GROUP_FILTER,
                setFilters: (state, { filters }) =>
                    filters.filterGroup && filters.filterGroup.values ? filters.filterGroup : state,
            },
        ],
        orderBy: [
            DEFAULT_ORDER_BY as TracingOrderBy,
            {
                setOrderBy: (_, { orderBy }) => orderBy,
                setFilters: (state, { filters }) => (filters.orderBy as TracingOrderBy) ?? state,
            },
        ],
        chartMode: [
            DEFAULT_CHART_MODE as TracingChartMode,
            {
                setChartMode: (_, { chartMode }) => chartMode,
                setFilters: (state, { filters }) => (filters.chartMode as TracingChartMode) ?? state,
            },
        ],
        heatmapYScale: [
            DEFAULT_HEATMAP_Y_SCALE as TracingHeatmapYScale,
            {
                setHeatmapYScale: (_, { heatmapYScale }) => heatmapYScale,
                setFilters: (state, { filters }) => (filters.heatmapYScale as TracingHeatmapYScale) ?? state,
            },
        ],
        selectedRegion: [
            null as TracingSelectedRegion | null,
            {
                setSelectedRegion: (_, { selectedRegion }) => selectedRegion,
                clearSelectedRegion: () => null,
                setFilters: (state, { filters }) =>
                    filters.selectedRegion !== undefined ? filters.selectedRegion : state,
            },
        ],
    }),

    selectors({
        filters: [
            (s) => [
                s.dateRange,
                s.serviceNames,
                s.filterGroup,
                s.orderBy,
                s.chartMode,
                s.heatmapYScale,
                s.selectedRegion,
            ],
            (
                dateRange,
                serviceNames,
                filterGroup,
                orderBy,
                chartMode,
                heatmapYScale,
                selectedRegion
            ): TracingFilters => ({
                dateRange,
                serviceNames,
                filterGroup,
                orderBy,
                chartMode,
                heatmapYScale,
                selectedRegion,
            }),
        ],
        utcDateRange: [
            (s) => [s.dateRange],
            (dateRange: DateRange) => ({
                date_from: dayjs(dateRange.date_from).isValid()
                    ? dayjs(dateRange.date_from).toISOString()
                    : dateRange.date_from,
                date_to: dayjs(dateRange.date_to).isValid()
                    ? dayjs(dateRange.date_to).toISOString()
                    : dateRange.date_to,
            }),
        ],
    }),
])
