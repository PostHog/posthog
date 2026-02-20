import { actions, afterMount, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'

import { Survey } from '~/types'

import type { surveyTriggerLogicType } from './surveyTriggerLogicType'

const SURVEYS_PAGE_SIZE = 20

export const surveyTriggerLogic = kea<surveyTriggerLogicType>([
    path(['products', 'workflows', 'frontend', 'Workflows', 'hogflows', 'steps', 'surveyTriggerLogic']),
    actions({
        setSearchTerm: (searchTerm: string) => ({ searchTerm }),
    }),
    loaders(({ values }) => ({
        surveys: [
            [] as Survey[],
            {
                loadSurveys: async () => {
                    const response = await api.surveys.list({ limit: SURVEYS_PAGE_SIZE, archived: false })
                    return response.results
                },
            },
        ],
        moreSurveys: [
            [] as Survey[],
            {
                loadMoreSurveys: async () => {
                    const response = await api.surveys.list({
                        limit: SURVEYS_PAGE_SIZE,
                        offset: values.allSurveys.length,
                        archived: false,
                    })
                    return response.results
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
    reducers({
        searchTerm: [
            '' as string,
            {
                setSearchTerm: (_, { searchTerm }) => searchTerm,
            },
        ],
        allSurveys: [
            [] as Survey[],
            {
                loadSurveysSuccess: (_, { surveys }) => surveys,
                loadMoreSurveysSuccess: (state, { moreSurveys }) => [...state, ...moreSurveys],
            },
        ],
        hasMoreSurveys: [
            true,
            {
                loadSurveysSuccess: (_, { surveys }) => surveys.length >= SURVEYS_PAGE_SIZE,
                loadMoreSurveysSuccess: (_, { moreSurveys }) => moreSurveys.length >= SURVEYS_PAGE_SIZE,
            },
        ],
    }),
    selectors({
        filteredSurveys: [
            (s) => [s.allSurveys, s.searchTerm],
            (allSurveys: Survey[], searchTerm: string): Survey[] => {
                if (!searchTerm) {
                    return allSurveys
                }
                const lower = searchTerm.toLowerCase()
                return allSurveys.filter((s) => s.name.toLowerCase().includes(lower))
            },
        ],
    }),
    afterMount(({ actions }) => {
        actions.loadSurveys()
    }),
    listeners(({ actions }) => ({
        loadSurveysSuccess: () => {
            actions.loadResponseCounts()
        },
        loadMoreSurveysSuccess: () => {
            actions.loadResponseCounts()
        },
        loadSurveysFailure: ({ error }) => {
            lemonToast.error('Failed to load surveys: ' + error)
        },
        loadMoreSurveysFailure: ({ error }) => {
            lemonToast.error('Failed to load more surveys: ' + error)
        },
        loadResponseCountsFailure: ({ error }) => {
            lemonToast.error('Failed to load response counts: ' + error)
        },
    })),
])
