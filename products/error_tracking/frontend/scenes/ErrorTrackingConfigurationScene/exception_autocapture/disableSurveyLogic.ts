import { actions, connect, kea, listeners, path, reducers } from 'kea'
import posthog from 'posthog-js'

import { billingLogic } from 'scenes/billing/billingLogic'

import { ProductKey } from '~/queries/schema/schema-general'
import { SurveyQuestion } from '~/types'

import type { disableSurveyLogicType } from './disableSurveyLogicType'

const SURVEY_ID = '019c89a0-1469-0000-a31c-35883eb31be4'

export const disableSurveyLogic = kea<disableSurveyLogicType>([
    path(['scenes', 'error-tracking', 'configuration', 'disableSurveyLogic']),

    connect(() => ({
        values: [billingLogic, ['billing']],
    })),

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
            const billing = values.billing
            const errorTrackingProduct = billing?.products?.find((p) => p.type === ProductKey.ERROR_TRACKING)
            if (errorTrackingProduct?.current_amount_usd) {
                payload.error_tracking_current_amount_usd = errorTrackingProduct.current_amount_usd
            }
            if (errorTrackingProduct?.projected_amount_usd) {
                payload.error_tracking_projected_amount_usd = errorTrackingProduct.projected_amount_usd
            }
            if (billing?.current_total_amount_usd) {
                payload.current_total_amount_usd = billing.current_total_amount_usd
            }
            if (billing?.projected_total_amount_usd) {
                payload.projected_total_amount_usd = billing.projected_total_amount_usd
            }
            posthog.capture('survey sent', payload)
            cache.hideTimeout = setTimeout(() => {
                actions.hideSurvey()
                cache.hideTimeout = null
            }, 3000)
        },
    })),
])
