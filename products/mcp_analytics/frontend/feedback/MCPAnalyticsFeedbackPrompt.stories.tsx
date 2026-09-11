import { Meta, StoryObj } from '@storybook/react'
import { useValues } from 'kea'
import posthog from 'posthog-js'
import { useEffect } from 'react'

import { userLogic } from 'scenes/userLogic'

import { mswDecorator } from '~/mocks/browser'

import { MCPSessionDetail } from '../sessions/MCPSessionDetail'
import { mcpAnalyticsFeedbackLogic } from './mcpAnalyticsFeedbackLogic'
import { MCPAnalyticsFeedbackPrompt } from './MCPAnalyticsFeedbackPrompt'

const meta: Meta<typeof MCPAnalyticsFeedbackPrompt> = {
    title: 'Products/MCP Analytics/Feedback prompt',
    component: MCPAnalyticsFeedbackPrompt,
    decorators: [
        (Story) => {
            const { user } = useValues(userLogic)
            const logic = mcpAnalyticsFeedbackLogic({
                userId: user?.uuid ?? '',
                sessionId: 'example-session',
                isImpersonated: false,
            })
            useValues(logic)
            useEffect(() => {
                const onSurveysLoaded = posthog.onSurveysLoaded
                posthog.onSurveysLoaded = (callback) => {
                    callback([], { isLoaded: true })
                    return () => {}
                }
                logic.actions.showPrompt(Date.now())
                return () => {
                    posthog.onSurveysLoaded = onSurveysLoaded
                }
            }, [logic])
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
