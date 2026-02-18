import { actions, kea, listeners, path, reducers } from 'kea'
import posthog from 'posthog-js'

import type { disableSurveyLogicType } from './disableSurveyLogicType'

const SURVEY_ID = '019c72ac-3098-0000-8da2-c133ed9d9b9b'

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

    listeners(({ values, actions }) => ({
        showSurvey: () => {
            posthog.capture('survey shown', {
                $survey_id: SURVEY_ID,
            })
        },
        submitResponse: () => {
            posthog.capture('survey sent', {
                $survey_id: SURVEY_ID,
                $survey_response: values.response,
            })
            setTimeout(() => actions.hideSurvey(), 3000)
        },
    })),
])
