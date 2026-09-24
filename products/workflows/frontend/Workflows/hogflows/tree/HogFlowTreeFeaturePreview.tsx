import { FeaturePreviewFeedbackBanner } from '../../../FeaturePreviewFeedbackBanner'

const SURVEY_ID = '01a0856f-7ae3-0000-eef6-fec0a2e1b78f'
const RATING_QUESTION_ID = 'a899da8d-092a-41ce-ab9b-8e18b2c7cfd8'
const FEEDBACK_QUESTION_ID = 'acbad4b5-52c2-4a56-a280-5d2ddd064612'

export function HogFlowTreeFeaturePreview(): JSX.Element {
    return (
        <FeaturePreviewFeedbackBanner
            surveyId={SURVEY_ID}
            ratingQuestionId={RATING_QUESTION_ID}
            feedbackQuestionId={FEEDBACK_QUESTION_ID}
            surface="workflow_tree_editor"
            dismissKey="workflow-tree-feature-preview"
            prompt="We’re trialling a new list based workflow view. What do you think?"
            modalTitle="Help shape the new workflow view"
            feedbackPlaceholder="Tell us what works, what doesn’t, or what you’d change"
            data-attr="workflow-tree-feature-preview"
        />
    )
}
