import equal from 'fast-deep-equal'
import { actions, connect, kea, listeners, path, reducers } from 'kea'
import { router, urlToAction } from 'kea-router'

import { syncSearchParams, updateSearchParams } from '@posthog/products-error-tracking/frontend/utils'

import { DEFAULT_UNIVERSAL_GROUP_FILTER } from 'lib/components/UniversalFilters/universalFiltersLogic'
import { trackedActionToUrl } from 'lib/logic/scenes/trackedActionToUrl'
import { parseTagsFilter } from 'lib/utils/url'
import { sqlEditorLogic } from 'scenes/data-warehouse/editor/sqlEditorLogic'
import { SQLEditorMode } from 'scenes/data-warehouse/editor/sqlEditorModes'
import { Params } from 'scenes/sceneTypes'

import {
    DEFAULT_ORDER_BY,
    logsViewerConfigLogic,
} from 'products/logs/frontend/components/LogsViewer/config/logsViewerConfigLogic'
import { LogsViewerFilters } from 'products/logs/frontend/components/LogsViewer/config/types'
import {
    DEFAULT_INITIAL_LOGS_LIMIT,
    logsViewerDataLogic,
} from 'products/logs/frontend/components/LogsViewer/data/logsViewerDataLogic'
import { facetRailLogic } from 'products/logs/frontend/components/LogsViewer/FacetRail/facetRailLogic'
import { logsFilterHistoryLogic } from 'products/logs/frontend/components/LogsViewer/Filters/logsFilterHistoryLogic'
import {
    DEFAULT_DATE_RANGE,
    DEFAULT_SERVICE_NAMES,
    DEFAULT_SEVERITY_LEVELS,
    isValidSeverityLevel,
    logsViewerFiltersLogic,
} from 'products/logs/frontend/components/LogsViewer/Filters/logsViewerFiltersLogic'
import { logDetailsModalLogic } from 'products/logs/frontend/components/LogsViewer/LogDetailsModal/logDetailsModalLogic'
import { logsViewerLogic } from 'products/logs/frontend/components/LogsViewer/logsViewerLogic'

import type { logsSceneLogicType } from './logsSceneLogicType'

export const getLogsSqlEditorTabId = (id: string): string => `logs-sql-editor-${id}`

// Scope the viewer id (and so its persisted state: pinned logs, filters, config) per project.
// A static id would persist across projects in the same browser, leaking one project's pinned log payloads into another.
export const LOGS_SCENE_VIEWER_ID = `logs-scene-${window.POSTHOG_APP_CONTEXT?.current_team?.id ?? 'unknown'}`

export type LogsSceneActiveTab = 'viewer' | 'services' | 'alerts' | 'sql' | 'transformations' | 'configuration'
const VALID_ACTIVE_TABS: LogsSceneActiveTab[] = [
    'viewer',
    'services',
    'alerts',
    'sql',
    'transformations',
    'configuration',
]
export const DEFAULT_ACTIVE_TAB: LogsSceneActiveTab = 'viewer'

const resolveActiveTabFromParams = (params: Params): LogsSceneActiveTab | null => {
    if (typeof params.alertId === 'string' && params.alertId.length > 0) {
        return 'alerts'
    }
    if (typeof params.activeTab === 'string' && VALID_ACTIVE_TABS.includes(params.activeTab as LogsSceneActiveTab)) {
        return params.activeTab as LogsSceneActiveTab
    }
    return null
}

