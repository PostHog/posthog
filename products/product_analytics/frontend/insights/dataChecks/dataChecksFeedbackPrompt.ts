import type {
    SurveyFeedbackPromptConfig,
    SurveyFeedbackPromptLogicProps,
} from 'lib/logic/surveyFeedbackPrompt/surveyFeedbackPromptLogic'

import type { InsightLogicProps, UserType } from '~/types'

import type { InsightDataChecksStatus } from './insightDataChecksLogic'

export const DATA_CHECKS_FEEDBACK_SURVEY_ID = '01a15d5f-3117-0000-9b74-1712010c28ca'

// pinned: localStorage key prefix, renaming it resets every person's cooldown
const DATA_CHECKS_FEEDBACK_COOLDOWN_STORAGE_KEY = 'insight-data-checks-feedback-last-prompt'

const DATA_CHECKS_FEEDBACK_PROMPT: SurveyFeedbackPromptConfig = {
    surface: 'insight_data_checks',
    entryPoint: 'data_checks_popover',
    version: 1,
    question: 'Were these checks useful?',
    followUpQuestion: 'What would make these checks more useful?',
}

const STATUSES_WITH_RESULTS: InsightDataChecksStatus[] = ['passed', 'warning', 'problem']

export function dataChecksFeedbackLogicProps(
    user: UserType | null,
    insightProps: InsightLogicProps,
    status: InsightDataChecksStatus
): SurveyFeedbackPromptLogicProps {
    return {
        surveyId: DATA_CHECKS_FEEDBACK_SURVEY_ID,
        cooldownStorageKey: DATA_CHECKS_FEEDBACK_COOLDOWN_STORAGE_KEY,
        userId: user?.uuid ?? '',
        contextKey: String(insightProps.dashboardItemId ?? 'new'),
        prompt: DATA_CHECKS_FEEDBACK_PROMPT,
        isImpersonated: user?.is_impersonated ?? false,
        eligible: STATUSES_WITH_RESULTS.includes(status),
        delayMs: 0,
    }
}
