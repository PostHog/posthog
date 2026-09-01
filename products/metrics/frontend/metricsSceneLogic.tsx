import { MakeLogicType, actions, connect, kea, listeners, path, reducers } from 'kea'
import { router, urlToAction } from 'kea-router'

import { syncSearchParams, updateSearchParams } from '@posthog/products-error-tracking/frontend/utils'

import { DEFAULT_UNIVERSAL_GROUP_FILTER } from 'lib/components/UniversalFilters/constants'
import { isUniversalGroupFilterLike } from 'lib/components/UniversalFilters/utils'
import { trackedActionToUrl } from 'lib/logic/scenes/trackedActionToUrl'
import { removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { objectsEqual } from 'lib/utils/objects'
import { parseTagsFilter } from 'lib/utils/url'
import { sqlEditorLogic } from 'scenes/data-warehouse/editor/sqlEditorLogic'
import { SQLEditorMode } from 'scenes/data-warehouse/editor/sqlEditorModes'
import { Params } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { UniversalFiltersGroup } from '~/types'

import { OtelMetricTypeEnumApi } from 'products/metrics/frontend/generated/api.schemas'

import {
    DEFAULT_AGGREGATION,
    DEFAULT_DATE_FROM,
    MAX_CLAUSES,
    METRIC_AGGREGATIONS,
    MetricAggregation,
    MetricsViewerClause,
    createViewerClause,
    isMetricAggregation,
    metricsViewerLogic,
    sanitizeFormulaInput,
    toKnownMetricType,
} from './components/metricsViewerLogic'

export const METRICS_SQL_EDITOR_TAB_ID = 'metrics-sql-editor'

export type MetricsSceneActiveTab = 'overview' | 'viewer' | 'sql' | 'fundamentals'
const VALID_ACTIVE_TABS: MetricsSceneActiveTab[] = ['overview', 'viewer', 'sql', 'fundamentals']
export const DEFAULT_ACTIVE_TAB: MetricsSceneActiveTab = 'overview'

// kea-router pre-parses JSON-looking params, so anything a user types into the URL can reach
// setFilterGroup — validate the whole tree or the filter selectors crash on `.values`/`in`.
// The viewer renders values[0] as a nested group, so the top level must hold groups only.
const isValidFilterValue = (value: any): boolean =>
    typeof value === 'object' && value !== null && (!isUniversalGroupFilterLike(value) || isValidInnerGroup(value))
const isValidInnerGroup = (group: any): boolean =>
    isUniversalGroupFilterLike(group) && Array.isArray(group.values) && group.values.every(isValidFilterValue)
const isValidFilterGroup = (group: any): group is UniversalFiltersGroup =>
    isUniversalGroupFilterLike(group) &&
    Array.isArray(group.values) &&
    group.values.length > 0 &&
    group.values.every(isValidInnerGroup)

// Legacy single-clause params, written for one plain clause so old links stay short
// and other products' link builders (metricsLinks.ts) keep working unchanged.
const LEGACY_VIEWER_PARAMS = ['metricName', 'metricType', 'aggregation', 'groupBy', 'filterGroup'] as const

// A clause's alias must satisfy the backend's identifier rules (formulas reference it).
const CLAUSE_NAME_PATTERN = /^[a-z][a-z0-9_]{0,63}$/

// Only the fields a link needs — no active index, no explicit-pick flag, defaults omitted.
const serializeViewerClause = (clause: MetricsViewerClause): Record<string, any> => ({
    name: clause.name,
    metricName: clause.metricName.trim(),
    aggregation: clause.aggregation,
    ...(clause.selectedMetricType ? { metricType: clause.selectedMetricType } : {}),
    ...(clause.groupByKeys.length ? { groupBy: clause.groupByKeys } : {}),
    ...(objectsEqual(clause.filterGroup, DEFAULT_UNIVERSAL_GROUP_FILTER) ? {} : { filterGroup: clause.filterGroup }),
})

// The `clauses` param is attacker-controlled JSON (kea-router pre-parses it), so every
// field is validated before it can reach the viewer; any invalid entry rejects the whole
// param, mirroring how a malformed legacy filterGroup is ignored.
const parseClausesParam = (raw: unknown): MetricsViewerClause[] | null => {
    let parsed = raw
    if (typeof raw === 'string') {
        try {
            parsed = JSON.parse(raw)
        } catch {
            return null
        }
    }
    if (!Array.isArray(parsed) || parsed.length === 0 || parsed.length > MAX_CLAUSES) {
        return null
    }
    const seenNames = new Set<string>()
    const clauses: MetricsViewerClause[] = []
    for (const item of parsed) {
        if (typeof item !== 'object' || item === null) {
            return null
        }
        const name = typeof item.name === 'string' && CLAUSE_NAME_PATTERN.test(item.name) ? item.name : null
        const metricName = typeof item.metricName === 'string' ? item.metricName : ''
        if (!name || seenNames.has(name) || !metricName.trim()) {
            return null
        }
        seenNames.add(name)
        if (!isMetricAggregation(item.aggregation)) {
            return null
        }
        const groupByKeys =
            Array.isArray(item.groupBy) && item.groupBy.every((key: unknown) => typeof key === 'string')
                ? (item.groupBy as string[])
                : []
        clauses.push({
            name,
            metricName,
            selectedMetricType: toKnownMetricType(typeof item.metricType === 'string' ? item.metricType : undefined),
            aggregation: item.aggregation,
            // An aggregation named in a link is a deliberate choice — the picker's
            // late type backfill must not override it with the recommendation.
            aggregationExplicitlySet: true,
            filterGroup: isValidFilterGroup(item.filterGroup) ? item.filterGroup : DEFAULT_UNIVERSAL_GROUP_FILTER,
            groupByKeys,
        })
    }
    return clauses
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface metricsSceneLogicValues {
    aggregation: MetricAggregation // metricsViewerLogic
    dateFrom: string | null // metricsViewerLogic
    dateTo: string | null // metricsViewerLogic
    filterGroup: UniversalFiltersGroup // metricsViewerLogic
    formula: string // metricsViewerLogic
    groupByKeys: string[] // metricsViewerLogic
    metricName: string // metricsViewerLogic
    selectedMetricType: OtelMetricTypeEnumApi | null // metricsViewerLogic
    viewerClauses: MetricsViewerClause[] // metricsViewerLogic
    activeTab: MetricsSceneActiveTab
    isRestoringFromUrl: boolean
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface metricsSceneLogicActions {
    duplicateClause: (index: number) => {
        index: number
    } // metricsViewerLogic
    removeClause: (index: number) => {
        index: number
    } // metricsViewerLogic
    setAggregation: (aggregation: MetricAggregation) => {
        aggregation: MetricAggregation
    } // metricsViewerLogic
    setClauseMetricType: (
        index: number,
        metricType: OtelMetricTypeEnumApi | null
    ) => {
        index: number
        metricType: OtelMetricTypeEnumApi | null
    } // metricsViewerLogic
    setClauseRecommendedAggregation: (
        index: number,
        aggregation: MetricAggregation
    ) => {
        aggregation: MetricAggregation
        index: number
    } // metricsViewerLogic
    setClauses: (
        clauses: MetricsViewerClause[],
        formula: string
    ) => {
        clauses: MetricsViewerClause[]
        formula: string
    } // metricsViewerLogic
    setDateFrom: (dateFrom: string | null) => {
        dateFrom: string | null
    } // metricsViewerLogic
    setDateTo: (dateTo: string | null) => {
        dateTo: string | null
    } // metricsViewerLogic
    setFilterGroup: (filterGroup: UniversalFiltersGroup) => {
        filterGroup: UniversalFiltersGroup
    } // metricsViewerLogic
    setFormula: (formula: string) => {
        formula: string
    } // metricsViewerLogic
    setGroupByKeys: (groupByKeys: string[]) => {
        groupByKeys: string[]
    } // metricsViewerLogic
    setMetricName: (metricName: string) => {
        metricName: string
    } // metricsViewerLogic
    setRecommendedAggregation: (aggregation: MetricAggregation) => {
        aggregation: MetricAggregation
    } // metricsViewerLogic
    setSelectedMetricType: (metricType: OtelMetricTypeEnumApi | null) => {
        metricType: OtelMetricTypeEnumApi | null
    } // metricsViewerLogic
    keepSqlEditorMounted: (editorTabId: string) => {
        editorTabId: string
    }
    setActiveTab: (activeTab: MetricsSceneActiveTab) => {
        activeTab: MetricsSceneActiveTab
    }
    setRestoringFromUrl: (restoring: boolean) => {
        restoring: boolean
    }
}

export type metricsSceneLogicType = MakeLogicType<metricsSceneLogicValues, metricsSceneLogicActions>

export const metricsSceneLogic = kea<metricsSceneLogicType>([
    path(['products', 'metrics', 'frontend', 'metricsSceneLogic']),
    // The scene owns ALL URL sync: metricsViewerLogic stays URL-free so it can be embedded
    // anywhere, and this logic translates URL params into its actions and its actions back
    // into URL writes. Mirrors the logsSceneLogic / tracingSceneLogic boundary.
    connect(() => ({
        values: [
            metricsViewerLogic,
            [
                'metricName',
                'selectedMetricType',
                'aggregation',
                'dateFrom',
                'dateTo',
                'groupByKeys',
                'filterGroup',
                'viewerClauses',
                'formula',
            ],
        ],
        actions: [
            metricsViewerLogic,
            [
                'setMetricName',
                'setSelectedMetricType',
                'setAggregation',
                'setRecommendedAggregation',
                'setDateFrom',
                'setDateTo',
                'setGroupByKeys',
                'setFilterGroup',
                'setClauses',
                'setFormula',
                'removeClause',
                'duplicateClause',
                'setClauseMetricType',
                'setClauseRecommendedAggregation',
            ],
        ],
    })),
    actions({
        setActiveTab: (activeTab: MetricsSceneActiveTab) => ({ activeTab }),
        setRestoringFromUrl: (restoring: boolean) => ({ restoring }),
        keepSqlEditorMounted: (editorTabId: string) => ({ editorTabId }),
    }),
    reducers({
        activeTab: [DEFAULT_ACTIVE_TAB as MetricsSceneActiveTab, { setActiveTab: (_, { activeTab }) => activeTab }],
        // True while URL params are being applied, so URL writes pause and usage tracking
        // can tell a restore from the user touching a control.
        isRestoringFromUrl: [false, { setRestoringFromUrl: (_, { restoring }) => restoring }],
    }),
    listeners(({ cache }) => ({
        keepSqlEditorMounted: ({ editorTabId }) => {
            if (cache.sqlEditorTabId === editorTabId) {
                return
            }
            cache.unmountSqlEditor?.()
            cache.sqlEditorTabId = editorTabId
            // Intentionally not cleaned up in beforeUnmount: keeps the embedded sqlEditorLogic
            // alive across navigation so the user's query survives leaving and re-entering /metrics.
            cache.unmountSqlEditor = sqlEditorLogic({ tabId: editorTabId, mode: SQLEditorMode.Embedded }).mount()
        },
    })),
    urlToAction(({ actions, values, cache }) => {
        const applyUrlParams = (_: any, params: Params): void => {
            if (cache.isSyncingUrl) {
                return
            }
            // The setters below (and their viewer-listener cascades) each write the URL;
            // syncUrl skips writes during the restore, or a mid-apply write built from
            // half-applied state would strip the params this pass has not consumed yet.
            actions.setRestoringFromUrl(true)
            try {
                const requested = params.activeTab
                if (
                    typeof requested === 'string' &&
                    VALID_ACTIVE_TABS.includes(requested as MetricsSceneActiveTab) &&
                    requested !== values.activeTab
                ) {
                    actions.setActiveTab(requested as MetricsSceneActiveTab)
                }
                const parsedClauses = params.clauses ? parseClausesParam(params.clauses) : null
                if (parsedClauses) {
                    const formula = typeof params.formula === 'string' ? sanitizeFormulaInput(params.formula) : ''
                    const currentClauses = values.viewerClauses.filter((clause) => clause.metricName.trim())
                    if (
                        formula !== values.formula ||
                        !objectsEqual(
                            parsedClauses.map(serializeViewerClause),
                            currentClauses.map(serializeViewerClause)
                        )
                    ) {
                        actions.setClauses(parsedClauses, formula)
                    }
                } else {
                    // A legacy (single-clause) link means "show this one metric": collapse
                    // any multi-clause state first, so the appliers below land on clause 'a'.
                    if (values.viewerClauses.length > 1) {
                        actions.setClauses([createViewerClause('a')], '')
                    } else if (values.formula) {
                        actions.setFormula('')
                    }
                    // metricName first: its listener latches the metric type and a recommended
                    // aggregation, which the explicit URL params below then override.
                    const metricName = params.metricName != null ? String(params.metricName) : ''
                    if (metricName !== values.metricName) {
                        actions.setMetricName(metricName)
                    }
                    const metricType = toKnownMetricType(
                        typeof params.metricType === 'string' ? params.metricType : undefined
                    )
                    if (metricType && metricType !== values.selectedMetricType) {
                        actions.setSelectedMetricType(metricType)
                    }
                    const aggregation =
                        typeof params.aggregation === 'string' &&
                        METRIC_AGGREGATIONS.includes(params.aggregation as MetricAggregation)
                            ? (params.aggregation as MetricAggregation)
                            : null
                    if (aggregation && aggregation !== values.aggregation) {
                        actions.setAggregation(aggregation)
                    } else if (!aggregation && !metricName && values.aggregation !== DEFAULT_AGGREGATION) {
                        // A bare URL resets to the clean-slate default. With a metric but no
                        // aggregation param (a hand-written link), the recommended aggregation
                        // latched by setMetricName stays.
                        actions.setAggregation(DEFAULT_AGGREGATION)
                    }
                    const groupByKeys = parseTagsFilter(params.groupBy) ?? []
                    if (!objectsEqual(groupByKeys, values.groupByKeys)) {
                        actions.setGroupByKeys(groupByKeys)
                    }
                    if (params.filterGroup) {
                        try {
                            const filterGroup =
                                typeof params.filterGroup === 'string'
                                    ? JSON.parse(params.filterGroup)
                                    : params.filterGroup
                            if (isValidFilterGroup(filterGroup) && !objectsEqual(filterGroup, values.filterGroup)) {
                                actions.setFilterGroup(filterGroup)
                            }
                        } catch {
                            // Ignore malformed filterGroup JSON in the URL
                        }
                    } else if (!objectsEqual(DEFAULT_UNIVERSAL_GROUP_FILTER, values.filterGroup)) {
                        actions.setFilterGroup(DEFAULT_UNIVERSAL_GROUP_FILTER)
                    }
                }
                const dateFrom =
                    typeof params.dateFrom === 'string' && params.dateFrom ? params.dateFrom : DEFAULT_DATE_FROM
                if (dateFrom !== values.dateFrom) {
                    actions.setDateFrom(dateFrom)
                }
                const dateTo = typeof params.dateTo === 'string' && params.dateTo ? params.dateTo : null
                if (dateTo !== values.dateTo) {
                    actions.setDateTo(dateTo)
                }
            } finally {
                actions.setRestoringFromUrl(false)
            }
        }
        return { [urls.metrics()]: applyUrlParams }
    }),
    trackedActionToUrl(({ values, cache }) => {
        const syncUrl = (): [string, Params, Record<string, any>, { replace: boolean }] | undefined => {
            // No writes during a restore (see applyUrlParams) or after navigating away —
            // an async cascade (e.g. the picker's late metric-type backfill) must not
            // splat metrics params onto another scene's URL.
            const pathname = removeProjectIdIfPresent(router.values.location.pathname).replace(/\/+$/, '')
            if (values.isRestoringFromUrl || pathname !== urls.metrics()) {
                return undefined
            }
            cache.isSyncingUrl = true
            const result = syncSearchParams(router, (params: Params) => {
                updateSearchParams(params, 'activeTab', values.activeTab, DEFAULT_ACTIVE_TAB)
                // A blank just-added row is unsaved work in progress, not link state.
                const namedClauses = values.viewerClauses.filter((clause) => clause.metricName.trim())
                const useClausesEncoding = namedClauses.length > 1 || (!!values.formula && namedClauses.length > 0)
                if (useClausesEncoding) {
                    // The two encodings must never disagree, so whichever one is written
                    // deletes the other's params.
                    params.clauses = namedClauses.map(serializeViewerClause)
                    updateSearchParams(params, 'formula', values.formula, '')
                    for (const legacyParam of LEGACY_VIEWER_PARAMS) {
                        delete params[legacyParam]
                    }
                } else {
                    delete params.clauses
                    delete params.formula
                    updateSearchParams(params, 'metricName', values.metricName, '')
                    updateSearchParams(params, 'metricType', values.selectedMetricType, null)
                    if (values.metricName) {
                        // Never dropped while a metric is picked: 'sum' is both the default and a
                        // valid explicit choice, so a link that omitted it would restore with the
                        // metric type's recommended aggregation instead of the one on screen.
                        params.aggregation = values.aggregation
                    } else {
                        delete params.aggregation
                    }
                    updateSearchParams(params, 'groupBy', values.groupByKeys, [] as string[])
                    updateSearchParams(params, 'filterGroup', values.filterGroup, DEFAULT_UNIVERSAL_GROUP_FILTER)
                }
                updateSearchParams(params, 'dateFrom', values.dateFrom, DEFAULT_DATE_FROM)
                updateSearchParams(params, 'dateTo', values.dateTo, null)
                return params
            })
            queueMicrotask(() => {
                cache.isSyncingUrl = false
            })
            return result
        }
        return {
            setActiveTab: () => syncUrl(),
            setMetricName: () => syncUrl(),
            setSelectedMetricType: () => syncUrl(),
            setAggregation: () => syncUrl(),
            setRecommendedAggregation: () => syncUrl(),
            setDateFrom: () => syncUrl(),
            setDateTo: () => syncUrl(),
            setGroupByKeys: () => syncUrl(),
            setFilterGroup: () => syncUrl(),
            setClauses: () => syncUrl(),
            setFormula: () => syncUrl(),
            removeClause: () => syncUrl(),
            duplicateClause: () => syncUrl(),
            setClauseMetricType: () => syncUrl(),
            setClauseRecommendedAggregation: () => syncUrl(),
        }
    }),
])
