import { FeaturePreviewFeedbackBanner } from '../FeaturePreviewFeedbackBanner'
import {
    BROADCASTS_FEEDBACK_RATING_QUESTION_ID,
    BROADCASTS_FEEDBACK_SURVEY_ID,
    BROADCASTS_FEEDBACK_TEXT_QUESTION_ID,
} from './broadcastsFeedbackSurvey'

/** Asked on a sent or scheduled broadcast that PostHog AI drafted. */
export function ComposerDraftFeedback(): JSX.Element {
    return (
        <FeaturePreviewFeedbackBanner
            surveyId={BROADCASTS_FEEDBACK_SURVEY_ID}
            ratingQuestionId={BROADCASTS_FEEDBACK_RATING_QUESTION_ID}
            feedbackQuestionId={BROADCASTS_FEEDBACK_TEXT_QUESTION_ID}
            // pinned: feedback_surface value, filtered on in the broadcasts dashboard
            surface="broadcasts-composer-draft"
            dismissKey="broadcasts-composer-draft-feedback"
            prompt="Did PostHog AI get this broadcast right?"
            modalTitle="Help us improve AI drafts"
            feedbackPlaceholder="What did you have to change, or what did it get wrong?"
            className="m-0"
            data-attr="broadcasts-composer-draft-feedback"
        />
    )
}
