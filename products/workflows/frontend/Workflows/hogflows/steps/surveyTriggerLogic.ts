import { actions, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import { Survey } from '~/types'

import type { surveyTriggerLogicType } from './surveyTriggerLogicType'

const SURVEYS_PAGE_SIZE = 20

export const surveyTriggerLogic = kea<surveyTriggerLogicType>([
    path(['products', 'workflows', 'frontend', 'Workflows', 'hogflows', 'steps', 'surveyTriggerLogic']),
    actions({
        loadMoreSurveys: true,
        appendSurveys: (surveys: Survey[]) => ({ surveys }),
    }),
    reducers({
        allSurveys: [
            [] as Survey[],
            {
                loadSurveysSuccess: (_, { surveys }) => surveys,
                appendSurveys: (state, { surveys }) => [...state, ...surveys],
            },
        ],
        hasMoreSurveys: [
            true,
            {
                loadSurveysSuccess: (_, { surveys }) => surveys.length >= SURVEYS_PAGE_SIZE,
                appendSurveys: (_, { surveys }) => surveys.length >= SURVEYS_PAGE_SIZE,
            },
        ],
        moreSurveysLoading: [
            false,
            {
                loadMoreSurveys: () => true,
                appendSurveys: () => false,
            },
        ],
    }),
    loaders(({ values }) => ({
        surveys: [
            [] as Survey[],
            {
                loadSurveys: async () => {
                    const response = await api.surveys.list({ limit: SURVEYS_PAGE_SIZE })
                    return response.results.filter((s) => !s.archived)
                },
            },
        ],
        responseCounts: [
            {} as Record<string, number>,
            {
                loadResponseCounts: async () => {
                    const surveyIds = values.allSurveys.map((s) => s.id).join(',')
                    if (!surveyIds) {
                        return {}
                    }
                    return await api.surveys.getResponsesCount(surveyIds)
                },
            },
        ],
    })),
    listeners(({ values, actions }) => ({
        loadMoreSurveys: async () => {
            const response = await api.surveys.list({
                limit: SURVEYS_PAGE_SIZE,
                offset: values.allSurveys.length,
            })
            const filtered = response.results.filter((s) => !s.archived)
            actions.appendSurveys(filtered)
        },
        loadSurveysSuccess: () => {
            actions.loadResponseCounts()
        },
        appendSurveys: () => {
            actions.loadResponseCounts()
        },
    })),
])
