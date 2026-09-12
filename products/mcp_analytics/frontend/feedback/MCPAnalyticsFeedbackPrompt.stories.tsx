import { Meta, StoryObj } from '@storybook/react'
import { useValues } from 'kea'
import posthog, { Survey, SurveyType, SurveyQuestionType } from 'posthog-js'
import { useEffect } from 'react'

import { userLogic } from 'scenes/userLogic'

import { mswDecorator } from '~/mocks/browser'

import { MCPSessionDetail } from '../sessions/MCPSessionDetail'
import { MCP_ANALYTICS_USEFULNESS_SURVEY_ID } from './constants'
import { mcpAnalyticsFeedbackLogic } from './mcpAnalyticsFeedbackLogic'
import { MCPAnalyticsFeedbackPrompt } from './MCPAnalyticsFeedbackPrompt'

const survey: Survey = {
    id: MCP_ANALYTICS_USEFULNESS_SURVEY_ID,
    name: 'Session usefulness',
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
            question: 'Did this session help you find what you needed?',
            display: 'emoji',
            scale: 2,
            lowerBoundLabel: '',
            upperBoundLabel: '',
        },
        {
            id: 'example-detail',
            type: SurveyQuestionType.Open,
            question: 'What did you learn, or what was missing?',
            optional: true,
        },
    ],
}

const meta: Meta<typeof MCPAnalyticsFeedbackPrompt> = {
    title: 'Products/MCP Analytics/Feedback prompt',
    component: MCPAnalyticsFeedbackPrompt,
    decorators: [
        (Story, context) => {
            const { user } = useValues(userLogic)
            const logic = mcpAnalyticsFeedbackLogic({
                userId: user?.uuid ?? '',
                sessionId: 'example-session',
                isImpersonated: false,
            })
            useValues(logic)
            useEffect(() => {
                const onSurveysLoaded = posthog.onSurveysLoaded
                const capture = posthog.capture
                posthog.capture = () => ({ uuid: 'example-event' }) as ReturnType<typeof posthog.capture>
                posthog.onSurveysLoaded = (callback) => {
                    callback([], { isLoaded: true })
                    return () => {}
                }
                logic.actions.showPrompt(survey, Date.now(), 'example-submission')
                if (context.parameters.feedbackStage === 'followup') {
                    logic.actions.responseQueued('2', false)
                }
                if (context.parameters.feedbackStage === 'error') {
                    logic.actions.responseQueued('2', false)
                    logic.actions.setDetail('Found a tool call that needs a clearer error message.')
                    logic.actions.responseFailed()
                }
                if (context.parameters.feedbackStage === 'thanks') {
                    logic.actions.responseQueued('1', true)
                }
                return () => {
                    posthog.onSurveysLoaded = onSurveysLoaded
                    posthog.capture = capture
                }
            }, [logic, context.parameters.feedbackStage])
            return <Story />
        },
    ],
}
export default meta

type Story = StoryObj<typeof meta>

export const Default: Story = {
    render: () => (
        <div className="w-[800px] max-w-full">
            <MCPAnalyticsFeedbackPrompt sessionId="example-session" />
        </div>
    ),
}

export const Narrow: Story = {
    render: () => (
        <div className="w-[520px] max-w-full">
            <MCPAnalyticsFeedbackPrompt sessionId="example-session" />
        </div>
    ),
}

export const SessionReview: Story = {
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/mcp_analytics/sessions/': {
                    results: [
                        {
                            session_id: 'example-session',
                            distinct_id: 'example-user',
                            session_start: '2026-09-01T12:00:00Z',
                            session_end: '2026-09-01T12:00:02Z',
                            tool_calls: 1,
                            intent: 'Check the status of a deployment.',
                            mcp_client_name: 'Example client',
                        },
                    ],
                    has_next: false,
                },
                '/api/projects/:team_id/mcp_analytics/sessions/:session_id/tool_calls/': {
                    results: [
                        {
                            event_id: 'example-call',
                            timestamp: '2026-09-01T12:00:01Z',
                            tool_name: 'deployment-status',
                            intent: 'Check whether the deployment completed.',
                            is_error: false,
                            duration_ms: 240,
                        },
                    ],
                    has_next: false,
                },
            },
        }),
    ],
    render: () => (
        <div className="w-[520px] max-w-full h-[400px] rounded border border-primary">
            <MCPSessionDetail />
        </div>
    ),
}

export const FollowUp: Story = { ...Narrow, parameters: { feedbackStage: 'followup' } }
export const Error: Story = { ...Narrow, parameters: { feedbackStage: 'error' } }
export const Thanks: Story = { ...Narrow, parameters: { feedbackStage: 'thanks' } }
