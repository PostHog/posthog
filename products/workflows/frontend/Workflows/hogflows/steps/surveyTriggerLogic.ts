import { actions, afterMount, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'

import { Survey, SurveyQuestionType } from '~/types'

import { getRegisteredTriggerTypes } from '../registry/triggers/triggerTypeRegistry'
import type { HogFlow } from '../types'
import type { surveyTriggerLogicType } from './surveyTriggerLogicType'

const SURVEYS_PAGE_SIZE = 20

export function isSurveyTrigger(workflow: HogFlow | null | undefined): boolean {
    if (!workflow) {
        return false
    }
    const trigger = workflow.actions?.find((a) => a.type === 'trigger')
    if (!trigger) {
        return false
    }
    const surveyType = getRegisteredTriggerTypes().find((t) => t.value === 'survey_response')
    return surveyType?.matchConfig?.(trigger.config) ?? false
}

export function getSampleValueForQuestionType(type: string): any {
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
}

export function buildSurveySampleEvent(
    selectedSurvey: Survey | null,
    getSampleValue: (type: string) => any
): Record<string, any> {
    const surveyProperties: Record<string, any> = {
        $survey_id: selectedSurvey?.id ?? 'survey-uuid',
        $survey_name: selectedSurvey?.name ?? 'Survey name',
        $survey_completed: true,
        $survey_submission_id: 'submission-uuid',
        $survey_iteration: null,
        $survey_iteration_start_date: null,
        $survey_questions: [{ id: 'question-id', question: 'Question text', response: 'Response' }],
    }

    if (selectedSurvey?.questions) {
        selectedSurvey.questions.forEach((question) => {
            if (question.type === SurveyQuestionType.Link) {
                return
            }
            if (question.id) {
                surveyProperties[`$survey_response_${question.id}`] = getSampleValue(question.type)
            }
        })
        surveyProperties.$survey_questions = selectedSurvey.questions.map((q) => ({
            id: q.id ?? '',
            question: q.question,
            response: getSampleValue(q.type),
        }))
    }

    return {
        event: 'survey sent',
        distinct_id: 'user123',
        properties: surveyProperties,
        timestamp: '2024-01-01T12:00:00Z',
    }
}

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
