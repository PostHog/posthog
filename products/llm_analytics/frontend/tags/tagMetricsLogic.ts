import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import { HogQLQuery, NodeKind, TrendsQuery } from '~/queries/schema/schema-general'
import { ChartDisplayType, PropertyFilterType, PropertyOperator } from '~/types'

import { llmTaggersLogic } from './llmTaggersLogic'
import type { tagMetricsLogicType } from './tagMetricsLogicType'
import { getIntervalFromDateRange, Tagger } from './types'

export interface TagStats {
    tagger_id: string
    runs_count: number
    tag_counts: Record<string, number>
}

export interface TagSummaryMetrics {
    total_runs: number
    top_tags: { tag: string; count: number }[]
    unique_tags_applied: number
}

export interface TagMetricsLogicProps {
    tabId?: string
}

export const tagMetricsLogic = kea<tagMetricsLogicType>([
    path(['products', 'llm_analytics', 'frontend', 'tags', 'tagMetricsLogic']),
    props({} as TagMetricsLogicProps),
    key((props) => props.tabId ?? 'default'),

    connect((props: TagMetricsLogicProps) => ({
        values: [llmTaggersLogic({ tabId: props.tabId }), ['taggers']],
    })),

    actions({
        setDates: (dateFrom: string | null, dateTo: string | null) => ({ dateFrom, dateTo }),
    }),

    reducers({
        dateFilter: [
            { dateFrom: '-7d' as string | null, dateTo: null as string | null },
            {
                setDates: (_, { dateFrom, dateTo }) => ({ dateFrom, dateTo }),
            },
        ],
    }),

    loaders(({ values }) => ({
        tagStats: [
            [] as { tag: string; count: number }[],
            {
                loadTagStats: async () => {
                    const dateFrom = values.dateFilter.dateFrom || '-7d'
                    const dateTo = values.dateFilter.dateTo || null

                    const query: HogQLQuery = {
                        kind: NodeKind.HogQLQuery,
                        query: `
                            SELECT
                                tag,
                                count() as cnt
                            FROM events
                            ARRAY JOIN JSONExtractArrayRaw(properties, '$ai_tags') as tag
                            WHERE event = '$ai_tag' AND {filters}
                            GROUP BY tag
                            ORDER BY cnt DESC
                            LIMIT 50
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
                        return (response.results || []).map((row: [string, number]) => ({
                            tag: row[0].replace(/^"|"$/g, ''),
                            count: row[1],
                        }))
                    } catch (error) {
                        console.error('Failed to load tag stats:', error)
                        return []
                    }
                },
            },
        ],
        totalRuns: [
            0,
            {
                loadTotalRuns: async () => {
                    const dateFrom = values.dateFilter.dateFrom || '-7d'
                    const dateTo = values.dateFilter.dateTo || null

                    const query: HogQLQuery = {
                        kind: NodeKind.HogQLQuery,
                        query: `
                            SELECT count() as cnt
                            FROM events
                            WHERE event = '$ai_tag' AND {filters}
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
                        return response.results?.[0]?.[0] ?? 0
                    } catch {
                        return 0
                    }
                },
            },
        ],
    })),

    selectors({
        summaryMetrics: [
            (s) => [s.tagStats, s.totalRuns],
            (tagStats: { tag: string; count: number }[], totalRuns: number): TagSummaryMetrics => {
                return {
                    total_runs: totalRuns,
                    top_tags: tagStats.slice(0, 10),
                    unique_tags_applied: tagStats.length,
                }
            },
        ],

        enabledTaggerCount: [
            (s) => [s.taggers],
            (taggers: Tagger[]): number => taggers.filter((t) => t.enabled && !t.deleted).length,
        ],

        chartQuery: [
            (s) => [s.tagStats, s.dateFilter],
            (
                tagStats: { tag: string; count: number }[],
                dateFilter: { dateFrom: string | null; dateTo: string | null }
            ): TrendsQuery | null => {
                if (tagStats.length === 0) {
                    return null
                }

                const dateFrom = dateFilter.dateFrom || '-7d'
                const dateTo = dateFilter.dateTo || null
                const interval = getIntervalFromDateRange(dateFrom)

                const topTags = tagStats.slice(0, 10)

                return {
                    kind: NodeKind.TrendsQuery,
                    series: topTags.map((tagStat) => ({
                        kind: NodeKind.EventsNode,
                        event: '$ai_tag',
                        custom_name: tagStat.tag,
                        properties: [
                            {
                                key: '$ai_tags',
                                value: tagStat.tag,
                                operator: PropertyOperator.IContains,
                                type: PropertyFilterType.Event,
                            },
                        ],
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
        setDates: () => {
            actions.loadTagStats()
            actions.loadTotalRuns()
        },
    })),

    afterMount(({ actions }) => {
        actions.loadTagStats()
        actions.loadTotalRuns()
    }),
])
