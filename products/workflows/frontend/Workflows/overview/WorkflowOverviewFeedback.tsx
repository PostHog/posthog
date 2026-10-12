import { FeaturePreviewFeedbackBanner } from '../../FeaturePreviewFeedbackBanner'

// Shares the workflow feature preview survey; `surface` keeps these responses apart from the list view's.
const SURVEY_ID = '01a0856f-7ae3-0000-eef6-fec0a2e1b78f'
const RATING_QUESTION_ID = 'a899da8d-092a-41ce-ab9b-8e18b2c7cfd8'
const FEEDBACK_QUESTION_ID = 'acbad4b5-52c2-4a56-a280-5d2ddd064612'

export function WorkflowOverviewFeedback(): JSX.Element {
    return (
        <FeaturePreviewFeedbackBanner
            surveyId={SURVEY_ID}
            ratingQuestionId={RATING_QUESTION_ID}
            feedbackQuestionId={FEEDBACK_QUESTION_ID}
            surface="workflow_overview_tab"
            dismissKey="workflow-overview-feature-preview"
            prompt="We're trying out an overview for workflows. Is it useful?"
            modalTitle="Help shape the workflow overview"
            feedbackPlaceholder="Tell us what's useful, what's missing, or what you'd change"
            className=""
            data-attr="workflow-overview-feature-preview"
        />
    )
}
