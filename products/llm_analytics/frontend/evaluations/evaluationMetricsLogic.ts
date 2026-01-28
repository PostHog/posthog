import { actions, afterMount, connect, kea, listeners, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { dayjs } from 'lib/dayjs'

import { HogQLQuery, NodeKind, TrendsQuery } from '~/queries/schema/schema-general'
import { ChartDisplayType, HogQLMathType } from '~/types'

import { llmAnalyticsSharedLogic } from '../llmAnalyticsSharedLogic'
import { PASS_RATE_SUCCESS_THRESHOLD } from './components/EvaluationMetrics'
import type { evaluationMetricsLogicType } from './evaluationMetricsLogicType'
import { llmEvaluationsLogic } from './llmEvaluationsLogic'
import { EvaluationConfig } from './types'

const MIN_RUNS_FOR_FAILING_STATUS = 3

export interface EvaluationStats {
    evaluation_id: string
    runs_count: number
    applicable_count: number
    pass_count: number
    pass_rate: number
    applicability_rate: number
}

export interface SummaryMetrics {
    total_runs: number
    overall_pass_rate: number
    failing_evaluations_count: number
}

type RawStatsRow = [evaluation_id: string, runs_count: number, applicable_count: number, pass_count: number]

function getIntervalFromDateRange(dateFrom: string | null): 'hour' | 'day' {
    if (!dateFrom) {
        return 'day'
    }

    // Handle "today" formats
    if (dateFrom === 'dStart' || dateFrom === '-0d' || dateFrom === '-0dStart') {
        return 'hour'
    }

    // Handle relative date strings like "-24h", "-1d", "-7d"
    const match = dateFrom.match(/^-(\d+)([hdwmy])/i)
    if (match) {
        const value = parseInt(match[1])
        const unit = match[2].toLowerCase()
        const hoursMap: Record<string, number> = { h: 1, d: 24, w: 168, m: 720, y: 8760 }
        const hours = value * (hoursMap[unit] || 24)
        return hours <= 24 ? 'hour' : 'day'
    }

    // Handle absolute dates
    const duration = dayjs.duration(dayjs().diff(dayjs(dateFrom)))
    return duration.asDays() <= 1 ? 'hour' : 'day'
}

export const evaluationMetricsLogic = kea<evaluationMetricsLogicType>([
    path(['products', 'llm_analytics', 'frontend', 'evaluations', 'evaluationMetricsLogic']),

    connect({
        values: [llmEvaluationsLogic, ['evaluations'], llmAnalyticsSharedLogic, ['dateFilter']],
        actions: [llmAnalyticsSharedLogic, ['setDates']],
    }),

    actions({
        refreshMetrics: true,
    }),

    loaders(({ values }) => ({
        stats: [
            [] as EvaluationStats[],
            {
                loadStats: async () => {
                    const dateFrom = values.dateFilter.dateFrom || '-1d'
                    const dateTo = values.dateFilter.dateTo || null

                    const query: HogQLQuery = {
                        kind: NodeKind.HogQLQuery,
                        query: `
                            SELECT
                                properties.$ai_evaluation_id as evaluation_id,
                                count() as runs_count,
                                countIf(properties.$ai_evaluation_result IS NOT NULL) as applicable_count,
                                countIf(properties.$ai_evaluation_result = 1) as pass_count
                            FROM events
                            WHERE event = '$ai_evaluation' AND {filters}
                            GROUP BY evaluation_id
                        `,
                        filters: {
                            dateRange: {
                                date_from: dateFrom,
                                date_to: dateTo,
                            },
                        },
                    }

                    try {
                        const response = await api.query(query)

                        return (response.results || []).map((row: RawStatsRow) => {
                            const runs_count = row[1]
                            const applicable_count = row[2]
                            const pass_count = row[3]
                            // Pass rate excludes N/A results (uses applicable_count as denominator)
                            const pass_rate = applicable_count > 0 ? (pass_count / applicable_count) * 100 : 0
                            const applicability_rate = runs_count > 0 ? (applicable_count / runs_count) * 100 : 0

                            return {
                                evaluation_id: row[0],
                                runs_count,
                                applicable_count,
                                pass_count,
                                pass_rate: Math.round(pass_rate * 10) / 10,
                                applicability_rate: Math.round(applicability_rate * 10) / 10,
                            }
                        })
                    } catch (error) {
                        console.error('Failed to load stats:', error)
                        return []
                    }
                },
            },
        ],
    })),

    selectors({
        summaryMetrics: [
            (s) => [s.stats],
            (stats: EvaluationStats[]): SummaryMetrics => {
                const total_runs = stats.reduce((sum: number, stat) => sum + stat.runs_count, 0)
                const total_applicable = stats.reduce((sum: number, stat) => sum + stat.applicable_count, 0)
                const total_passes = stats.reduce((sum: number, stat) => sum + stat.pass_count, 0)
                // Overall pass rate excludes N/A results
                const overall_pass_rate = total_applicable > 0 ? (total_passes / total_applicable) * 100 : 0

                const failing_count = stats.filter((stat) => {
                    // Use applicable_count for minimum runs check
                    return (
                        stat.applicable_count >= MIN_RUNS_FOR_FAILING_STATUS &&
                        stat.pass_rate < PASS_RATE_SUCCESS_THRESHOLD
                    )
                }).length

                return {
                    total_runs,
                    overall_pass_rate: Math.round(overall_pass_rate * 10) / 10,
                    failing_evaluations_count: failing_count,
                }
            },
        ],

        evaluationsWithMetrics: [
            (s) => [s.evaluations, s.stats],
            (
                evaluations: EvaluationConfig[],
                stats: EvaluationStats[]
            ): Array<EvaluationConfig & { stats?: EvaluationStats }> => {
                const statsMap = new Map(stats.map((stat) => [stat.evaluation_id, stat]))

                return evaluations.map((evaluation) => ({
                    ...evaluation,
                    stats: statsMap.get(evaluation.id),
                }))
            },
        ],

        chartQuery: [
            (s) => [s.evaluations, s.dateFilter],
            (
                evaluations: EvaluationConfig[],
                dateFilter: { dateFrom: string | null; dateTo: string | null }
            ): TrendsQuery | null => {
                const enabledEvaluations = evaluations.filter((e) => e.enabled && !e.deleted)

                if (enabledEvaluations.length === 0) {
                    return null
                }

                const dateFrom = dateFilter.dateFrom || '-7d'
                const dateTo = dateFilter.dateTo || null
                const interval = getIntervalFromDateRange(dateFrom)

                return {
                    kind: NodeKind.TrendsQuery,
                    series: enabledEvaluations.slice(0, 10).map((evaluation) => ({
                        kind: NodeKind.EventsNode,
                        event: '$ai_evaluation',
                        custom_name: evaluation.name,
                        math: HogQLMathType.HogQL,
                        // Pass rate excludes N/A results, returns 0 if all results are N/A
                        math_hogql: `if(countIf(properties.$ai_evaluation_id = '${evaluation.id}' AND properties.$ai_evaluation_result IS NOT NULL) > 0, countIf(properties.$ai_evaluation_id = '${evaluation.id}' AND properties.$ai_evaluation_result = 1) / countIf(properties.$ai_evaluation_id = '${evaluation.id}' AND properties.$ai_evaluation_result IS NOT NULL) * 100, 0)`,
                    })),
                    trendsFilter: {
                        display: ChartDisplayType.ActionsLineGraph,
                    },
                    dateRange: {
                        date_from: dateFrom,
                        date_to: dateTo,
                    },
                    interval,
                }
            },
        ],
    }),

    listeners(({ actions }) => ({
        refreshMetrics: () => {
            actions.loadStats()
        },
        setDates: () => {
            actions.loadStats()
        },
    })),

    afterMount(({ actions }) => {
        actions.loadStats()
    }),
])
