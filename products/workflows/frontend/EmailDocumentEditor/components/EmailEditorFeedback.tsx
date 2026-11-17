import { FeaturePreviewFeedbackBanner } from 'products/workflows/frontend/FeaturePreviewFeedbackBanner'

// The api-type survey the new editor's banner reports to.
const EMAIL_EDITOR_FEEDBACK_SURVEY_ID = '01a1b1b8-80ac-0000-69c3-d6d49770d78c'
const EMAIL_EDITOR_FEEDBACK_RATING_QUESTION_ID = '7083646e-1fba-4ad7-97ee-e290849ac4fe'
const EMAIL_EDITOR_FEEDBACK_TEXT_QUESTION_ID = 'e49fca42-fae0-4f4e-9c26-f9b0517aed45'

export function EmailEditorFeedback(): JSX.Element {
    return (
        <FeaturePreviewFeedbackBanner
            surveyId={EMAIL_EDITOR_FEEDBACK_SURVEY_ID}
            ratingQuestionId={EMAIL_EDITOR_FEEDBACK_RATING_QUESTION_ID}
            feedbackQuestionId={EMAIL_EDITOR_FEEDBACK_TEXT_QUESTION_ID}
            surface="email-editor"
            dismissKey="workflows-email-editor-feedback"
            prompt="This email editor is new. Is it doing what you need?"
            feedbackTitle="Help shape the email editor"
            feedbackPlaceholder="Tell us what works, what doesn't, or what you'd change"
            data-attr="email-editor-feedback"
        />
    )
}
