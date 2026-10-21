import { Meta, StoryObj } from '@storybook/react'
import posthog, { Survey, SurveyQuestionType, SurveyType } from 'posthog-js'
import { useEffect } from 'react'

import { DataChecksFeedback } from './DataChecksFeedback'
import {
    DATA_CHECKS_FEEDBACK_RATINGS,
    DATA_CHECKS_FEEDBACK_SURVEY_ID,
    dataChecksFeedbackLogic,
} from './dataChecksFeedbackLogic'

const survey: Survey = {
    id: DATA_CHECKS_FEEDBACK_SURVEY_ID,
    name: 'Insight data checks usefulness',
    type: SurveyType.API,
    start_date: '2026-01-01T00:00:00Z',
    feature_flag_keys: null,
    linked_flag_key: null,
    targeting_flag_key: null,
    internal_targeting_flag_key: null,
    appearance: null,
    conditions: null,
    end_date: null,
    current_iteration: null,
    current_iteration_start_date: null,
    questions: [
        {
            id: 'example-rating',
            type: SurveyQuestionType.Rating,
            question: 'Were these checks useful?',
            display: 'emoji',
            scale: 2,
            lowerBoundLabel: '',
            upperBoundLabel: '',
        },
        {
            id: 'example-note',
            type: SurveyQuestionType.Open,
            question: 'What would make these checks more useful?',
            optional: true,
        },
    ],
}

const meta: Meta<typeof DataChecksFeedback> = {
    title: 'Insights/Data checks/Feedback prompt',
    component: DataChecksFeedback,
    beforeEach: () => {
        const { capture, onSurveysLoaded, onFeatureFlags } = posthog
        posthog.capture = () => ({ uuid: 'example-event' }) as ReturnType<typeof posthog.capture>
        posthog.onSurveysLoaded = () => () => {}
        posthog.onFeatureFlags = () => () => {}
        return () => {
            Object.assign(posthog, { capture, onSurveysLoaded, onFeatureFlags })
        }
    },
    decorators: [
        (Story, context) => {
            const logic = dataChecksFeedbackLogic({ userId: context.args.userId })
            const stage = context.parameters.feedbackStage
            useEffect(() => {
                const unmount = logic.mount()
                logic.actions.setSurvey(survey)
                if (stage === 'note' || stage === 'thanks') {
                    logic.actions.rate(DATA_CHECKS_FEEDBACK_RATINGS.NOT_USEFUL)
                }
                if (stage === 'thanks') {
                    logic.actions.submitNote()
                }
                return unmount
            }, [logic, stage])
            return (
                <div className="w-96 rounded border p-3" data-quill>
                    <Story />
                </div>
            )
        },
    ],
}
export default meta

type Story = StoryObj<typeof meta>

// Each story has its own person, because a rating is remembered in local storage.
export const Question: Story = { args: { userId: 'example-question' } }
export const Note: Story = { args: { userId: 'example-note' }, parameters: { feedbackStage: 'note' } }
export const Thanks: Story = { args: { userId: 'example-thanks' }, parameters: { feedbackStage: 'thanks' } }
