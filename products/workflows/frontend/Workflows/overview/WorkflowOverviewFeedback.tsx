import { FeaturePreviewFeedbackBanner } from '../../FeaturePreviewFeedbackBanner'

const SURVEY_ID = '01a135a4-2f3c-0000-4732-df04655842ff'
const RATING_QUESTION_ID = '521dcdd1-4a8b-40c4-a8b3-41ac5b9a751f'
const FEEDBACK_QUESTION_ID = '227c1646-eafa-46ad-823c-d2a8892a806b'

export function WorkflowOverviewFeedback(): JSX.Element {
    return (
        <FeaturePreviewFeedbackBanner
            surveyId={SURVEY_ID}
            ratingQuestionId={RATING_QUESTION_ID}
            feedbackQuestionId={FEEDBACK_QUESTION_ID}
            surface="workflow_overview_tab"
            dismissKey="workflow-overview-feature-preview"
            prompt="We're trying out an overview for workflows. Is it useful?"
            feedbackTitle="Help shape the workflow overview"
            feedbackPlaceholder="Tell us what's useful, what's missing, or what you'd change"
            className=""
            data-attr="workflow-overview-feature-preview"
        />
    )
}
