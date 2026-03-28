import { afterMount, kea, key, listeners, path, props } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import { HogQLQuery, NodeKind } from '~/queries/schema/schema-general'

import type { generationTagRunsLogicType } from './generationTagRunsLogicType'
import { TagRun } from './tags/llmTaggerLogic'

export interface GenerationTagRunsLogicProps {
    generationEventId: string
}

export const generationTagRunsLogic = kea<generationTagRunsLogicType>([
    path(['products', 'llm_analytics', 'frontend', 'generationTagRunsLogic']),
    props({} as GenerationTagRunsLogicProps),
    key((props) => props.generationEventId),

    loaders(({ props }) => ({
        generationTagRuns: [
            [] as TagRun[],
            {
                loadGenerationTagRuns: async () => {
                    const query: HogQLQuery = {
                        kind: NodeKind.HogQLQuery,
                        query: `
                            SELECT
                                timestamp,
                                properties.$ai_tags as tags,
                                properties.$ai_tag_reasoning as reasoning,
                                properties.$ai_trace_id as trace_id,
                                properties.$ai_target_event_id as target_event_id,
                                properties.$ai_tagger_name as tagger_name
                            FROM events
                            WHERE event = '$ai_tag'
                              AND properties.$ai_target_event_id = '${props.generationEventId}'
                            ORDER BY timestamp DESC
                            LIMIT 50
                        `,
                    }
                    try {
                        const response = await api.query(query)
                        return (response.results || []).map((row: any[]) => ({
                            timestamp: row[0],
                            tags: typeof row[1] === 'string' ? JSON.parse(row[1]) : row[1] || [],
                            reasoning: row[2] || '',
                            trace_id: row[3] || '',
                            target_event_id: row[4] || '',
                            tagger_name: row[5] || '',
                        }))
                    } catch {
                        return []
                    }
                },
            },
        ],
    })),

    listeners(({ actions }) => ({
        refreshGenerationTagRuns: () => {
            actions.loadGenerationTagRuns()
        },
    })),

    afterMount(({ actions }) => {
        actions.loadGenerationTagRuns()
    }),
])
