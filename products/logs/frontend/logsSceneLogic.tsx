import equal from 'fast-deep-equal'
import { actions, connect, kea, listeners, path, props, reducers, selectors } from 'kea'
import { router } from 'kea-router'
import posthog from 'posthog-js'

import { syncSearchParams, updateSearchParams } from '@posthog/products-error-tracking/frontend/utils'

import { DEFAULT_UNIVERSAL_GROUP_FILTER } from 'lib/components/UniversalFilters/universalFiltersLogic'
import { tabAwareActionToUrl } from 'lib/logic/scenes/tabAwareActionToUrl'
import { tabAwareScene } from 'lib/logic/scenes/tabAwareScene'
import { tabAwareUrlToAction } from 'lib/logic/scenes/tabAwareUrlToAction'
import { parseTagsFilter } from 'lib/utils'
import { Params } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'

import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'
import { UniversalFiltersGroup, UniversalFiltersGroupValue } from '~/types'

import {
    DEFAULT_DATE_RANGE,
    DEFAULT_SERVICE_NAMES,
    DEFAULT_SEVERITY_LEVELS,
    isValidSeverityLevel,
    logsViewerFiltersLogic,
} from 'products/logs/frontend/components/LogsViewer/Filters/logsViewerFiltersLogic'
import {
    DEFAULT_ORDER_BY,
    logsViewerConfigLogic,
} from 'products/logs/frontend/components/LogsViewer/config/logsViewerConfigLogic'
import { LogsViewerFilters } from 'products/logs/frontend/components/LogsViewer/config/types'
import {
    DEFAULT_INITIAL_LOGS_LIMIT,
    logsViewerDataLogic,
} from 'products/logs/frontend/components/LogsViewer/data/logsViewerDataLogic'

import type { logsSceneLogicType } from './logsSceneLogicType'
import { LogsFiltersHistoryEntry } from './types'

export interface LogsLogicProps {
    tabId: string
}

