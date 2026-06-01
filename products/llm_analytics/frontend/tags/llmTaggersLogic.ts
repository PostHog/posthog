import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { teamLogic } from 'scenes/teamLogic'

import { HogQLQuery, NodeKind, TrendsQuery } from '~/queries/schema/schema-general'
import { ChartDisplayType } from '~/types'

import { llmAnalyticsSharedLogic } from '../llmAnalyticsSharedLogic'
import type { llmTaggersLogicType } from './llmTaggersLogicType'
import { defaultTaggerTemplates } from './templates'
import { getIntervalFromDateRange, Tagger } from './types'

export interface LLMTaggersLogicProps {
    tabId?: string
}

export interface TaggerRunStats {
    tagger_id: string
    runs_count: number
}

export interface TaggerTagCount {
    tagger_id: string
    tag_name: string
    count: number
}

type RawStatsRow = [tagger_id: string, runs_count: number]
type RawTagCountRow = [tagger_id: string, tag_name: string, count: number]

export const llmTaggersLogic = kea<llmTaggersLogicType>([
    path(['products', 'llm_analytics', 'taggers', 'llmTaggersLogic']),
    props({} as LLMTaggersLogicProps),
    key((props) => props.tabId ?? 'default'),
    connect(() => ({
        values: [featureFlagLogic, ['featureFlags'], llmAnalyticsSharedLogic, ['dateFilter']],
        actions: [teamLogic, ['addProductIntent'], llmAnalyticsSharedLogic, ['setDates']],
    })),

    actions({
        loadTaggers: true,
        loadTaggersSuccess: (taggers: Tagger[]) => ({ taggers }),
        toggleTaggerEnabled: (id: string) => ({ id }),
        setTaggersFilter: (filter: string) => ({ filter }),
    }),

    reducers({
        taggers: [
            [] as Tagger[],
            {
                loadTaggersSuccess: (_, { taggers }) => taggers,
            },
        ],
        taggersLoading: [
            false,
            {
                loadTaggers: () => true,
                loadTaggersSuccess: () => false,
            },
        ],
        taggersFilter: [
            '',
            {
                setTaggersFilter: (_, { filter }) => filter,
            },
        ],
        hasSeededDefaults: [
            false,
            {
                loadTaggersSuccess: () => true,
            },
        ],
    }),

    loaders(({ values }) => ({
        runStats: [
            [] as TaggerRunStats[],
            {
                loadRunStats: async () => {
                    const dateFrom = values.dateFilter.dateFrom || '-7d'
                    const dateTo = values.dateFilter.dateTo || null

                    const query: HogQLQuery = {
                        kind: NodeKind.HogQLQuery,
                        query: `
                            SELECT
                                properties.$ai_tagger_id as tagger_id,
                                count() as runs_count
                            FROM events
                            WHERE event = '$ai_tag' AND {filters}
                            GROUP BY tagger_id
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
                        return (response.results || []).map((row: RawStatsRow) => ({
                            tagger_id: row[0],
                            runs_count: row[1],
                        }))
                    } catch {
                        return []
                    }
                },
            },
        ],
        tagCounts: [
            [] as TaggerTagCount[],
            {
                loadTagCounts: async () => {
                    const dateFrom = values.dateFilter.dateFrom || '-7d'
                    const dateTo = values.dateFilter.dateTo || null

                    const query: HogQLQuery = {
                        kind: NodeKind.HogQLQuery,
                        query: `
                            SELECT
                                properties.$ai_tagger_id as tagger_id,
                                arrayJoin(JSONExtract(ifNull(properties.$ai_tags, '[]'), 'Array(String)')) as tag_name,
                                count() as cnt
                            FROM events
                            WHERE event = '$ai_tag' AND {filters}
                            GROUP BY tagger_id, tag_name
                            ORDER BY tagger_id, cnt DESC
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
                        return (response.results || []).map((row: RawTagCountRow) => ({
                            tagger_id: row[0],
                            tag_name: row[1],
                            count: row[2],
                        }))
                    } catch {
                        return []
                    }
                },
            },
        ],
    })),

    selectors({
        filteredTaggers: [
            (s) => [s.taggers, s.taggersFilter],
            (taggers: Tagger[], filter: string): Tagger[] => {
                if (!filter) {
                    return taggers
                }
                const lowerFilter = filter.toLowerCase()
                return taggers.filter(
                    (tagger) =>
                        tagger.name.toLowerCase().includes(lowerFilter) ||
                        tagger.description?.toLowerCase().includes(lowerFilter) ||
                        tagger.tagger_config.tags.some((tag) => tag.name.toLowerCase().includes(lowerFilter))
                )
            },
        ],

        runStatsMap: [
            (s) => [s.runStats],
            (runStats: TaggerRunStats[]): Record<string, number> => {
                const map: Record<string, number> = {}
                for (const stat of runStats) {
                    map[stat.tagger_id] = stat.runs_count
                }
                return map
            },
        ],

        tagDistributionMap: [
            (s) => [s.tagCounts],
            (tagCounts: TaggerTagCount[]): Record<string, Array<{ name: string; percent: number }>> => {
                const byTagger: Record<string, TaggerTagCount[]> = {}
                for (const tc of tagCounts) {
                    if (!byTagger[tc.tagger_id]) {
                        byTagger[tc.tagger_id] = []
                    }
                    byTagger[tc.tagger_id].push(tc)
                }
                const result: Record<string, Array<{ name: string; percent: number }>> = {}
                for (const [taggerId, counts] of Object.entries(byTagger)) {
                    const total = counts.reduce((sum, c) => sum + c.count, 0)
                    result[taggerId] = counts.map((c) => ({
                        name: c.tag_name,
                        percent: total > 0 ? Math.round((c.count / total) * 100) : 0,
                    }))
                }
                return result
            },
        ],

        totalRuns: [
            (s) => [s.runStats],
            (runStats: TaggerRunStats[]): number => runStats.reduce((sum, s) => sum + s.runs_count, 0),
        ],

        chartQuery: [
            (s) => [s.taggers, s.dateFilter],
            (taggers: Tagger[], dateFilter: { dateFrom: string | null; dateTo: string | null }): TrendsQuery | null => {
                if (taggers.filter((t) => t.enabled && !t.deleted).length === 0) {
                    return null
                }

                const dateFrom = dateFilter.dateFrom || '-7d'
                const dateTo = dateFilter.dateTo || null
                const interval = getIntervalFromDateRange(dateFrom)

                return {
                    kind: NodeKind.TrendsQuery,
                    series: [
                        {
                            kind: NodeKind.EventsNode,
                            event: '$ai_tag',
                            math: 'total' as any,
                        },
                    ],
                    breakdownFilter: {
                        // Bucket runs with no tags under "(no tag)" so taggers still appear
                        // on the chart when they ran but produced no matches.
                        breakdown:
                            "concat(properties.$ai_tagger_name, ' — ', arrayJoin(if(length(JSONExtract(ifNull(properties.$ai_tags, '[]'), 'Array(String)')) = 0, ['(no tag)'], JSONExtract(ifNull(properties.$ai_tags, '[]'), 'Array(String)'))))",
                        breakdown_type: 'hogql',
                    },
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

    listeners(({ actions, values }) => ({
        loadTaggers: async () => {
            const response = await api.get('api/environments/@current/taggers/')
            if (response.results.length === 0 && !values.hasSeededDefaults) {
                for (const template of defaultTaggerTemplates) {
                    await api.create('api/environments/@current/taggers/', {
                        name: template.name,
                        description: template.description,
                        enabled: false,
                        tagger_config: template.tagger_config,
                        conditions: [{ id: `cond-${Date.now()}`, rollout_percentage: 100, properties: [] }],
                    })
                }
                const seeded = await api.get('api/environments/@current/taggers/')
                actions.loadTaggersSuccess(seeded.results)
            } else {
                actions.loadTaggersSuccess(response.results)
            }
        },
        loadTaggersSuccess: () => {
            actions.loadRunStats()
            actions.loadTagCounts()
        },
        toggleTaggerEnabled: async ({ id }, breakpoint) => {
            const tagger = values.taggers.find((t) => t.id === id)
            if (!tagger) {
                return
            }
            await api.update(`api/environments/@current/taggers/${id}/`, { enabled: !tagger.enabled })
            await breakpoint(100)
            actions.loadTaggers()
        },
        setDates: () => {
            actions.loadRunStats()
            actions.loadTagCounts()
        },
    })),

    afterMount(({ actions, values }) => {
        // Default to last 24h if no date range has been set via URL
        if (values.dateFilter.dateFrom === '-1h') {
            actions.setDates('-24h', null)
        }
        actions.loadTaggers()
    }),
])
