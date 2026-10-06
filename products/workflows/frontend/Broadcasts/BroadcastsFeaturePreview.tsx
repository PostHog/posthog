import { FeaturePreviewFeedbackBanner } from '../FeaturePreviewFeedbackBanner'
import {
    BROADCASTS_FEEDBACK_RATING_QUESTION_ID,
    BROADCASTS_FEEDBACK_SURVEY_ID,
    BROADCASTS_FEEDBACK_TEXT_QUESTION_ID,
} from './broadcastsFeedbackSurvey'

export function BroadcastsFeaturePreview(): JSX.Element {
    return (
        <FeaturePreviewFeedbackBanner
            surveyId={BROADCASTS_FEEDBACK_SURVEY_ID}
            ratingQuestionId={BROADCASTS_FEEDBACK_RATING_QUESTION_ID}
            feedbackQuestionId={BROADCASTS_FEEDBACK_TEXT_QUESTION_ID}
            surface="broadcasts"
            dismissKey="broadcasts-feature-preview"
            prompt="Broadcasts is new. Is it doing what you need?"
            modalTitle="Help shape broadcasts"
            feedbackPlaceholder="Tell us what works, what doesn’t, or what you’d change"
            // Line up with the search box and table below, which sit flush with the tab content.
            className="my-2"
            data-attr="broadcasts-feature-preview"
        />
    )
}