export const logsSceneLogic = kea<logsSceneLogicType>([
    props({} as LogsLogicProps),
    path(['products', 'logs', 'frontend', 'logsSceneLogic']),
    tabAwareScene(),
    connect((props: LogsLogicProps) => ({
        actions: [
            teamLogic,
            ['addProductIntent'],
            logsViewerFiltersLogic({ id: props.tabId }),
            ['setDateRange', 'setFilterGroup', 'setFilters', 'setSearchTerm', 'setSeverityLevels', 'setServiceNames'],
            logsViewerConfigLogic({ id: props.tabId }),
            ['setOrderBy'],
            logsViewerDataLogic({ id: props.tabId }),
            ['setInitialLogsLimit', 'runQuery', 'clearLogs', 'fetchLogsSuccess'],
        ],
        values: [
            logsViewerFiltersLogic({ id: props.tabId }),
            ['filters', 'utcDateRange'],
            logsViewerConfigLogic({ id: props.tabId }),
            ['orderBy'],
            logsViewerDataLogic({ id: props.tabId }),
            ['initialLogsLimit', 'hasRunQuery'],
        ],
    })),
    tabAwareUrlToAction(({ actions, values }) => {
        const urlToAction = (_: any, params: Params): void => {
            const filtersFromUrl: Partial<LogsViewerFilters> = {}
            let hasFilterChanges = false

            if (params.dateRange) {
                try {
                    const dateRange =
                        typeof params.dateRange === 'string' ? JSON.parse(params.dateRange) : params.dateRange
                    if (!equal(dateRange, values.filters.dateRange)) {
                        filtersFromUrl.dateRange = dateRange
                        hasFilterChanges = true
                    }
                } catch {
                    // Ignore malformed dateRange JSON in URL
                }
            }
            if (params.filterGroup) {
                if (!equal(params.filterGroup, values.filters.filterGroup)) {
                    filtersFromUrl.filterGroup = params.filterGroup
                    hasFilterChanges = true
                }
            } else if (!equal(DEFAULT_UNIVERSAL_GROUP_FILTER, values.filters.filterGroup)) {
                filtersFromUrl.filterGroup = DEFAULT_UNIVERSAL_GROUP_FILTER
                hasFilterChanges = true
            }
            if (params.searchTerm) {
                if (!equal(params.searchTerm, values.filters.searchTerm)) {
                    filtersFromUrl.searchTerm = params.searchTerm
                    hasFilterChanges = true
                }
            } else if (values.filters.searchTerm !== '') {
                filtersFromUrl.searchTerm = ''
                hasFilterChanges = true
            }
            if (params.severityLevels) {
                const parsed = parseTagsFilter(params.severityLevels)
                if (parsed) {
                    const levels = parsed.filter(isValidSeverityLevel)
                    if (levels.length > 0 && !equal(levels, values.filters.severityLevels)) {
                        filtersFromUrl.severityLevels = levels
                        hasFilterChanges = true
                    }
                }
            } else if (!equal(DEFAULT_SEVERITY_LEVELS, values.filters.severityLevels)) {
                filtersFromUrl.severityLevels = DEFAULT_SEVERITY_LEVELS
                hasFilterChanges = true
            }
            if (params.serviceNames) {
                const names = parseTagsFilter(params.serviceNames)
                if (names && !equal(names, values.filters.serviceNames)) {
                    filtersFromUrl.serviceNames = names
                    hasFilterChanges = true
                }
            } else if (!equal(DEFAULT_SERVICE_NAMES, values.filters.serviceNames)) {
                filtersFromUrl.serviceNames = DEFAULT_SERVICE_NAMES
                hasFilterChanges = true
            }

            if (hasFilterChanges) {
                actions.setFilters(filtersFromUrl, false)
            }

            // Non-filter params handled separately
            if (params.orderBy && !equal(params.orderBy, values.orderBy)) {
                actions.setOrderBy(params.orderBy)
            }
            if (params.initialLogsLimit != null && +params.initialLogsLimit !== values.initialLogsLimit) {
                actions.setInitialLogsLimit(+params.initialLogsLimit)
            }
        }
        return {
            '*': urlToAction,
        }
    }),

    tabAwareActionToUrl(({ actions, values }) => {
        const buildUrlAndRunQuery = (): [
            string,
            Params,
            Record<string, any>,
            {
                replace: boolean
            },
        ] => {
            return syncSearchParams(router, (params: Params) => {
                updateSearchParams(params, 'searchTerm', values.filters.searchTerm, '')
                updateSearchParams(params, 'filterGroup', values.filters.filterGroup, DEFAULT_UNIVERSAL_GROUP_FILTER)
                updateSearchParams(params, 'dateRange', values.filters.dateRange, DEFAULT_DATE_RANGE)
                updateSearchParams(params, 'severityLevels', values.filters.severityLevels, DEFAULT_SEVERITY_LEVELS)
                updateSearchParams(params, 'serviceNames', values.filters.serviceNames, DEFAULT_SERVICE_NAMES)
                updateSearchParams(params, 'orderBy', values.orderBy, DEFAULT_ORDER_BY)
                actions.runQuery()
                return params
            })
        }

        const clearInitialLogsLimit = (): [
            string,
            Params,
            Record<string, any>,
            {
                replace: boolean
            },
        ] => {
            return syncSearchParams(router, (params: Params) => {
                updateSearchParams(params, 'initialLogsLimit', null, DEFAULT_INITIAL_LOGS_LIMIT)
                return params
            })
        }

        return {
            // initialLogsLimit is a one-shot override from "copy link to log" URLs.
            // It ensures the first fetch loads enough logs to include the linked log,
            // then resets to null so subsequent queries use the default page size.
            fetchLogsSuccess: () => clearInitialLogsLimit(),
            syncUrlAndRunQuery: () => buildUrlAndRunQuery(),
        }
    }),

    actions({
        syncUrlAndRunQuery: true,
        pushToFilterHistory: (filters: LogsViewerFilters) => ({ filters }),
        restoreFiltersFromHistory: (index: number) => ({ index }),
        clearFilterHistory: true,
        toggleAttributeBreakdown: (key: string) => ({ key }),
        setExpandedAttributeBreaksdowns: (expandedAttributeBreaksdowns: string[]) => ({ expandedAttributeBreaksdowns }),
    }),

    reducers({
        filterHistory: [
            [] as LogsFiltersHistoryEntry[],
            { persist: true },
            {
                pushToFilterHistory: (state, { filters }) => {
                    if (state.length > 0 && equal(state[0].filters, filters)) {
                        return state
                    }
                    const entry: LogsFiltersHistoryEntry = { filters, timestamp: Date.now() }
                    return [entry, ...state].slice(0, 10)
                },
                clearFilterHistory: () => [],
            },
        ],
        expandedAttributeBreaksdowns: [
            [] as string[],
            {
                setExpandedAttributeBreaksdowns: (_, { expandedAttributeBreaksdowns }) => expandedAttributeBreaksdowns,
            },
        ],
    }),

    selectors({
        tabId: [(_, p) => [p.tabId], (tabId: string) => tabId],
        hasFilterHistory: [
            (s) => [s.filterHistory],
            (filterHistory: LogsFiltersHistoryEntry[]) => filterHistory.length > 0,
        ],
    }),

    listeners(({ values, actions }) => ({
        setSearchTerm: ({ searchTerm }) => {
            if (values.hasRunQuery) {
                posthog.capture('logs filter changed', {
                    filter_type: 'search',
                    search_term_length: searchTerm?.length ?? 0,
                })
                actions.addProductIntent({
                    product_type: ProductKey.LOGS,
                    intent_context: ProductIntentContext.LOGS_SET_FILTERS,
                })
                actions.pushToFilterHistory(values.filters)
            }
            actions.syncUrlAndRunQuery()
        },
        setFilterGroup: () => {
            // Don't run query if there's a filter without a value (user is still selecting)
            const hasIncompleteUniversalFilterValue = (filterValue: UniversalFiltersGroupValue): boolean => {
                if (!filterValue || typeof filterValue !== 'object') {
                    return false
                }

                // If this is a nested UniversalFiltersGroup, recursively check its values
                if ('type' in filterValue && 'values' in filterValue) {
                    const groupValues = (filterValue as UniversalFiltersGroup).values ?? []
                    return groupValues.some((child) => hasIncompleteUniversalFilterValue(child))
                }

                // ActionFilter: check for missing id
                if ('id' in filterValue) {
                    return (filterValue as { id: unknown }).id == null
                }

                // Property filter: check for missing or empty value
                if ('value' in filterValue) {
                    const val = (filterValue as { value: unknown }).value
                    return val == null || (Array.isArray(val) && val.length === 0)
                }

                return false
            }

            const rootGroup = values.filters.filterGroup?.values?.[0] as UniversalFiltersGroup | undefined
            const hasIncompleteFilter =
                rootGroup?.values?.some((filterValue) => hasIncompleteUniversalFilterValue(filterValue)) ?? false

            if (hasIncompleteFilter) {
                return
            }

            if (values.hasRunQuery) {
                posthog.capture('logs filter changed', { filter_type: 'attributes' })
                actions.addProductIntent({
                    product_type: ProductKey.LOGS,
                    intent_context: ProductIntentContext.LOGS_SET_FILTERS,
                })
                actions.pushToFilterHistory(values.filters)
            }
            actions.syncUrlAndRunQuery()
        },
        setSeverityLevels: ({ severityLevels }) => {
            if (values.hasRunQuery) {
                posthog.capture('logs filter changed', {
                    filter_type: 'severity',
                    severity_levels: severityLevels ?? [],
                })
                actions.addProductIntent({
                    product_type: ProductKey.LOGS,
                    intent_context: ProductIntentContext.LOGS_SET_FILTERS,
                })
                actions.pushToFilterHistory(values.filters)
            }
            actions.syncUrlAndRunQuery()
        },
        setServiceNames: ({ serviceNames }) => {
            if (values.hasRunQuery) {
                posthog.capture('logs filter changed', {
                    filter_type: 'service',
                    service_count: serviceNames?.length ?? 0,
                })
                actions.addProductIntent({
                    product_type: ProductKey.LOGS,
                    intent_context: ProductIntentContext.LOGS_SET_FILTERS,
                })
                actions.pushToFilterHistory(values.filters)
            }
            actions.syncUrlAndRunQuery()
        },
        setDateRange: () => {
            if (values.hasRunQuery) {
                posthog.capture('logs filter changed', { filter_type: 'date_range' })
                actions.addProductIntent({
                    product_type: ProductKey.LOGS,
                    intent_context: ProductIntentContext.LOGS_SET_FILTERS,
                })
                actions.pushToFilterHistory(values.filters)
            }
            actions.syncUrlAndRunQuery()
        },
        setFilters: ({ pushToHistory }) => {
            if (values.hasRunQuery) {
                posthog.capture('logs filter changed', { filter_type: 'bulk' })
                actions.addProductIntent({
                    product_type: ProductKey.LOGS,
                    intent_context: ProductIntentContext.LOGS_SET_FILTERS,
                })
                if (pushToHistory) {
                    actions.pushToFilterHistory(values.filters)
                }
            }
            actions.syncUrlAndRunQuery()
        },
        setOrderBy: ({ orderBy, source }) => {
            posthog.capture('logs setting changed', { setting: 'order_by', value: orderBy, source })
            actions.syncUrlAndRunQuery()
        },
        restoreFiltersFromHistory: ({ index }) => {
            const entry = values.filterHistory[index]
            if (entry) {
                posthog.capture('logs filter history restored', {
                    history_index: index,
                    history_size: values.filterHistory.length,
                })
                actions.setFilters(entry.filters, false)
            }
        },
        clearFilterHistory: () => {
            posthog.capture('logs filter history cleared', {
                history_size: values.filterHistory.length,
            })
        },

        toggleAttributeBreakdown: ({ key }) => {
            const breakdowns = [...values.expandedAttributeBreaksdowns]
            const index = breakdowns.indexOf(key)
            index >= 0 ? breakdowns.splice(index, 1) : breakdowns.push(key)
            actions.setExpandedAttributeBreaksdowns(breakdowns)
        },
    })),
])