export const logsSceneLogic = kea<logsSceneLogicType>([
    path(['products', 'logs', 'frontend', 'logsSceneLogic']),
    connect(() => ({
        actions: [
            logsViewerFiltersLogic({ id: LOGS_SCENE_VIEWER_ID }),
            ['setFilters'],
            logsFilterHistoryLogic({ id: LOGS_SCENE_VIEWER_ID }),
            ['pushToFilterHistory'],
            logsViewerConfigLogic({ id: LOGS_SCENE_VIEWER_ID }),
            ['setOrderBy'],
            logsViewerDataLogic({ id: LOGS_SCENE_VIEWER_ID }),
            ['setInitialLogsLimit', 'fetchLogsSuccess', 'handleQueryChange'],
            logsViewerLogic({ id: LOGS_SCENE_VIEWER_ID }),
            ['setLinkToLogId', 'clearLinkToLogId'],
            logDetailsModalLogic({ id: LOGS_SCENE_VIEWER_ID }),
            ['closeLogDetails'],
            facetRailLogic({ id: LOGS_SCENE_VIEWER_ID }),
            ['setFacetNameSearch'],
        ],
        values: [
            logsViewerFiltersLogic({ id: LOGS_SCENE_VIEWER_ID }),
            ['filters', 'utcDateRange'],
            logsViewerConfigLogic({ id: LOGS_SCENE_VIEWER_ID }),
            ['orderBy'],
            logsViewerDataLogic({ id: LOGS_SCENE_VIEWER_ID }),
            ['initialLogsLimit'],
            logsViewerLogic({ id: LOGS_SCENE_VIEWER_ID }),
            ['linkToLogId'],
            facetRailLogic({ id: LOGS_SCENE_VIEWER_ID }),
            ['facetNameSearch'],
        ],
    })),
    urlToAction(({ actions, values, cache }) => {
        const urlToAction = (_: any, params: Params): void => {
            if (cache.isSyncingUrl) {
                return
            }
            const requestedTab = resolveActiveTabFromParams(params)
            if (requestedTab && requestedTab !== values.activeTab) {
                actions.setActiveTab(requestedTab)
            }

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

            const linkToLogId = params.linkToLogId as string | undefined
            if (linkToLogId && linkToLogId !== values.linkToLogId) {
                actions.setLinkToLogId(linkToLogId)
            }

            // Facet-name search: a plain string param. Absent param resets the field to empty.
            const facetNameSearch = typeof params.facetNameSearch === 'string' ? params.facetNameSearch : ''
            if (facetNameSearch !== values.facetNameSearch) {
                actions.setFacetNameSearch(facetNameSearch)
            }
        }
        return {
            '*': urlToAction,
        }
    }),

    trackedActionToUrl(({ values, cache }) => {
        // Guard to prevent infinite loops between actionToUrl and urlToAction.
        // Uses setTimeout (macrotask) so the flag stays set until the router has
        // fully processed the URL change, even in test environments with
        // synchronously-resolving mocks.
        const withUrlSyncGuard = <T,>(fn: () => T): T => {
            cache.isSyncingUrl = true
            const result = fn()
            setTimeout(() => {
                cache.isSyncingUrl = false
            }, 0)
            return result
        }

        const syncUrl = (): [
            string,
            Params,
            Record<string, any>,
            {
                replace: boolean
            },
        ] => {
            return withUrlSyncGuard(() =>
                syncSearchParams(router, (params: Params) => {
                    updateSearchParams(params, 'searchTerm', values.filters.searchTerm, '')
                    updateSearchParams(
                        params,
                        'filterGroup',
                        values.filters.filterGroup,
                        DEFAULT_UNIVERSAL_GROUP_FILTER
                    )
                    updateSearchParams(params, 'dateRange', values.filters.dateRange, DEFAULT_DATE_RANGE)
                    updateSearchParams(params, 'severityLevels', values.filters.severityLevels, DEFAULT_SEVERITY_LEVELS)
                    updateSearchParams(params, 'serviceNames', values.filters.serviceNames, DEFAULT_SERVICE_NAMES)
                    updateSearchParams(params, 'orderBy', values.orderBy, DEFAULT_ORDER_BY)
                    updateSearchParams(params, 'facetNameSearch', values.facetNameSearch, '')
                    return params
                })
            )
        }

        const clearLinkToLogId = (): ReturnType<typeof syncSearchParams> => {
            return withUrlSyncGuard(() =>
                syncSearchParams(router, (params: Params) => {
                    delete params.linkToLogId
                    return params
                })
            )
        }

        const clearInitialLogsLimit = (): [
            string,
            Params,
            Record<string, any>,
            {
                replace: boolean
            },
        ] => {
            return withUrlSyncGuard(() =>
                syncSearchParams(router, (params: Params) => {
                    updateSearchParams(params, 'initialLogsLimit', null, DEFAULT_INITIAL_LOGS_LIMIT)
                    return params
                })
            )
        }

        const syncActiveTab = (): ReturnType<typeof syncSearchParams> => {
            return withUrlSyncGuard(() =>
                syncSearchParams(router, (params: Params) => {
                    updateSearchParams(params, 'activeTab', values.activeTab, DEFAULT_ACTIVE_TAB)
                    return params
                })
            )
        }

        return {
            // initialLogsLimit is a one-shot override from "copy link to log" URLs.
            // It ensures the first fetch loads enough logs to include the linked log,
            // then resets to null so subsequent queries use the default page size.
            fetchLogsSuccess: () => clearInitialLogsLimit(),
            closeLogDetails: () => clearLinkToLogId(),
            clearLinkToLogId: () => clearLinkToLogId(),
            syncUrl: () => syncUrl(),
            setActiveTab: () => syncActiveTab(),
        }
    }),

    actions({
        setActiveTab: (activeTab: LogsSceneActiveTab) => ({ activeTab }),
        syncUrl: true,
        toggleAttributeBreakdown: (key: string) => ({ key }),
        setExpandedAttributeBreaksdowns: (expandedAttributeBreaksdowns: string[]) => ({ expandedAttributeBreaksdowns }),
        keepSqlEditorMounted: (editorTabId: string) => ({ editorTabId }),
    }),

    reducers({
        activeTab: [
            DEFAULT_ACTIVE_TAB as LogsSceneActiveTab,
            {
                setActiveTab: (_, { activeTab }) => activeTab,
            },
        ],
        expandedAttributeBreaksdowns: [
            [] as string[],
            {
                setExpandedAttributeBreaksdowns: (_, { expandedAttributeBreaksdowns }) => expandedAttributeBreaksdowns,
            },
        ],
    }),

    listeners(({ values, actions, cache }) => ({
        toggleAttributeBreakdown: ({ key }) => {
            const breakdowns = [...values.expandedAttributeBreaksdowns]
            const index = breakdowns.indexOf(key)
            index >= 0 ? breakdowns.splice(index, 1) : breakdowns.push(key)
            actions.setExpandedAttributeBreaksdowns(breakdowns)
        },
        handleQueryChange: () => {
            actions.pushToFilterHistory(values.filters)
            actions.syncUrl()
        },
        setOrderBy: () => {
            actions.syncUrl()
        },
        setFacetNameSearch: () => {
            actions.syncUrl()
        },
        keepSqlEditorMounted: ({ editorTabId }) => {
            if (cache.sqlEditorTabId === editorTabId) {
                return
            }
            cache.unmountSqlEditor?.()
            cache.sqlEditorTabId = editorTabId
            // Intentionally not cleaned up in beforeUnmount: keeps the embedded sqlEditorLogic
            // alive across navigation so the user's query survives leaving and re-entering /logs.
            cache.unmountSqlEditor = sqlEditorLogic({ tabId: editorTabId, mode: SQLEditorMode.Embedded }).mount()
        },
    })),
])
