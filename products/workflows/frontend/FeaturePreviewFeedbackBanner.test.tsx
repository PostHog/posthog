import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import posthog from 'posthog-js'

import { lemonBannerLogic } from 'lib/lemon-ui/LemonBanner/lemonBannerLogic'

import { initKeaTests } from '~/test/init'

import { FeaturePreviewFeedbackBanner } from './FeaturePreviewFeedbackBanner'

jest.mock('posthog-js')

const SURVEY_ID = 'survey-1'
const RATING_QUESTION_ID = 'rating-q'
const FEEDBACK_QUESTION_ID = 'feedback-q'

const renderBanner = (dismissKey = 'test-banner'): void => {
    render(
        <FeaturePreviewFeedbackBanner
            surveyId={SURVEY_ID}
            ratingQuestionId={RATING_QUESTION_ID}
            feedbackQuestionId={FEEDBACK_QUESTION_ID}
            surface="broadcasts"
            dismissKey={dismissKey}
            prompt="Is this doing what you need?"
            modalTitle="Help shape it"
            feedbackPlaceholder="What would you change?"
            data-attr="test-banner"
        />
    )
}

const captures = (): [string, Record<string, any>][] => (posthog.capture as jest.Mock).mock.calls as any

describe('FeaturePreviewFeedbackBanner', () => {
    beforeEach(() => {
        initKeaTests()
        jest.clearAllMocks()
    })

    afterEach(() => {
        cleanup()
    })

    it('records the rating against the survey as soon as a thumb is clicked', () => {
        // Someone who rates and never opens the modal still has to count, so the rating cannot wait
        // for the written feedback.
        renderBanner()
        fireEvent.click(screen.getByTestId('test-banner-thumbs-up'))

        const sent = captures().find(([name]) => name === 'survey sent')
        expect(sent).not.toBeUndefined()
        const props = sent![1]
        expect(props.$survey_id).toBe(SURVEY_ID)
        expect(props[`$survey_response_${RATING_QUESTION_ID}`]).toBe('Useful')
        expect(props.$survey_completed).toBe(false)
        expect(props.feedback_surface).toBe('broadcasts')
    })

    it('sends the written feedback on the same submission as the rating', () => {
        // A second submission id would split one person's rating and note into two responses.
        renderBanner()
        fireEvent.click(screen.getByTestId('test-banner-thumbs-up'))
        const ratingProps = captures().find(([name]) => name === 'survey sent')![1]

        fireEvent.change(screen.getByPlaceholderText('What would you change?'), {
            target: { value: 'The recipient list matters most' },
        })
        fireEvent.click(screen.getByText('Send feedback'))

        const completed = captures().filter(([name]) => name === 'survey sent')[1][1]
        expect(completed.$survey_submission_id).toBe(ratingProps.$survey_submission_id)
        expect(completed[`$survey_response_${FEEDBACK_QUESTION_ID}`]).toBe('The recipient list matters most')
        expect(completed.$survey_completed).toBe(true)
    })

    it('does not record an impression for a banner the person already dismissed', () => {
        // LemonBanner renders nothing once dismissed, so capturing on mount would count an
        // impression nobody saw and make the response rate read far lower than it is.
        const logic = lemonBannerLogic({ dismissKey: 'test-banner-dismissed' })
        logic.mount()
        logic.actions.dismiss()

        renderBanner('test-banner-dismissed')

        expect(captures().filter(([name]) => name === 'survey shown')).toHaveLength(0)
    })

    it('ignores a second rating', () => {
        // The buttons disable after the first click; without that a double click would file two responses.
        renderBanner()
        fireEvent.click(screen.getByTestId('test-banner-thumbs-up'))
        fireEvent.click(screen.getByTestId('test-banner-thumbs-down'))

        expect(captures().filter(([name]) => name === 'survey sent')).toHaveLength(1)
    })
})
