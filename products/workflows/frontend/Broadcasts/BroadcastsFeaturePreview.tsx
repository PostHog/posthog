import { FeaturePreviewFeedbackBanner } from '../FeaturePreviewFeedbackBanner'

const SURVEY_ID = '01a0ce6c-f291-0000-092b-8677d994599c'
const RATING_QUESTION_ID = 'a5e6e02a-174b-41a7-8da6-7fa1595ac763'
const FEEDBACK_QUESTION_ID = '1e3e0368-135f-485c-bf46-ddaac558e879'

export function BroadcastsFeaturePreview(): JSX.Element {
    return (
        <FeaturePreviewFeedbackBanner
            surveyId={SURVEY_ID}
            ratingQuestionId={RATING_QUESTION_ID}
            feedbackQuestionId={FEEDBACK_QUESTION_ID}
            surface="broadcasts"
            dismissKey="broadcasts-feature-preview"
            prompt="Broadcasts is new. Is it doing what you need?"
            modalTitle="Help shape broadcasts"
            feedbackPlaceholder="Tell us what works, what doesn’t, or what you’d change"
            data-attr="broadcasts-feature-preview"
        />
    )
}
