import { deepEqual as equal } from 'fast-equals'
import {
    MakeLogicType,
    actions,
    afterMount,
    kea,
    key,
    listeners,
    path,
    propsChanged,
    props,
    reducers,
    selectors,
} from 'kea'
import posthog from 'posthog-js'

import { zoomDateRange } from 'lib/components/DateFilter/DateRangePicker'
import { DEFAULT_UNIVERSAL_GROUP_FILTER } from 'lib/components/UniversalFilters/constants'
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
import {
    FacetFilterTarget,
    SERVICE_NAME_FILTER,
    SEVERITY_LEVEL_FILTER,
    setFacetIncluded,
} from 'products/logs/frontend/components/LogsViewer/FacetRail/facetFilters'
import {
    LogsFilterTarget,
    mergeFilterIntoValues,
} from 'products/logs/frontend/components/LogsViewer/Filters/logsFilterAdd'

export const DEFAULT_DATE_RANGE = { date_from: '-1h', date_to: null }
const VALID_SEVERITY_LEVELS: readonly LogSeverityLevel[] = ['trace', 'debug', 'info', 'warn', 'error', 'fatal']
export const DEFAULT_SEVERITY_LEVELS = [] as LogsQuery['severityLevels']

export const isValidSeverityLevel = (level: string): level is LogSeverityLevel =>
    VALID_SEVERITY_LEVELS.includes(level as LogSeverityLevel)

export const DEFAULT_SERVICE_NAMES = [] as LogsQuery['serviceNames']

