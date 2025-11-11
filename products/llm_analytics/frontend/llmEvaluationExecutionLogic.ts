import { actions, connect, kea, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { teamLogic } from 'scenes/teamLogic'

import type { llmEvaluationExecutionLogicType } from './llmEvaluationExecutionLogicType'

export const llmEvaluationExecutionLogic = kea<llmEvaluationExecutionLogicType>([
    path(['products', 'llm_analytics', 'frontend', 'llmEvaluationExecutionLogic']),
    connect(() => ({
        values: [teamLogic, ['currentTeamId']],
    })),
    actions({
        runEvaluation: (evaluationId: string, targetEventId: string, timestamp: string) => ({
            evaluationId,
            targetEventId,
            timestamp,
        }),
    }),
    loaders(({ values }) => ({
        evaluationRun: [
            null as { workflow_id: string } | null,
            {
                runEvaluation: async ({ evaluationId, targetEventId, timestamp }) => {
                    if (!values.currentTeamId) {
                        throw new Error('No team selected')
                    }

                    try {
                        const response = await api.evaluationRuns.create({
                            evaluation_id: evaluationId,
                            target_event_id: targetEventId,
                            timestamp: timestamp,
                        })

                        lemonToast.success('Evaluation started successfully')
                        return response
                    } catch (error) {
                        lemonToast.error('Failed to start evaluation')
                        throw error
                    }
                },
            },
        ],
    })),
    reducers({
        lastRunWorkflowId: [
            null as string | null,
            {
                runEvaluationSuccess: (_, { evaluationRun }) => evaluationRun?.workflow_id || null,
            },
        ],
    }),
])
