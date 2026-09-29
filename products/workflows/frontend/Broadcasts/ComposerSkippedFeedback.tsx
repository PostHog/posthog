import { FeaturePreviewFeedbackBanner } from '../FeaturePreviewFeedbackBanner'
import {
    BROADCASTS_FEEDBACK_RATING_QUESTION_ID,
    BROADCASTS_FEEDBACK_SURVEY_ID,
    BROADCASTS_FEEDBACK_TEXT_QUESTION_ID,
} from './broadcastsFeedbackSurvey'

/** Asked right after someone leaves the PostHog AI composer for the step-by-step wizard. */
export function ComposerSkippedFeedback(): JSX.Element {
    return (
        <FeaturePreviewFeedbackBanner
            surveyId={BROADCASTS_FEEDBACK_SURVEY_ID}
            ratingQuestionId={BROADCASTS_FEEDBACK_RATING_QUESTION_ID}
            feedbackQuestionId={BROADCASTS_FEEDBACK_TEXT_QUESTION_ID}
            // pinned: feedback_surface value, filtered on in the broadcasts dashboard
            surface="broadcasts-composer-skipped"
            dismissKey="broadcasts-composer-skipped-feedback"
            prompt="Would PostHog AI have been useful for this broadcast?"
            modalTitle="What made you set it up yourself?"
            feedbackPlaceholder="For example, it's quicker to write it myself, or I wasn't sure what it would send"
            className="m-0"
            data-attr="broadcasts-composer-skipped-feedback"
        />
    )
}
