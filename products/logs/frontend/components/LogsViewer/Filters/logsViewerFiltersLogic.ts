import equal from 'fast-deep-equal'
import { actions, afterMount, kea, key, listeners, path, propsChanged, props, reducers, selectors } from 'kea'
import posthog from 'posthog-js'

import { zoomDateRange } from 'lib/components/DateFilter/DateRangePicker'
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
    // Filters enforced by the embedding scene (e.g. the person profile Logs tab pins
    // a distinct_id filter so the tab can't fall back to project-wide logs). Kept
    // entirely separate from the user-editable `filterGroup` — combined with it only
    // at query-build time via `queryFilterGroup` so the chips never see them and
    // can't drift when the pinned shape changes (e.g. `logs_distinct_id_attribute_key`
    // resolves to a non-default key after mount).
    pinnedFilters?: UniversalFiltersGroup
}

// Combines the user-editable filterGroup with pinned filters (prepended to the inner
// AND group). Used at query-build time and for taxonomic value suggestions so the
// query and suggestion stay scoped, without putting pinned filters into editable state.
export function combineWithPinnedFilters(
    filterGroup: UniversalFiltersGroup,
    pinnedFilters: UniversalFiltersGroup | undefined
): UniversalFiltersGroup {
    if (!pinnedFilters?.values?.length) {
        return filterGroup
    }
    const inner = filterGroup.values[0] as UniversalFiltersGroup | undefined
    const innerValues = inner?.values ?? []
    return {
        ...filterGroup,
        values: [
            {
                type: FilterLogicalOperator.And,
                values: [...pinnedFilters.values, ...innerValues],
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

        // Mirror of the `pinnedFilters` prop into state so consumers can read it via
        // useValues without going through the kea selector input-prop machinery
        // (which doesn't accept optional props).
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
        // Combined view used for query payloads and taxonomic value suggestions —
        // user-editable `filterGroup` with pinned filters prepended. Pinned filters
        // intentionally never enter `filterGroup` itself so chips and saved views
        // can't pick them up.
        queryFilterGroup: [
            (s) => [s.filterGroup, s.pinnedFilters],
            (filterGroup: UniversalFiltersGroup, pinnedFilters: UniversalFiltersGroup | undefined) =>
                combineWithPinnedFilters(filterGroup, pinnedFilters),
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

    propsChanged(({ actions, props: logicProps }, oldProps) => {
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
        // Mirror the prop into state when content changes (e.g. switching between
        // people on the person profile, or the team's pinned attribute key resolving
        // after mount). Deep-equal check avoids redundant updates on identical re-renders.
        if (!equal(logicProps.pinnedFilters, oldProps.pinnedFilters)) {
            actions.setPinnedFilters(logicProps.pinnedFilters)
        }
    }),

    afterMount(({ actions, props: logicProps }) => {
        if (logicProps.initialFilters) {
            actions.setFilters(logicProps.initialFilters, false)
        }
        if (logicProps.pinnedFilters) {
            actions.setPinnedFilters(logicProps.pinnedFilters)
        }
    }),
])
