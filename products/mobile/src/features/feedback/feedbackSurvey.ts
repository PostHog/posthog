import { randomUUID } from 'expo-crypto'

import { captureSurveyEvent } from '@/lib/analytics'

// The "Mobile app feedback" API survey in PostHog's own project, which is the project `EXPO_PUBLIC_POSTHOG_KEY`
// sends to. A Slack notification on the survey posts each response to #support-mobile-app.
const SURVEY_ID = '01a1a733-ccf1-0000-5cab-1ecb6181d038'
const QUESTION_ID = '3f98fbdb-9c7e-450c-b354-aa1bf09c9988'

// The Slack message puts the response in one section block, and Slack refuses a section text over 3000 characters.
export const FEEDBACK_MAX_LENGTH = 2000

export function feedbackShown(): void {
    void captureSurveyEvent('survey shown', { $survey_id: SURVEY_ID }).catch(() => undefined)
}

export function feedbackDismissed(): void {
    void captureSurveyEvent('survey dismissed', { $survey_id: SURVEY_ID }).catch(() => undefined)
}

/** The email lets the team reply. The sheet shows it, so the person knows it goes with the message. */
export function sendFeedback(message: string, email: string, submissionId = randomUUID()): Promise<void> {
    return captureSurveyEvent('survey sent', {
        $survey_id: SURVEY_ID,
        $survey_response: message,
        [`$survey_response_${QUESTION_ID}`]: message,
        $survey_completed: true,
        $survey_submission_id: submissionId,
        email,
    })
}
