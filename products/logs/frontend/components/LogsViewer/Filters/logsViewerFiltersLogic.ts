import equal from 'fast-deep-equal'
import { actions, afterMount, kea, key, listeners, path, propsChanged, props, reducers, selectors } from 'kea'
import posthog from 'posthog-js'

import { DEFAULT_UNIVERSAL_GROUP_FILTER } from 'lib/components/UniversalFilters/universalFiltersLogic'
import { dayjs } from 'lib/dayjs'

import { DateRange, LogSeverityLevel, LogsQuery } from '~/queries/schema/schema-general'
import {
    FilterLogicalOperator,
    PropertyFilterType,
    PropertyOperator,
    UniversalFiltersGroup,
    UniversalFiltersGroupValue,
} from '~/types'

import { LogsViewerFilters } from 'products/logs/frontend/components/LogsViewer/config/types'
import { zoomDateRange } from 'products/logs/frontend/components/LogsViewer/Filters/zoom-utils'

import type { logsViewerFiltersLogicType } from './logsViewerFiltersLogicType'

export const DEFAULT_DATE_RANGE = { date_from: '-1h', date_to: null }
const VALID_SEVERITY_LEVELS: readonly LogSeverityLevel[] = ['trace', 'debug', 'info', 'warn', 'error', 'fatal']
export const DEFAULT_SEVERITY_LEVELS = [] as LogsQuery['severityLevels']

export const isValidSeverityLevel = (level: string): level is LogSeverityLevel =>
    VALID_SEVERITY_LEVELS.includes(level as LogSeverityLevel)

export const DEFAULT_SERVICE_NAMES = [] as LogsQuery['serviceNames']

export interface LogsViewerFiltersLogicProps {
    id: string
    initialFilters?: Partial<LogsViewerFilters>
    // Filters enforced by the embedding scene. Merged into filterGroup and rendered
    // without an X — users can't accidentally clear the scope (e.g. the person profile
    // Logs tab pins a distinct_id filter so the tab can't fall back to project-wide logs).
    pinnedFilters?: UniversalFiltersGroup
}

// Returns a filterGroup with pinned values prepended to the nested group, deduplicated
// by deep equality against existing user filters.
export function mergePinnedFilters(
    filterGroup: UniversalFiltersGroup,
    pinnedFilters: UniversalFiltersGroup | undefined
): UniversalFiltersGroup {
    if (!pinnedFilters?.values?.length) {
        return filterGroup
    }
    const inner = filterGroup.values[0] as UniversalFiltersGroup | undefined
    const innerValues = inner?.values ?? []
    const existingNonPinned = innerValues.filter((v) => !pinnedFilters.values.some((pv) => equal(v, pv)))
    return {
        ...filterGroup,
        values: [
            {
                type: FilterLogicalOperator.And,
                values: [...pinnedFilters.values, ...existingNonPinned],
            } as UniversalFiltersGroup,
            ...filterGroup.values.slice(1),
        ],
    }
}

