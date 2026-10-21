import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import { Meta, StoryObj } from '@storybook/react'
import posthog, { Survey, SurveyQuestionType, SurveyType } from 'posthog-js'
import { useEffect } from 'react'

import { surveyFeedbackPromptLogic } from 'lib/logic/surveyFeedbackPrompt/surveyFeedbackPromptLogic'

import { InsightShortId } from '~/types'

import { DataChecksFeedback } from './DataChecksFeedback'
import { dataChecksFeedbackLogicProps } from './dataChecksFeedbackPrompt'

const logicProps = dataChecksFeedbackLogicProps(
    MOCK_DEFAULT_USER,
    { dashboardItemId: 'example-insight' as InsightShortId },
    'passed'
)

const survey: Survey = {
    id: logicProps.surveyId,
    name: 'Data checks usefulness',
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
            id: 'example-choice',
            type: SurveyQuestionType.Rating,
            question: logicProps.prompt.question,
            display: 'emoji',
            scale: 2,
            lowerBoundLabel: '',
            upperBoundLabel: '',
        },
        {
            id: 'example-detail',
            type: SurveyQuestionType.Open,
            question: logicProps.prompt.followUpQuestion,
            optional: true,
        },
    ],
}

const meta: Meta<typeof DataChecksFeedback> = {
    title: 'Insights/Data checks/Feedback prompt',
    component: DataChecksFeedback,
    args: { logicProps },
    beforeEach: () => {
        const { capture, onSurveysLoaded } = posthog
        posthog.capture = () => ({ uuid: 'example-event' }) as ReturnType<typeof posthog.capture>
        posthog.onSurveysLoaded = () => () => {}
        return () => {
            Object.assign(posthog, { capture, onSurveysLoaded })
        }
    },
    decorators: [
        (Story, context) => {
            const logic = surveyFeedbackPromptLogic(logicProps)
            useEffect(() => {
                const unmount = logic.mount()
                logic.actions.showPrompt(survey, Date.now(), 'example-submission')
                if (context.parameters.feedbackStage === 'followup') {
                    logic.actions.responseQueued('2', false)
                }
                if (context.parameters.feedbackStage === 'thanks') {
                    logic.actions.responseQueued('1', true)
                }
                return unmount
            }, [logic, context.parameters.feedbackStage])
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

export const Question: Story = {}
export const FollowUp: Story = { parameters: { feedbackStage: 'followup' } }
export const Thanks: Story = { parameters: { feedbackStage: 'thanks' } }
