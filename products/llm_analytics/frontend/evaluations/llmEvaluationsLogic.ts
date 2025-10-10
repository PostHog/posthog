import { actions, afterMount, kea, listeners, path, reducers, selectors } from 'kea'

import api from 'lib/api'
import { teamLogic } from 'scenes/teamLogic'

import type { llmEvaluationsLogicType } from './llmEvaluationsLogicType'
import { EvaluationConfig } from './types'

export const llmEvaluationsLogic = kea<llmEvaluationsLogicType>([
    path(['products', 'llm_analytics', 'evaluations', 'llmEvaluationsLogic']),

    actions({
        loadEvaluations: true,
        loadEvaluationsSuccess: (evaluations: EvaluationConfig[]) => ({ evaluations }),
        createEvaluation: (evaluation: Partial<EvaluationConfig>) => ({ evaluation }),
        createEvaluationSuccess: (evaluation: EvaluationConfig) => ({ evaluation }),
        updateEvaluation: (id: string, evaluation: Partial<EvaluationConfig>) => ({ id, evaluation }),
        updateEvaluationSuccess: (id: string, evaluation: Partial<EvaluationConfig>) => ({ id, evaluation }),
        deleteEvaluation: (id: string) => ({ id }),
        deleteEvaluationSuccess: (id: string) => ({ id }),
        duplicateEvaluation: (id: string) => ({ id }),
        duplicateEvaluationSuccess: (evaluation: EvaluationConfig) => ({ evaluation }),
        toggleEvaluationEnabled: (id: string) => ({ id }),
        toggleEvaluationEnabledSuccess: (id: string) => ({ id }),
        setEvaluationsFilter: (filter: string) => ({ filter }),
    }),

    reducers({
        evaluations: [
            [] as EvaluationConfig[],
            {
                loadEvaluationsSuccess: (_, { evaluations }) => evaluations,
                createEvaluationSuccess: (state, { evaluation }) => [...state, evaluation],
                updateEvaluationSuccess: (state, { id, evaluation }) =>
                    state.map((e: EvaluationConfig) => (e.id === id ? { ...e, ...evaluation } : e)),
                deleteEvaluationSuccess: (state, { id }) => state.filter((e: EvaluationConfig) => e.id !== id),
                duplicateEvaluationSuccess: (state, { evaluation }) => [...state, evaluation],
                toggleEvaluationEnabledSuccess: (state, { id }) =>
                    state.map((e: EvaluationConfig) => (e.id === id ? { ...e, enabled: !e.enabled } : e)),
            },
        ],
        evaluationsLoading: [
            false,
            {
                loadEvaluations: () => true,
                loadEvaluationsSuccess: () => false,
            },
        ],
        evaluationsFilter: [
            '',
            {
                setEvaluationsFilter: (_, { filter }) => filter,
            },
        ],
    }),

    listeners(({ actions, values }) => ({
        loadEvaluations: async () => {
            try {
                const teamId = teamLogic.values.currentTeamId
                if (!teamId) {
                    return
                }

                const response = await api.get(`/api/environments/${teamId}/evaluations/`)
                actions.loadEvaluationsSuccess(response.results)
            } catch (error) {
                console.error('Failed to load evaluations:', error)
                actions.loadEvaluationsSuccess([])
            }
        },

        createEvaluation: async ({ evaluation }) => {
            try {
                const teamId = teamLogic.values.currentTeamId
                if (!teamId) {
                    return
                }

                const response = await api.create(`/api/environments/${teamId}/evaluations/`, evaluation)
                actions.createEvaluationSuccess(response)
            } catch (error) {
                console.error('Failed to create evaluation:', error)
            }
        },

        updateEvaluation: async ({ id, evaluation }) => {
            try {
                const teamId = teamLogic.values.currentTeamId
                if (!teamId) {
                    return
                }

                const response = await api.update(`/api/environments/${teamId}/evaluations/${id}/`, evaluation)
                actions.updateEvaluationSuccess(id, response)
            } catch (error) {
                console.error('Failed to update evaluation:', error)
            }
        },

        deleteEvaluation: async ({ id }) => {
            try {
                const teamId = teamLogic.values.currentTeamId
                if (!teamId) {
                    return
                }
                await api.update(`/api/environments/${teamId}/evaluations/${id}/`, { deleted: true })
                actions.deleteEvaluationSuccess(id)
            } catch (error) {
                console.error('Failed to delete evaluation:', error)
            }
        },

        duplicateEvaluation: async ({ id }) => {
            try {
                const original = values.evaluations.find((e: EvaluationConfig) => e.id === id)
                if (!original) {
                    return
                }

                const duplicate = {
                    name: `${original.name} (Copy)`,
                    description: original.description,
                    enabled: original.enabled,
                    prompt: original.prompt,
                    conditions: original.conditions,
                }

                const teamId = teamLogic.values.currentTeamId
                if (!teamId) {
                    return
                }

                const response = await api.create(`/api/environments/${teamId}/evaluations/`, duplicate)
                actions.duplicateEvaluationSuccess(response)
            } catch (error) {
                console.error('Failed to duplicate evaluation:', error)
            }
        },

        toggleEvaluationEnabled: async ({ id }) => {
            try {
                const evaluation = values.evaluations.find((e: EvaluationConfig) => e.id === id)
                if (!evaluation) {
                    return
                }

                const teamId = teamLogic.values.currentTeamId
                if (!teamId) {
                    return
                }

                await api.update(`/api/environments/${teamId}/evaluations/${id}/`, {
                    enabled: !evaluation.enabled,
                })
                actions.toggleEvaluationEnabledSuccess(id)
            } catch (error) {
                console.error('Failed to toggle evaluation enabled:', error)
            }
        },
    })),

    selectors({
        filteredEvaluations: [
            (s) => [s.evaluations, s.evaluationsFilter],
            (evaluations: EvaluationConfig[], filter: string) => {
                if (!filter) {
                    return evaluations
                }
                return evaluations.filter(
                    (e: EvaluationConfig) =>
                        e.name.toLowerCase().includes(filter.toLowerCase()) ||
                        e.description?.toLowerCase().includes(filter.toLowerCase()) ||
                        e.prompt.toLowerCase().includes(filter.toLowerCase())
                )
            },
        ],
    }),

    afterMount(({ actions }) => {
        actions.loadEvaluations()
    }),
])