export const logsViewerFiltersLogic = kea<logsViewerFiltersLogicType>([
    path(['products', 'logs', 'frontend', 'components', 'LogsViewer', 'Filters', 'logsViewerFiltersLogic']),
    props({ id: 'default' } as LogsViewerFiltersLogicProps),
    key((props) => props.id),

    actions({
        // setting individual filters
        setDateRange: (dateRange: DateRange) => ({ dateRange }),
        setSearchTerm: (searchTerm: LogsQuery['searchTerm']) => ({ searchTerm }),
        setSeverityLevels: (severityLevels: LogsQuery['severityLevels']) => ({ severityLevels }),
        setServiceNames: (serviceNames: LogsQuery['serviceNames']) => ({ serviceNames }),
        setFilterGroup: (filterGroup: UniversalFiltersGroup, openFilterOnInsert: boolean = true) => ({
            filterGroup,
            openFilterOnInsert,
        }),

        // setting all filters at once
        setFilters: (filters: Partial<LogsViewerFilters>, pushToHistory: boolean = true) => ({
            filters,
            pushToHistory,
        }),

        // Mirror of the `pinnedFilters` prop into state so consumers (LogsFilterBar)
        // can read it via useValues without going through the kea selector input-prop
        // machinery (which doesn't accept optional props).
        setPinnedFilters: (pinnedFilters: UniversalFiltersGroup | undefined) => ({ pinnedFilters }),

        zoomDateRange: (multiplier: number) => ({ multiplier }),

        addFilter: (
            key: string,
            value: string,
            operator: PropertyOperator = PropertyOperator.Exact,
            propertyType: PropertyFilterType = PropertyFilterType.LogAttribute
        ) => ({
            key,
            value,
            operator,
            propertyType,
        }),
    }),

    reducers({
        dateRange: [
            DEFAULT_DATE_RANGE as DateRange,
            {
                setDateRange: (_, { dateRange }) => dateRange,
                setFilters: (state, { filters }) => filters.dateRange ?? state,
            },
        ],
        searchTerm: [
            '' as LogsQuery['searchTerm'],
            {
                setSearchTerm: (_, { searchTerm }) => searchTerm,
                setFilters: (state, { filters }) => filters.searchTerm ?? state,
            },
        ],
        severityLevels: [
            DEFAULT_SEVERITY_LEVELS as LogsQuery['severityLevels'],
            {
                setSeverityLevels: (_, { severityLevels }) => severityLevels,
                setFilters: (state, { filters }) => filters.severityLevels ?? state,
            },
        ],
        serviceNames: [
            DEFAULT_SERVICE_NAMES as LogsQuery['serviceNames'],
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
        openFilterOnInsert: [
            false as boolean,
            {
                setFilterGroup: (_, { openFilterOnInsert }) => openFilterOnInsert,
            },
        ],
        pinnedFilters: [
            undefined as UniversalFiltersGroup | undefined,
            {
                setPinnedFilters: (_, { pinnedFilters }) => pinnedFilters,
            },
        ],
    }),

    selectors({
        id: [(_, p) => [p.id], (id: string) => id],
        filters: [
            (s) => [s.dateRange, s.searchTerm, s.severityLevels, s.serviceNames, s.filterGroup],
            (
                dateRange: DateRange,
                searchTerm: LogsQuery['searchTerm'],
                severityLevels: LogsQuery['severityLevels'],
                serviceNames: LogsQuery['serviceNames'],
                filterGroup: UniversalFiltersGroup
            ): LogsViewerFilters => ({ dateRange, searchTerm, severityLevels, serviceNames, filterGroup }),
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
                explicitDate: dateRange.explicitDate,
            }),
        ],
    }),

    listeners(({ actions, values }) => ({
        zoomDateRange: ({ multiplier }) => {
            posthog.capture('logs date range zoomed', {
                direction: multiplier > 1 ? 'out' : 'in',
                multiplier,
            })
            const newDateRange = zoomDateRange(values.filters.dateRange, multiplier)
            actions.setDateRange(newDateRange)
        },
        addFilter: ({ key, value, operator, propertyType }) => {
            const currentGroup = values.filters.filterGroup.values[0] as UniversalFiltersGroup

            const newGroup: UniversalFiltersGroup = {
                ...currentGroup,
                values: [
                    ...currentGroup.values,
                    {
                        key,
                        value: [value],
                        operator,
                        type: propertyType,
                    } as UniversalFiltersGroupValue,
                ],
            }

            actions.setFilterGroup({ ...values.filters.filterGroup, values: [newGroup] }, false)
        },
    })),

    propsChanged(({ actions, values, props: logicProps }, oldProps) => {
        if (logicProps.initialFilters && logicProps.initialFilters !== oldProps.initialFilters) {
            actions.setFilters(logicProps.initialFilters, false)
        } else if (!logicProps.initialFilters && oldProps.initialFilters) {
            actions.setFilters(
                {
                    searchTerm: '',
                    severityLevels: DEFAULT_SEVERITY_LEVELS,
                    serviceNames: DEFAULT_SERVICE_NAMES,
                },
                false
            )
        }
        // Re-merge pinned filters when the embedding scene changes them (e.g. switching
        // between people on the person profile). Deep-equal check avoids re-merging on
        // every render when the parent reconstructs the prop object identically.
        if (!equal(logicProps.pinnedFilters, oldProps.pinnedFilters)) {
            actions.setPinnedFilters(logicProps.pinnedFilters)
            actions.setFilterGroup(mergePinnedFilters(values.filterGroup, logicProps.pinnedFilters), false)
        }
    }),

    afterMount(({ actions, values, props: logicProps }) => {
        if (logicProps.initialFilters) {
            actions.setFilters(logicProps.initialFilters, false)
        }
        if (logicProps.pinnedFilters) {
            actions.setPinnedFilters(logicProps.pinnedFilters)
            actions.setFilterGroup(mergePinnedFilters(values.filterGroup, logicProps.pinnedFilters), false)
        }
    }),
])
