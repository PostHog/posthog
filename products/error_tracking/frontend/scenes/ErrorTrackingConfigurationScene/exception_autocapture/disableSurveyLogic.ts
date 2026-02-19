import { actions, kea, listeners, path, reducers } from 'kea'
import posthog from 'posthog-js'

import { SurveyQuestion } from '~/types'

import type { disableSurveyLogicType } from './disableSurveyLogicType'

const SURVEY_ID = '019c72ac-3098-0000-8da2-c133ed9d9b9b'

export const disableSurveyLogic = kea<disableSurveyLogicType>([
    path(['scenes', 'error-tracking', 'configuration', 'disableSurveyLogic']),

    actions({
        showSurvey: true,
        hideSurvey: true,
        setSurveyQuestions: (questions: SurveyQuestion[]) => ({ questions }),
        setSelectedChoice: (choice: string) => ({ choice }),
        setOpenResponse: (response: string) => ({ response }),
        submitResponse: true,
    }),

    reducers({
        visible: [
            false,
            {
                showSurvey: () => true,
                hideSurvey: () => false,
            },
        ],
        surveyQuestions: [
            [] as SurveyQuestion[],
            {
                setSurveyQuestions: (_, { questions }) => questions,
            },
        ],
        selectedChoice: [
            null as string | null,
            {
                setSelectedChoice: (_, { choice }) => choice,
                hideSurvey: () => null,
            },
        ],
        openResponse: [
            '',
            {
                setOpenResponse: (_, { response }) => response,
                hideSurvey: () => '',
            },
        ],
        submitted: [
            false,
            {
                submitResponse: () => true,
                showSurvey: () => false,
                hideSurvey: () => false,
            },
        ],
    }),

    listeners(({ values, actions, cache }) => ({
        showSurvey: () => {
            if (cache.hideTimeout) {
                clearTimeout(cache.hideTimeout)
                cache.hideTimeout = null
            }
            posthog.getSurveys((surveys) => {
                const survey = surveys.find((s) => s.id === SURVEY_ID)
                if (survey) {
                    actions.setSurveyQuestions(survey.questions as unknown as SurveyQuestion[])
                }
            })
            posthog.capture('survey shown', {
                $survey_id: SURVEY_ID,
            })
        },
        submitResponse: () => {
            const payload: Record<string, string> = {
                $survey_id: SURVEY_ID,
            }
            if (values.selectedChoice) {
                payload.$survey_response = values.selectedChoice
            }
            if (values.openResponse.trim()) {
                payload.$survey_response_1 = values.openResponse
            }
            posthog.capture('survey sent', payload)
            cache.hideTimeout = setTimeout(() => {
                actions.hideSurvey()
                cache.hideTimeout = null
            }, 3000)
        },
    })),
])
