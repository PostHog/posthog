import { actions, afterMount, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import api from 'lib/api'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { hogql } from '~/queries/utils'
import { Breadcrumb } from '~/types'

import type { llmEvaluationLogicType } from './llmEvaluationLogicType'
import { EvaluationConditionSet, EvaluationConfig, EvaluationRun } from './types'

export interface LLMEvaluationLogicProps {
    evaluationId: string
}

export const llmEvaluationLogic = kea<llmEvaluationLogicType>([
    path(['products', 'llm_analytics', 'evaluations', 'llmEvaluationLogic']),
    props({} as LLMEvaluationLogicProps),
    key((props) => props.evaluationId || 'new'),

    actions({
        // Evaluation configuration actions
        setEvaluationName: (name: string) => ({ name }),
        setEvaluationDescription: (description: string) => ({ description }),
        setEvaluationPrompt: (prompt: string) => ({ prompt }),
        setEvaluationEnabled: (enabled: boolean) => ({ enabled }),
        setTriggerConditions: (conditions: EvaluationConditionSet[]) => ({ conditions }),

        // Evaluation management actions
        saveEvaluation: true,
        saveEvaluationSuccess: (evaluation: EvaluationConfig) => ({ evaluation }),
        loadEvaluation: true,
        loadEvaluationSuccess: (evaluation: EvaluationConfig | null) => ({ evaluation }),
        resetEvaluation: true,

        // Evaluation runs actions
        refreshEvaluationRuns: true,
    }),

    loaders(({ props, values }) => ({
        evaluationRuns: [
            [] as EvaluationRun[],
            {
                loadEvaluationRuns: async () => {
                    if (!props.evaluationId || props.evaluationId === 'new') {
                        return []
                    }

                    const teamId = teamLogic.values.currentTeamId
                    if (!teamId) {
                        return []
                    }

                    const query = hogql`
                        SELECT
                            uuid,
                            timestamp,
                            properties.$ai_target_event_id as target_event_id,
                            properties.$ai_trace_id as trace_id,
                            properties.$ai_evaluation_result as result,
                            properties.$ai_evaluation_model as model,
                            properties.$ai_evaluation_reasoning as reasoning
                        FROM events
                        WHERE
                            event = '$ai_evaluation'
                            AND team_id = ${teamId}
                            AND properties.$ai_evaluation_id = ${props.evaluationId}
                        ORDER BY timestamp DESC
                        LIMIT 100
                    `

                    const response = await api.queryHogQL(query, {
                        ...(values.isForceRefresh && { refresh: 'force_blocking' }),
                    })

                    return (response.results || []).map((row: any) => ({
                        id: row[0],
                        evaluation_id: props.evaluationId,
                        generation_id: row[2],
                        trace_id: row[3],
                        timestamp: row[1],
                        result: row[4],
                        reasoning: row[6] || 'No reasoning provided',
                        status: 'completed' as const,
                    }))
                },
            },
        ],
    })),

    reducers({
        evaluation: [
            null as EvaluationConfig | null,
            {
                setEvaluationName: (state, { name }) => (state ? { ...state, name } : null),
                setEvaluationDescription: (state, { description }) => (state ? { ...state, description } : null),
                setEvaluationPrompt: (state, { prompt }) => (state ? { ...state, prompt } : null),
                setEvaluationEnabled: (state, { enabled }) => (state ? { ...state, enabled } : null),
                setTriggerConditions: (state, { conditions }) => (state ? { ...state, conditions } : null),
                loadEvaluationSuccess: (_, { evaluation }) => evaluation,
                saveEvaluationSuccess: (_, { evaluation }) => evaluation,
                resetEvaluation: () => null,
            },
        ],
        isForceRefresh: [
            false,
            {
                refreshEvaluationRuns: () => true,
                loadEvaluationRunsSuccess: () => false,
                loadEvaluationRunsFailure: () => false,
            },
        ],
        evaluationLoading: [
            false,
            {
                loadEvaluation: () => true,
                loadEvaluationSuccess: () => false,
            },
        ],
        evaluationFormSubmitting: [
            false,
            {
                saveEvaluation: () => true,
                saveEvaluationSuccess: () => false,
            },
        ],
        hasUnsavedChanges: [
            false,
            {
                setEvaluationName: () => true,
                setEvaluationDescription: () => true,
                setEvaluationPrompt: () => true,
                setEvaluationEnabled: () => true,
                setTriggerConditions: () => true,
                saveEvaluationSuccess: () => false,
                loadEvaluationSuccess: () => false,
                resetEvaluation: () => false,
            },
        ],
    }),

    listeners(({ actions, values, props }) => ({
        loadEvaluation: async () => {
            if (props.evaluationId && props.evaluationId !== 'new') {
                try {
                    const teamId = teamLogic.values.currentTeamId
                    if (!teamId) {
                        return
                    }

                    const evaluation = await api.get(`/api/environments/${teamId}/evaluations/${props.evaluationId}/`)
                    actions.loadEvaluationSuccess(evaluation)
                } catch (error) {
                    console.error('Failed to load evaluation:', error)
                    actions.loadEvaluationSuccess(null)
                }
            } else if (props.evaluationId === 'new') {
                // Initialize new evaluation
                const newEvaluation: EvaluationConfig = {
                    id: '',
                    name: '',
                    description: '',
                    enabled: false,
                    prompt: '',
                    conditions: [
                        {
                            id: `cond-${Date.now()}`,
                            rollout_percentage: 100,
                            properties: [],
                        },
                    ],
                    total_runs: 0,
                    created_at: new Date().toISOString(),
                    updated_at: new Date().toISOString(),
                }
                actions.loadEvaluationSuccess(newEvaluation)
            }
        },

        refreshEvaluationRuns: () => {
            actions.loadEvaluationRuns()
        },

        saveEvaluation: async () => {
            try {
                const teamId = teamLogic.values.currentTeamId
                if (!teamId) {
                    return
                }

                if (props.evaluationId === 'new') {
                    const response = await api.create(`/api/environments/${teamId}/evaluations/`, values.evaluation!)
                    actions.saveEvaluationSuccess(response)
                } else {
                    const response = await api.update(
                        `/api/environments/${teamId}/evaluations/${props.evaluationId}/`,
                        values.evaluation!
                    )
                    actions.saveEvaluationSuccess(response)
                }
                router.actions.push(urls.llmAnalyticsEvaluations())
            } catch (error) {
                console.error('Failed to save evaluation:', error)
            }
        },
    })),

    selectors({
        isNewEvaluation: [(_, props) => [props.evaluationId], (evaluationId: string) => evaluationId === 'new'],

        formValid: [
            (s) => [s.evaluation],
            (evaluation) => {
                if (!evaluation) {
                    return false
                }
                return (
                    evaluation.name.length > 0 &&
                    evaluation.prompt.length > 0 &&
                    evaluation.conditions.length > 0 &&
                    evaluation.conditions.every((c) => c.rollout_percentage > 0 && c.rollout_percentage <= 100)
                )
            },
        ],

        runsSummary: [
            (s) => [s.evaluationRuns],
            (runs) => {
                if (runs.length === 0) {
                    return null
                }

                const successfulRuns = runs.filter((r) => r.result === true).length
                const failedRuns = runs.filter((r) => r.result === false).length
                const errorRuns = runs.filter((r) => r.status === 'failed').length

                return {
                    total: runs.length,
                    successful: successfulRuns,
                    failed: failedRuns,
                    errors: errorRuns,
                    successRate: runs.length > 0 ? Math.round((successfulRuns / runs.length) * 100) : 0,
                }
            },
        ],

        breadcrumbs: [
            (s) => [s.evaluation],
            (evaluation): Breadcrumb[] => [
                {
                    name: 'LLM Analytics',
                    path: urls.llmAnalyticsDashboard(),
                    key: 'LLMAnalytics',
                    iconType: 'llm_analytics',
                },
                {
                    name: 'Evaluations',
                    path: urls.llmAnalyticsEvaluations(),
                    key: 'LLMAnalyticsEvaluations',
                    iconType: 'llm_analytics',
                },
                {
                    name: evaluation?.name || 'New Evaluation',
                    key: 'LLMAnalyticsEvaluationEdit',
                },
            ],
        ],
    }),

    afterMount(({ actions, props }) => {
        actions.loadEvaluation()
        if (props.evaluationId !== 'new') {
            actions.loadEvaluationRuns()
        }
    }),
])
