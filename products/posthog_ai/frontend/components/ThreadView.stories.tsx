import type { Meta, StoryObj } from '@storybook/react'
import { BindLogic } from 'kea'
import { useEffect } from 'react'

import { mswDecorator } from '~/mocks/browser'

import { runStreamLogic } from '../logics/runStreamLogic'
import { ThreadView } from './ThreadView'

interface ThreadFixtureProps {
    streamKey: string
    toolName: string
    title: string
    rawOutput: unknown
}

const meta: Meta<ThreadFixtureProps> = {
    title: 'Products/PostHog AI/ThreadView',
    args: {
        streamKey: 'synthetic-conversation',
        toolName: 'notebooks-create',
        title: 'Create notebook',
        rawOutput: { short_id: 'example-notebook', title: 'Synthetic notebook' },
    },
    render: ({ streamKey, toolName, title, rawOutput }) => {
        useEffect(() => {
            const logic = runStreamLogic({ streamKey })
            const unmount = logic.mount()
            logic.actions.ingestAcpFrame(
                {
                    type: 'notification',
                    notification: {
                        method: 'session/update',
                        params: {
                            update: {
                                sessionUpdate: 'tool_call',
                                toolCallId: 'synthetic-tool-call',
                                title,
                                serverName: 'posthog',
                                toolName: 'exec',
                                status: 'in_progress',
                                rawInput: { command: `call ${toolName} {}` },
                                _meta: { claudeCode: { toolName: 'mcp__posthog__exec' } },
                            },
                        },
                    },
                },
                'replay'
            )
            logic.actions.ingestAcpFrame(
                {
                    type: 'notification',
                    notification: {
                        method: 'session/update',
                        params: {
                            update: {
                                sessionUpdate: 'tool_call_update',
                                toolCallId: 'synthetic-tool-call',
                                status: 'completed',
                                rawOutput,
                            },
                        },
                    },
                },
                'replay'
            )
            return unmount
        }, [streamKey, toolName, title, rawOutput])
        return (
            <div className="w-180 h-160 border rounded">
                <BindLogic logic={runStreamLogic} props={{ streamKey }}>
                    <ThreadView />
                </BindLogic>
            </div>
        )
    },
}
export default meta

type Story = StoryObj<typeof meta>

export const ColdConversation: Story = {}
export const ColdTask: Story = { args: { streamKey: 'synthetic-task-run' } }

export const ErrorTracking: Story = {
    args: {
        toolName: 'query-error-tracking-issues-list',
        title: 'Search error tracking issues',
        rawOutput: {
            results: [
                {
                    id: '0199c0de-1111-7000-8000-0000000000aa',
                    name: 'Synthetic checkout error',
                    description: 'Example checkout request failed',
                    status: 'active',
                    library: 'web',
                    aggregations: { occurrences: 12, users: 3 },
                },
            ],
            hasMore: false,
        },
    },
}

export const SavedInsightQuery: Story = {
    args: {
        toolName: 'insight-query',
        title: 'Query saved insight',
        rawOutput: {
            query: { kind: 'HogQLQuery', query: 'SELECT 4242 AS value' },
            insight: { name: 'Synthetic saved insight', url: '/project/1/insights/example' },
            results: { columns: ['value'], results: [[4242]] },
            _posthogUrl: '/project/1/insights/example',
        },
    },
    decorators: [
        mswDecorator({
            post: {
                '/api/environments/:team_id/query/': () => [
                    200,
                    { results: [[4242]], columns: ['value'], types: [['value', 'UInt16']] },
                ],
                '/api/environments/:team_id/query/:query_kind/': () => [
                    200,
                    { results: [[4242]], columns: ['value'], types: [['value', 'UInt16']] },
                ],
            },
        }),
    ],
}
