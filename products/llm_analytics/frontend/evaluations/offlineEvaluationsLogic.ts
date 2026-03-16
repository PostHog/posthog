import { actions, afterMount, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import api from 'lib/api'
import { tabAwareActionToUrl } from 'lib/logic/scenes/tabAwareActionToUrl'
import { tabAwareUrlToAction } from 'lib/logic/scenes/tabAwareUrlToAction'
import { dateStringToDayJs, isValidRelativeOrAbsoluteDate } from 'lib/utils'
import { removeProjectIdIfPresent } from 'lib/utils/router-utils'
import { urls } from 'scenes/urls'

import { hogql } from '~/queries/utils'

import type { offlineEvaluationsLogicType } from './offlineEvaluationsLogicType'

const OFFLINE_EXPERIMENTS_LIMIT = 200
const OFFLINE_EXPERIMENT_ITEMS_LIMIT = 20000
const INITIAL_OFFLINE_DATE_FROM = 'dStart' as string | null
const INITIAL_OFFLINE_DATE_TO = null as string | null

const EXPERIMENT_ID_EXPRESSION = "nullIf(properties.$ai_experiment_id, '')"
const EXPERIMENT_NAME_EXPRESSION = "nullIf(properties.$ai_experiment_name, '')"
const EXPERIMENT_ITEM_ID_EXPRESSION = "nullIf(properties.$ai_experiment_item_id, '')"
const METRIC_NAME_EXPRESSION = "nullIf(properties.$ai_metric_name, '')"
const METRIC_VERSION_EXPRESSION = "nullIf(properties.$ai_metric_version, '')"

type HogQLPrimitive = string | number | boolean | null

type RawOfflineExperimentRow = [
    experiment_id: HogQLPrimitive,
    experiment_name: HogQLPrimitive,
    first_seen_at: HogQLPrimitive,
    last_seen_at: HogQLPrimitive,
    events_count: HogQLPrimitive,
    items_count: HogQLPrimitive,
    metric_pairs_count: HogQLPrimitive,
]

type RawOfflineExperimentMetricRow = [
    item_id: HogQLPrimitive,
    experiment_item_name: HogQLPrimitive,
    experiment_name: HogQLPrimitive,
    metric_name: HogQLPrimitive,
    metric_version: HogQLPrimitive,
    status: HogQLPrimitive,
    score: HogQLPrimitive,
    score_min: HogQLPrimitive,
    score_max: HogQLPrimitive,
    result_type: HogQLPrimitive,
    reasoning: HogQLPrimitive,
    trace_id: HogQLPrimitive,
    dataset_id: HogQLPrimitive,
    dataset_item_id: HogQLPrimitive,
    ai_input: HogQLPrimitive,
    ai_output: HogQLPrimitive,
    ai_expected: HogQLPrimitive,
    last_seen_at: HogQLPrimitive,
]

export interface OfflineEvaluationsLogicProps {
    tabId?: string
}

export interface OfflineExperiment {
    experimentId: string
    experimentName: string | null
    firstSeenAt: string | null
    lastSeenAt: string | null
    eventsCount: number
    itemsCount: number
    metricPairsCount: number
}

export interface OfflineMetricColumn {
    key: string
    metricName: string
    metricVersion: string
}

export interface OfflineMetricValue {
    status: string | null
    score: number | null
    scoreMin: number | null
    scoreMax: number | null
    resultType: string | null
    reasoning: string | null
    traceId: string | null
}

export interface OfflineExperimentItem {
    itemId: string
    itemName: string | null
    experimentName: string | null
    traceId: string | null
    datasetId: string | null
    datasetItemId: string | null
    input: string | null
    output: string | null
    expected: string | null
    lastSeenAt: string | null
    metrics: Record<string, OfflineMetricValue>
}

export interface OfflineExperimentData {
    items: OfflineExperimentItem[]
    metricColumns: OfflineMetricColumn[]
}

interface OfflineDateFilter {
    dateFrom: string | null
    dateTo: string | null
}

function getEmptyOfflineExperimentData(): OfflineExperimentData {
    return {
        items: [],
        metricColumns: [],
    }
}

function getOfflineDateClauses(dateFilter: OfflineDateFilter): { dateFromClause: string; dateToClause: string } {
    const parsedDateFrom = dateFilter.dateFrom ? dateStringToDayJs(dateFilter.dateFrom) : null
    const parsedDateTo = dateFilter.dateTo ? dateStringToDayJs(dateFilter.dateTo) : null

    return {
        dateFromClause: parsedDateFrom
            ? `AND timestamp >= parseDateTimeBestEffort('${parsedDateFrom.toISOString()}')`
            : '',
        dateToClause: parsedDateTo ? `AND timestamp <= parseDateTimeBestEffort('${parsedDateTo.toISOString()}')` : '',
    }
}

function getOfflineDateFilterFromSearchParams(searchParams: Record<string, unknown>): OfflineDateFilter {
    const dateFromParam = searchParams.offline_date_from
    const dateToParam = searchParams.offline_date_to

    return {
        dateFrom:
            typeof dateFromParam === 'string' && isValidRelativeOrAbsoluteDate(dateFromParam)
                ? dateFromParam
                : INITIAL_OFFLINE_DATE_FROM,
        dateTo:
            typeof dateToParam === 'string' && isValidRelativeOrAbsoluteDate(dateToParam)
                ? dateToParam
                : INITIAL_OFFLINE_DATE_TO,
    }
}

function isOnOfflineEvaluationsRoute(pathname: string): boolean {
    const normalizedPath = removeProjectIdIfPresent(pathname)
    const offlinePath = urls.llmAnalyticsOfflineEvaluations()
    return normalizedPath === offlinePath || normalizedPath.startsWith(`${offlinePath}/`)
}

function asString(value: HogQLPrimitive): string | null {
    if (value === null || value === undefined) {
        return null
    }
    const stringValue = String(value).trim()
    return stringValue.length > 0 ? stringValue : null
}

function asNumber(value: HogQLPrimitive): number {
    if (typeof value === 'number') {
        return Number.isFinite(value) ? value : 0
    }

    if (typeof value === 'string') {
        const parsed = Number(value)
        return Number.isFinite(parsed) ? parsed : 0
    }

    return 0
}

function asNumberOrNull(value: HogQLPrimitive): number | null {
    if (typeof value === 'number') {
        return Number.isFinite(value) ? value : null
    }

    if (typeof value === 'string') {
        const parsed = Number(value)
        return Number.isFinite(parsed) ? parsed : null
    }

    return null
}

function compareNullableTimestampsDesc(left: string | null, right: string | null): number {
    if (left === right) {
        return 0
    }
    if (!left) {
        return 1
    }
    if (!right) {
        return -1
    }

    const leftTimestamp = Date.parse(left)
    const rightTimestamp = Date.parse(right)

    if (!Number.isNaN(leftTimestamp) && !Number.isNaN(rightTimestamp)) {
        return rightTimestamp - leftTimestamp
    }

    return right.localeCompare(left)
}

function metricKey(metricName: string, metricVersion: string): string {
    return `${metricName}::${metricVersion}`
}

export function mapOfflineExperiments(rows: RawOfflineExperimentRow[]): OfflineExperiment[] {
    return rows
        .map((row) => {
            const experimentId = asString(row[0])
            if (!experimentId) {
                return null
            }

            return {
                experimentId,
                experimentName: asString(row[1]),
                firstSeenAt: asString(row[2]),
                lastSeenAt: asString(row[3]),
                eventsCount: asNumber(row[4]),
                itemsCount: asNumber(row[5]),
                metricPairsCount: asNumber(row[6]),
            }
        })
        .filter((experiment): experiment is OfflineExperiment => experiment !== null)
}

export function mapOfflineExperimentItems(rows: RawOfflineExperimentMetricRow[]): OfflineExperimentData {
    const itemsById = new Map<string, OfflineExperimentItem>()
    const metricColumnsByKey = new Map<string, OfflineMetricColumn>()

    for (const row of rows) {
        const itemId = asString(row[0])
        if (!itemId) {
            continue
        }

        const itemName = asString(row[1])
        const experimentName = asString(row[2])
        const metricName = asString(row[3])
        const metricVersion = asString(row[4])

        const traceId = asString(row[11])
        const datasetId = asString(row[12])
        const datasetItemId = asString(row[13])
        const input = asString(row[14])
        const output = asString(row[15])
        const expected = asString(row[16])
        const rowLastSeenAt = asString(row[17])

        const existing = itemsById.get(itemId)
        const currentItem: OfflineExperimentItem = existing
            ? {
                  ...existing,
                  itemName: existing.itemName ?? itemName,
                  experimentName: existing.experimentName ?? experimentName,
                  traceId: existing.traceId ?? traceId,
                  datasetId: existing.datasetId ?? datasetId,
                  datasetItemId: existing.datasetItemId ?? datasetItemId,
                  input: existing.input ?? input,
                  output: existing.output ?? output,
                  expected: existing.expected ?? expected,
                  lastSeenAt:
                      compareNullableTimestampsDesc(existing.lastSeenAt, rowLastSeenAt) <= 0
                          ? existing.lastSeenAt
                          : rowLastSeenAt,
              }
            : {
                  itemId,
                  itemName,
                  experimentName,
                  traceId,
                  datasetId,
                  datasetItemId,
                  input,
                  output,
                  expected,
                  lastSeenAt: rowLastSeenAt,
                  metrics: {},
              }

        if (metricName && metricVersion) {
            const key = metricKey(metricName, metricVersion)

            metricColumnsByKey.set(key, {
                key,
                metricName,
                metricVersion,
            })

            currentItem.metrics[key] = {
                status: asString(row[5]),
                score: asNumberOrNull(row[6]),
                scoreMin: asNumberOrNull(row[7]),
                scoreMax: asNumberOrNull(row[8]),
                resultType: asString(row[9]),
                reasoning: asString(row[10]),
                traceId,
            }
        }

        itemsById.set(itemId, currentItem)
    }

    return {
        items: Array.from(itemsById.values()).sort((left, right) =>
            compareNullableTimestampsDesc(left.lastSeenAt, right.lastSeenAt)
        ),
        metricColumns: Array.from(metricColumnsByKey.values()).sort((left, right) => {
            const nameComparison = left.metricName.localeCompare(right.metricName)
            if (nameComparison !== 0) {
                return nameComparison
            }
            return left.metricVersion.localeCompare(right.metricVersion)
        }),
    }
}

export const offlineEvaluationsLogic = kea<offlineEvaluationsLogicType>([
    path(['products', 'llm_analytics', 'frontend', 'evaluations', 'offlineEvaluationsLogic']),
    props({} as OfflineEvaluationsLogicProps),
    key((props) => props.tabId ?? 'default'),

    actions({
        refreshOfflineEvaluations: true,
        setOfflineDates: (dateFrom: string | null, dateTo: string | null) => ({ dateFrom, dateTo }),
        setOfflineExperimentsFilter: (filter: string) => ({ filter }),
        setOfflineExperimentItemsFilter: (filter: string) => ({ filter }),
        selectExperiment: (experimentId: string) => ({ experimentId }),
        clearSelectedExperiment: true,
    }),

    reducers({
        selectedExperimentId: [
            null as string | null,
            {
                selectExperiment: (_, { experimentId }) => experimentId,
                clearSelectedExperiment: () => null,
            },
        ],

        offlineExperimentsFilter: [
            '',
            {
                setOfflineExperimentsFilter: (_, { filter }) => filter,
            },
        ],

        offlineDateFilter: [
            {
                dateFrom: INITIAL_OFFLINE_DATE_FROM,
                dateTo: INITIAL_OFFLINE_DATE_TO,
            } as { dateFrom: string | null; dateTo: string | null },
            {
                setOfflineDates: (_, { dateFrom, dateTo }) => ({ dateFrom, dateTo }),
            },
        ],

        offlineExperimentItemsFilter: [
            '',
            {
                setOfflineExperimentItemsFilter: (_, { filter }) => filter,
                selectExperiment: () => '',
                clearSelectedExperiment: () => '',
            },
        ],
    }),

    loaders(({ values }) => ({
        offlineExperiments: [
            [] as OfflineExperiment[],
            {
                loadOfflineExperiments: async () => {
                    const { dateFromClause, dateToClause } = getOfflineDateClauses(values.offlineDateFilter)

                    try {
                        const response = await api.queryHogQL(
                            hogql`
                                SELECT
                                    ${hogql.raw(EXPERIMENT_ID_EXPRESSION)} as experiment_id,
                                    argMax(${hogql.raw(EXPERIMENT_NAME_EXPRESSION)}, timestamp) as experiment_name,
                                    min(timestamp) as first_seen_at,
                                    max(timestamp) as last_seen_at,
                                    count() as events_count,
                                    uniqExactIf(
                                        ${hogql.raw(EXPERIMENT_ITEM_ID_EXPRESSION)},
                                        ${hogql.raw(EXPERIMENT_ITEM_ID_EXPRESSION)} IS NOT NULL
                                    ) as items_count,
                                    uniqExactIf(
                                        tuple(
                                            ${hogql.raw(METRIC_NAME_EXPRESSION)},
                                            ${hogql.raw(METRIC_VERSION_EXPRESSION)}
                                        ),
                                        ${hogql.raw(METRIC_NAME_EXPRESSION)} IS NOT NULL
                                        AND ${hogql.raw(METRIC_VERSION_EXPRESSION)} IS NOT NULL
                                    ) as metric_pairs_count
                                FROM events
                                WHERE
                                    event = '$ai_evaluation'
                                    AND ${hogql.raw(EXPERIMENT_ID_EXPRESSION)} IS NOT NULL
                                    ${hogql.raw(dateFromClause)}
                                    ${hogql.raw(dateToClause)}
                                GROUP BY experiment_id
                                ORDER BY last_seen_at DESC
                                LIMIT ${OFFLINE_EXPERIMENTS_LIMIT}
                            `,
                            { productKey: 'llm_analytics', scene: 'LLMAnalyticsEvaluations' }
                        )

                        return mapOfflineExperiments((response.results || []) as RawOfflineExperimentRow[])
                    } catch (error) {
                        console.error('Failed to load offline evaluation experiments:', error)
                        return []
                    }
                },
            },
        ],

        selectedExperimentData: [
            getEmptyOfflineExperimentData(),
            {
                loadSelectedExperimentData: async (payload: { experimentId?: string } = {}) => {
                    const { experimentId } = payload
                    const selectedExperimentId = experimentId ?? values.selectedExperimentId

                    if (!selectedExperimentId) {
                        return getEmptyOfflineExperimentData()
                    }

                    const { dateFromClause, dateToClause } = getOfflineDateClauses(values.offlineDateFilter)

                    try {
                        const response = await api.queryHogQL(
                            hogql`
                                SELECT
                                    ${hogql.raw(EXPERIMENT_ITEM_ID_EXPRESSION)} as item_id,
                                    argMax(properties.$ai_experiment_item_name, timestamp) as experiment_item_name,
                                    argMax(properties.$ai_experiment_name, timestamp) as experiment_name,
                                    ${hogql.raw(METRIC_NAME_EXPRESSION)} as metric_name,
                                    ${hogql.raw(METRIC_VERSION_EXPRESSION)} as metric_version,
                                    argMax(properties.$ai_status, timestamp) as status,
                                    argMax(properties.$ai_score, timestamp) as score,
                                    argMax(properties.$ai_score_min, timestamp) as score_min,
                                    argMax(properties.$ai_score_max, timestamp) as score_max,
                                    argMax(properties.$ai_result_type, timestamp) as result_type,
                                    argMax(properties.$ai_reasoning, timestamp) as reasoning,
                                    argMax(properties.$ai_trace_id, timestamp) as trace_id,
                                    argMax(properties.$ai_dataset_id, timestamp) as dataset_id,
                                    argMax(properties.$ai_dataset_item_id, timestamp) as dataset_item_id,
                                    argMax(properties.$ai_input, timestamp) as ai_input,
                                    argMax(properties.$ai_output, timestamp) as ai_output,
                                    argMax(properties.$ai_expected, timestamp) as ai_expected,
                                    max(timestamp) as last_seen_at
                                FROM events
                                WHERE
                                    event = '$ai_evaluation'
                                    AND properties.$ai_experiment_id = ${selectedExperimentId}
                                    AND ${hogql.raw(EXPERIMENT_ITEM_ID_EXPRESSION)} IS NOT NULL
                                    ${hogql.raw(dateFromClause)}
                                    ${hogql.raw(dateToClause)}
                                GROUP BY item_id, metric_name, metric_version
                                ORDER BY last_seen_at DESC
                                LIMIT ${OFFLINE_EXPERIMENT_ITEMS_LIMIT}
                            `,
                            { productKey: 'llm_analytics', scene: 'LLMAnalyticsEvaluations' }
                        )

                        return mapOfflineExperimentItems((response.results || []) as RawOfflineExperimentMetricRow[])
                    } catch (error) {
                        console.error('Failed to load offline evaluation experiment items:', error)
                        return getEmptyOfflineExperimentData()
                    }
                },
            },
        ],
    })),

    selectors({
        selectedExperiment: [
            (s) => [s.offlineExperiments, s.selectedExperimentId],
            (offlineExperiments: OfflineExperiment[], selectedExperimentId: string | null) =>
                offlineExperiments.find((experiment) => experiment.experimentId === selectedExperimentId) || null,
        ],

        filteredOfflineExperiments: [
            (s) => [s.offlineExperiments, s.offlineExperimentsFilter],
            (offlineExperiments: OfflineExperiment[], filter: string) => {
                const normalizedFilter = filter.trim().toLowerCase()
                if (!normalizedFilter) {
                    return offlineExperiments
                }

                return offlineExperiments.filter(
                    (experiment) =>
                        experiment.experimentId.toLowerCase().includes(normalizedFilter) ||
                        experiment.experimentName?.toLowerCase().includes(normalizedFilter)
                )
            },
        ],

        offlineMetricColumns: [
            (s) => [s.selectedExperimentData],
            (selectedExperimentData) => selectedExperimentData.metricColumns,
        ],

        filteredOfflineExperimentItems: [
            (s) => [s.selectedExperimentData, s.offlineExperimentItemsFilter],
            (selectedExperimentData: OfflineExperimentData, filter: string) => {
                const normalizedFilter = filter.trim().toLowerCase()
                if (!normalizedFilter) {
                    return selectedExperimentData.items
                }

                return selectedExperimentData.items.filter((item) => {
                    const candidateStrings = [
                        item.itemId,
                        item.itemName,
                        item.experimentName,
                        item.traceId,
                        item.datasetId,
                        item.datasetItemId,
                        item.input,
                        item.output,
                        item.expected,
                    ]

                    const reasoningMatches = Object.values(item.metrics).some((metric) =>
                        metric.reasoning?.toLowerCase().includes(normalizedFilter)
                    )
                    const traceMatches = Object.values(item.metrics).some((metric) =>
                        metric.traceId?.toLowerCase().includes(normalizedFilter)
                    )

                    return (
                        reasoningMatches ||
                        traceMatches ||
                        candidateStrings.some((value) => value?.toLowerCase().includes(normalizedFilter))
                    )
                })
            },
        ],
    }),

    listeners(({ actions, values }) => {
        const loadOfflineData = (): void => {
            actions.loadOfflineExperiments()
            if (values.selectedExperimentId) {
                actions.loadSelectedExperimentData({ experimentId: values.selectedExperimentId })
            }
        }

        return {
            selectExperiment: ({ experimentId }) => {
                actions.loadSelectedExperimentData({ experimentId })
            },

            setOfflineDates: () => {
                loadOfflineData()
            },

            clearSelectedExperiment: () => {
                actions.loadSelectedExperimentDataSuccess(getEmptyOfflineExperimentData())
            },

            refreshOfflineEvaluations: () => {
                loadOfflineData()
            },

            loadOfflineExperimentsSuccess: ({ offlineExperiments }) => {
                if (
                    values.selectedExperimentId &&
                    !offlineExperiments.some((experiment) => experiment.experimentId === values.selectedExperimentId)
                ) {
                    actions.clearSelectedExperiment()
                }
            },
        }
    }),

    tabAwareUrlToAction(({ actions, values }) => ({
        [urls.llmAnalyticsEvaluations()]: () => {
            if (values.selectedExperimentId) {
                actions.clearSelectedExperiment()
            }
        },
        [urls.llmAnalyticsOfflineEvaluationExperiment(':experimentId', false)]: ({ experimentId }, searchParams) => {
            if (experimentId && experimentId !== values.selectedExperimentId) {
                actions.selectExperiment(experimentId)
            }

            const { dateFrom, dateTo } = getOfflineDateFilterFromSearchParams(searchParams)

            if (dateFrom !== values.offlineDateFilter.dateFrom || dateTo !== values.offlineDateFilter.dateTo) {
                actions.setOfflineDates(dateFrom, dateTo)
            }
        },
        [urls.llmAnalyticsOfflineEvaluations()]: (_, searchParams) => {
            if (values.selectedExperimentId) {
                actions.clearSelectedExperiment()
            }

            const { dateFrom, dateTo } = getOfflineDateFilterFromSearchParams(searchParams)

            if (dateFrom !== values.offlineDateFilter.dateFrom || dateTo !== values.offlineDateFilter.dateTo) {
                actions.setOfflineDates(dateFrom, dateTo)
            }
        },
    })),

    tabAwareActionToUrl(() => ({
        setOfflineDates: ({ dateFrom, dateTo }) => {
            if (!isOnOfflineEvaluationsRoute(router.values.location.pathname)) {
                return undefined
            }

            return [
                router.values.location.pathname,
                {
                    ...router.values.searchParams,
                    offline_date_from: dateFrom === INITIAL_OFFLINE_DATE_FROM ? undefined : dateFrom || undefined,
                    offline_date_to: dateTo || undefined,
                },
            ]
        },
        selectExperiment: ({ experimentId }) => [
            urls.llmAnalyticsOfflineEvaluationExperiment(experimentId),
            {
                ...router.values.searchParams,
                tab: undefined,
                experiment: undefined,
            },
        ],
        clearSelectedExperiment: () => {
            if (!isOnOfflineEvaluationsRoute(router.values.location.pathname)) {
                return undefined
            }

            return [
                urls.llmAnalyticsOfflineEvaluations(),
                {
                    ...router.values.searchParams,
                    tab: undefined,
                    experiment: undefined,
                },
            ]
        },
    })),

    afterMount(({ actions }) => {
        actions.loadOfflineExperiments()
    }),
])
