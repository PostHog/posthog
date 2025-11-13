import { actions, afterMount, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router, urlToAction } from 'kea-router'

import api from 'lib/api'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import { queryEvaluationRuns } from '../utils'
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

                    return await queryEvaluationRuns({
                        evaluationId: props.evaluationId,
                        forceRefresh: values.isForceRefresh,
                    })
                },
            },
        ],
    })),

    reducers({
        originalEvaluation: [
            null as EvaluationConfig | null,
            {
                loadEvaluationSuccess: (_, { evaluation }) => evaluation,
                saveEvaluationSuccess: (_, { evaluation }) => evaluation,
            },
        ],
        evaluation: [
            null as EvaluationConfig | null,
            {
                setEvaluationName: (state, { name }) => (state ? { ...state, name } : null),
                setEvaluationDescription: (state, { description }) => (state ? { ...state, description } : null),
                setEvaluationPrompt: (state, { prompt }) =>
                    state ? { ...state, evaluation_config: { ...state.evaluation_config, prompt } } : null,
                setEvaluationEnabled: (state, { enabled }) => (state ? { ...state, enabled } : null),
                setTriggerConditions: (state, { conditions }) => (state ? { ...state, conditions } : null),
                loadEvaluationSuccess: (_, { evaluation }) => evaluation,
                saveEvaluationSuccess: (_, { evaluation }) => evaluation,
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
                    evaluation_type: 'llm_judge',
                    evaluation_config: {
                        prompt: '',
                    },
                    output_type: 'boolean',
                    output_config: {},
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

        resetEvaluation: () => {
            if (props.evaluationId === 'new') {
                const newEvaluation: EvaluationConfig = {
                    id: '',
                    name: '',
                    description: '',
                    enabled: false,
                    evaluation_type: 'llm_judge',
                    evaluation_config: {
                        prompt: '',
                    },
                    output_type: 'boolean',
                    output_config: {},
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
            } else {
                actions.loadEvaluationSuccess(values.originalEvaluation)
            }
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
                    evaluation.evaluation_config.prompt.length > 0 &&
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

    urlToAction(({ actions, props }) => ({
        '/llm-analytics/evaluations/:id': (_, __, ___, { method }) => {
            // Only reload when user clicked link, not on browser back/forward
            if (method === 'PUSH') {
                actions.loadEvaluation()
                if (props.evaluationId !== 'new') {
                    actions.loadEvaluationRuns()
                }
            }
        },
    })),

    afterMount(({ actions, props }) => {
        actions.loadEvaluation()
        if (props.evaluationId !== 'new') {
            actions.loadEvaluationRuns()
        }
    }),
])
