import { actions, afterMount, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'

import { Survey, SurveyQuestionType } from '~/types'
import { SurveyEventName } from '~/types'

import type { HogFlow } from '../types'
import type { surveyTriggerLogicType } from './surveyTriggerLogicType'

const SURVEYS_PAGE_SIZE = 20

export function isSurveyTrigger(workflow: HogFlow | null | undefined): boolean {
    if (!workflow) {
        return false
    }
    const trigger = workflow.actions?.find((a) => a.type === 'trigger')
    if (!trigger || trigger.config.type !== 'event') {
        return false
    }
    const events = trigger.config.filters?.events ?? []
    return events.length === 1 && events[0]?.id === SurveyEventName.SENT
}

export const surveyTriggerLogic = kea<surveyTriggerLogicType>([
    path(['products', 'workflows', 'frontend', 'Workflows', 'hogflows', 'steps', 'surveyTriggerLogic']),
    actions({
        loadMoreSurveys: true,
        loadMoreSurveysFailure: true,
        appendSurveys: (surveys: Survey[]) => ({ surveys }),
        setSearchTerm: (searchTerm: string) => ({ searchTerm }),
    }),
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
                loadMoreSurveysFailure: () => false,
                appendSurveys: () => false,
            },
        ],
    }),
    selectors({
        getSampleValueForQuestionType: [
            () => [],
            (): ((type: string) => any) =>
                (type: string): any => {
                    switch (type) {
                        case SurveyQuestionType.Open:
                            return 'User response text'
                        case SurveyQuestionType.Rating:
                            return '8'
                        case SurveyQuestionType.SingleChoice:
                            return 'Selected option'
                        case SurveyQuestionType.MultipleChoice:
                            return ['Option A', 'Option B']
                        case SurveyQuestionType.Link:
                            return null
                        default:
                            return 'response'
                    }
                },
        ],
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
    afterMount(({ actions }) => {
        actions.loadSurveys()
    }),
    listeners(({ values, actions }) => ({
        loadMoreSurveys: async () => {
            try {
                const response = await api.surveys.list({
                    limit: SURVEYS_PAGE_SIZE,
                    offset: values.allSurveys.length,
                })
                const filtered = response.results.filter((s) => !s.archived)
                actions.appendSurveys(filtered)
            } catch (e) {
                lemonToast.error('Failed to load more surveys: ' + (e as Error).message)
                actions.loadMoreSurveysFailure()
            }
        },
        loadSurveysSuccess: () => {
            actions.loadResponseCounts()
        },
        loadSurveysFailure: ({ error }) => {
            lemonToast.error('Failed to load surveys: ' + error)
        },
        loadResponseCountsFailure: ({ error }) => {
            lemonToast.error('Failed to load response counts: ' + error)
        },
        appendSurveys: () => {
            actions.loadResponseCounts()
        },
    })),
])
