import { actions, afterMount, kea, key, path, props, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { teamLogic } from 'scenes/teamLogic'

import { GenerationEvaluationRun } from './components/GenerationEvalRunsTable'
import type { generationEvaluationRunsLogicType } from './generationEvaluationRunsLogicType'

export interface GenerationEvaluationRunsLogicProps {
    generationEventId: string
}

export const generationEvaluationRunsLogic = kea<generationEvaluationRunsLogicType>([
    path(['products', 'llm_analytics', 'frontend', 'generationEvaluationRunsLogic']),
    props({} as GenerationEvaluationRunsLogicProps),
    key((props) => props.generationEventId),

    actions({
        loadGenerationEvaluationRuns: (generationEventId: string) => ({ generationEventId }),
    }),

    loaders(({ props }) => ({
        generationEvaluationRuns: [
            [] as GenerationEvaluationRun[],
            {
                loadGenerationEvaluationRuns: async () => {
                    const { currentTeamId } = teamLogic.values
                    if (!currentTeamId) {
                        return []
                    }

                    try {
                        // Query $ai_evaluation events for this generation from ClickHouse
                        const query = `
                            SELECT
                                uuid,
                                timestamp,
                                properties.$ai_evaluation_id as evaluation_id,
                                properties.$ai_evaluation_name as evaluation_name,
                                properties.$ai_evaluation_result as result,
                                properties.$ai_evaluation_reasoning as reasoning
                            FROM events
                            WHERE
                                event = '$ai_evaluation'
                                AND team_id = ${currentTeamId}
                                AND properties.$ai_target_event_id = '${props.generationEventId}'
                            ORDER BY timestamp DESC
                            LIMIT 100
                        `

                        const response = await api.query({ kind: 'HogQLQuery', query })

                        // Transform results to GenerationEvaluationRun format
                        const runs: GenerationEvaluationRun[] = (response.results || []).map((row: any) => ({
                            id: row[0],
                            evaluation_id: row[2],
                            evaluation_name: row[3] || 'Unknown Evaluation',
                            timestamp: row[1],
                            result: row[4],
                            reasoning: row[5] || 'No reasoning provided',
                            status: 'completed' as const,
                        }))

                        return runs
                    } catch (error) {
                        console.error('Failed to load generation evaluation runs:', error)
                        return []
                    }
                },
            },
        ],
    })),

    reducers({
        generationEventId: [
            '' as string,
            {
                loadGenerationEvaluationRuns: (_, { generationEventId }) => generationEventId,
            },
        ],
    }),

    afterMount(({ actions, props }) => {
        actions.loadGenerationEvaluationRuns(props.generationEventId)
    }),
])