export interface LogsViewerFiltersLogicProps {
    id: string
    initialFilters?: Partial<LogsViewerFilters>
    // Filters enforced by the embedding scene (e.g. the tracing span drawer pins a
    // trace_id filter so the tab can't fall back to project-wide logs). Kept
    // entirely separate from the user-editable `filterGroup` — combined with it only
    // at query-build time via `queryFilterGroup` so the chips never see them and
    // can't drift when the pinned shape changes.
    pinnedFilters?: UniversalFiltersGroup
    // Scope every query to this person (uuid or numeric id). Expanded server-side to the
    // person's distinct ids and matched against the team's configured distinct-id log
    // attributes — unlike a pinned distinct-ids filter, not capped by how many ids the
    // person page happened to load.
    personId?: string
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

/**
 * Folds the legacy `severityLevels` / `serviceNames` fields into the filterGroup as `exact` log
 * filters. Those fields predate the facet rail and are still how URL params, saved views, alerts and
 * embedding scenes hand the viewer a level or service selection, but the viewer keeps that selection
 * in the filterGroup alone, so the rail's checkboxes and the chips bar cannot disagree about what is
 * filtered. Exclusions have never had a dedicated field, so they are left as they are.
 *
 * A field that is present but empty clears that facet's includes, which is how an embedding scene
 * drops the scope it applied; a field that is absent leaves the group untouched. An empty field
 * handed over *alongside* a group is ignored, because the group is then the whole selection: a saved
 * view or a persisted filter-history entry can carry `severityLevels: []` next to a group that holds
 * a `severity_level =` chip the user added by hand, and clearing on that would drop the chip on
 * restore.
 */
export function foldLegacyColumnFilters(
    filterGroup: UniversalFiltersGroup,
    filters: Partial<LogsViewerFilters>
): UniversalFiltersGroup {
    const groupIsAuthoritative = !!filters.filterGroup?.values
    let folded = filterGroup
    const fold = (field: string[] | undefined, target: FacetFilterTarget): void => {
        if (field === undefined || (groupIsAuthoritative && field.length === 0)) {
            return
        }
        folded = setFacetIncluded(folded, target, field)
    }
    fold(filters.severityLevels, SEVERITY_LEVEL_FILTER)
    fold(filters.serviceNames, SERVICE_NAME_FILTER)
    return folded
}

/**
 * The dedicated LogsQuery fields, empty. Level and service selections travel inside `filterGroup`
 * (see foldLegacyColumnFilters), but LogsQuery requires both keys, so viewer query payloads spread
 * this in rather than each restating that they filter on neither.
 */
export function unsetColumnQueryFields(): Pick<LogsQuery, 'severityLevels' | 'serviceNames'> {
    return { severityLevels: [], serviceNames: [] }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface logsViewerFiltersLogicValues {
    dateRange: DateRange
    facetRefreshCounter: number
    filterGroup: UniversalFiltersGroup
    filters: LogsViewerFilters
    focusedFilter: LogsFilterTarget | null
    id: string
    openFilterOnInsert: boolean
    personId: string | undefined
    pinnedFilters: UniversalFiltersGroup | undefined
    queryFilterGroup: UniversalFiltersGroup
    searchTerm: LogsQuery['searchTerm']
    utcDateRange: {
        date_from: string | null | undefined
        date_to: string | null | undefined
        explicitDate: boolean | null | undefined
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface logsViewerFiltersLogicActions {
    addFilter: (
        key: string,
        value: string,
        operator?: PropertyOperator,
        propertyType?: PropertyFilterType
    ) => {
        key: string
        operator: PropertyOperator
        propertyType: PropertyFilterType
        value: string
    }
    bumpFacetRefresh: () => {
        value: true
    }
    focusFilter: (target: LogsFilterTarget | null) => {
        target: FacetFilterTarget | null
    }
    setDateRange: (dateRange: DateRange) => {
        dateRange: DateRange
    }
    setFilterGroup: (
        filterGroup: UniversalFiltersGroup,
        openFilterOnInsert?: boolean
    ) => {
        filterGroup: UniversalFiltersGroup
        openFilterOnInsert: boolean
    }
    setFilters: (
        filters: Partial<LogsViewerFilters>,
        pushToHistory?: boolean
    ) => {
        filters: Partial<LogsViewerFilters>
        pushToHistory: boolean
    }
    setPersonId: (personId: string | undefined) => {
        personId: string | undefined
    }
    setPinnedFilters: (pinnedFilters: UniversalFiltersGroup | undefined) => {
        pinnedFilters: UniversalFiltersGroup | undefined
    }
    setSearchTerm: (searchTerm: LogsQuery['searchTerm']) => {
        searchTerm: string | undefined
    }
    zoomDateRange: (multiplier: number) => {
        multiplier: number
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface logsViewerFiltersLogicMeta {
    key: string
    __keaTypeGenInternalSelectorTypes: {
        id: (id: string) => string
        filters: (
            dateRange: DateRange,
            searchTerm: string | undefined,
            filterGroup: UniversalFiltersGroup
        ) => LogsViewerFilters
        queryFilterGroup: (
            filterGroup: UniversalFiltersGroup,
            pinnedFilters: UniversalFiltersGroup | undefined
        ) => UniversalFiltersGroup
        utcDateRange: (dateRange: DateRange) => {
            date_from: string | null | undefined
            date_to: string | null | undefined
            explicitDate: boolean | null | undefined
        }
    }
}

export type logsViewerFiltersLogicType = MakeLogicType<
    logsViewerFiltersLogicValues,
    logsViewerFiltersLogicActions,
    LogsViewerFiltersLogicProps,
    logsViewerFiltersLogicMeta
>

export const logsViewerFiltersLogic = kea<logsViewerFiltersLogicType>([
    path(['products', 'logs', 'frontend', 'components', 'LogsViewer', 'Filters', 'logsViewerFiltersLogic']),
    props({ id: 'default' } as LogsViewerFiltersLogicProps),
    key((props) => props.id),

    actions({
        // setting individual filters
        setDateRange: (dateRange: DateRange) => ({ dateRange }),
        setSearchTerm: (searchTerm: LogsQuery['searchTerm']) => ({ searchTerm }),
        // Ask the chips bar to open the filter on this attribute for editing.
        focusFilter: (target: LogsFilterTarget | null) => ({ target }),
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

        // Mirror of the `personId` prop into state, same rationale as `setPinnedFilters`.
        setPersonId: (personId: string | undefined) => ({ personId }),

        zoomDateRange: (multiplier: number) => ({ multiplier }),

        bumpFacetRefresh: true,

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
        facetRefreshCounter: [
            0,
            {
                bumpFacetRefresh: (state) => state + 1,
            },
        ],
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
        filterGroup: [
            DEFAULT_UNIVERSAL_GROUP_FILTER as UniversalFiltersGroup,
            {
                setFilterGroup: (_, { filterGroup }) =>
                    filterGroup && filterGroup.values ? filterGroup : DEFAULT_UNIVERSAL_GROUP_FILTER,
                setFilters: (state, { filters }) =>
                    foldLegacyColumnFilters(
                        filters.filterGroup && filters.filterGroup.values ? filters.filterGroup : state,
                        filters
                    ),
            },
        ],
        openFilterOnInsert: [
            false as boolean,
            {
                setFilterGroup: (_, { openFilterOnInsert }) => openFilterOnInsert,
            },
        ],
        // The attribute whose chip the bar holds open, or null for none. Keyed on the attribute
        // rather than a position: filters come and go, and a stale index would open whichever
        // filter shifted into that slot.
        focusedFilter: [
            null as LogsFilterTarget | null,
            {
                focusFilter: (_, { target }) => target,
            },
        ],
        pinnedFilters: [
            undefined as UniversalFiltersGroup | undefined,
            {
                setPinnedFilters: (_, { pinnedFilters }) => pinnedFilters,
            },
        ],
        personId: [
            undefined as string | undefined,
            {
                setPersonId: (_, { personId }) => personId,
            },
        ],
    }),

    selectors({
        id: [(_, p) => [p.id], (id: string) => id],
        filters: [
            (s) => [s.dateRange, s.searchTerm, s.filterGroup],
            (
                dateRange: DateRange,
                searchTerm: LogsQuery['searchTerm'],
                filterGroup: UniversalFiltersGroup
            ): LogsViewerFilters => ({ dateRange, searchTerm, filterGroup }),
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

            // Reconciled rather than appended, so clicking the same attribute row twice does not
            // stack a duplicate chip, and including a value cancels a standing exclusion of it.
            // Same rules the search bar and the facet rail apply.
            const reconciled = mergeFilterIntoValues(currentGroup.values, {
                key,
                value: [value],
                operator,
                type: propertyType,
            } as UniversalFiltersGroupValue)

            if (equal(reconciled, currentGroup.values)) {
                // The click landed on filters that already say this. Writing an equal group would
                // reload the list, the patterns pivot and the group-by breakdown for no change.
                return
            }

            const newGroup: UniversalFiltersGroup = { ...currentGroup, values: reconciled }

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
        if (logicProps.personId !== oldProps.personId) {
            actions.setPersonId(logicProps.personId)
        }
    }),

    afterMount(({ actions, props: logicProps }) => {
        if (logicProps.initialFilters) {
            actions.setFilters(logicProps.initialFilters, false)
        }
        if (logicProps.pinnedFilters) {
            actions.setPinnedFilters(logicProps.pinnedFilters)
        }
        if (logicProps.personId) {
            actions.setPersonId(logicProps.personId)
        }
    }),
])
