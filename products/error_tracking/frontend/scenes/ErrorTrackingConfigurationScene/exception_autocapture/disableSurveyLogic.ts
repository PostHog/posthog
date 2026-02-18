import { actions, kea, listeners, path, reducers } from 'kea'
import posthog from 'posthog-js'

import type { disableSurveyLogicType } from './disableSurveyLogicType'

const SURVEY_ID = '019c7121-f593-0000-2a0f-963ae6b3f5df'

export const disableSurveyLogic = kea<disableSurveyLogicType>([
    path(['scenes', 'error-tracking', 'configuration', 'disableSurveyLogic']),

    actions({
        showSurvey: true,
        hideSurvey: true,
        setResponse: (response: string) => ({ response }),
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
        response: [
            '',
            {
                setResponse: (_, { response }) => response,
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
            posthog.capture('survey shown', {
                $survey_id: SURVEY_ID,
            })
        },
        submitResponse: () => {
            posthog.capture('survey sent', {
                $survey_id: SURVEY_ID,
                $survey_response: values.response,
            })
            cache.hideTimeout = setTimeout(() => {
                actions.hideSurvey()
                cache.hideTimeout = null
            }, 3000)
        },
    })),
])
