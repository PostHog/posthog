import type { Meta, StoryObj } from '@storybook/react'
import { BindLogic } from 'kea'
import { useEffect } from 'react'

import { mswDecorator } from '~/mocks/browser'

import { runStreamLogic } from '../logics/runStreamLogic'
import type { StoredLogEntry } from '../types/wireTypes'
import type { TurnTrailer } from '../utils/turnTrailers'
import { ThreadView } from './ThreadView'
import { TurnFeedbackActions } from './TurnFeedbackActions'

interface ThreadFixtureProps {
    streamKey: string
    toolName: string
    title: string
    toolInput: Record<string, unknown>
    rawOutput: unknown
}

const meta: Meta<ThreadFixtureProps> = {
    title: 'Products/PostHog AI/ThreadView',
    args: {
        streamKey: 'synthetic-conversation',
        toolName: 'notebooks-create',
        title: 'Create notebook',
        toolInput: {},
        rawOutput: { short_id: 'example-notebook', title: 'Synthetic notebook' },
    },
    render: ({ streamKey, toolName, title, toolInput, rawOutput }) => {
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
                                rawInput: { command: `call ${toolName} ${JSON.stringify(toolInput)}` },
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
        }, [streamKey, toolName, title, toolInput, rawOutput])
        return (
            <div className="w-180 max-w-full h-160 border rounded">
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

export const ExecuteSqlWithVariables: Story = {
    ...SavedInsightQuery,
    args: {
        toolName: 'execute-sql',
        title: 'Run SQL query',
        toolInput: { query: 'SELECT {variables.example_value} AS value;' },
        rawOutput: {
            content: [{ type: 'text', text: 'value\n4242' }],
            _meta: {
                'com.posthog.mcp/app_data': {
                    query: {
                        kind: 'HogQLQuery',
                        query: 'SELECT {variables.example_value} AS value',
                        variables: {
                            '0199c0de-1111-7000-8000-0000000000aa': {
                                variableId: '0199c0de-1111-7000-8000-0000000000aa',
                                code_name: 'example_value',
                            },
                        },
                    },
                },
            },
        },
    },
}

function timedNotification(timestamp: string, method: string, params: Record<string, unknown>): StoredLogEntry {
    return { type: 'notification', timestamp, notification: { method, params } }
}

const MESSAGE_FOOTER_ENTRIES: StoredLogEntry[] = [
    timedNotification('2024-03-11T14:02:10Z', '_client/human_message', {
        content: 'How many users signed up last week?',
    }),
    timedNotification('2024-03-11T14:02:18Z', 'session/update', {
        update: {
            sessionUpdate: 'agent_message_chunk',
            messageId: 'synthetic-answer',
            content: { type: 'text', text: 'Signups grew week over week. See the trend below.' },
        },
    }),
    timedNotification('2024-03-11T14:02:20Z', '_posthog/turn_complete', {}),
]

function renderSyntheticTurnTrailer(trailer: TurnTrailer): JSX.Element {
    return (
        <TurnFeedbackActions
            sessionId="synthetic-task"
            turnIndex={trailer.turnIndex}
            run={{ taskId: 'synthetic-task' }}
            turnText={trailer.turnText}
            timestamp={trailer.timestamp}
        />
    )
}

export const MessageFooters: Story = {
    args: { streamKey: 'synthetic-message-footers' },
    parameters: {
        mockDate: '2024-03-11T14:05:00Z',
        pseudo: { hover: ['[data-message-type="human"]'] },
    },
    render: ({ streamKey }) => {
        useEffect(() => {
            const logic = runStreamLogic({ streamKey })
            const unmount = logic.mount()
            // The logic keeps its state across the strict-mode effect rerun, and human messages do not dedupe.
            if (logic.values.threadItems.length === 0) {
                for (const entry of MESSAGE_FOOTER_ENTRIES) {
                    logic.actions.ingestAcpFrame(entry, 'replay')
                }
            }
            return unmount
        }, [streamKey])
        return (
            <div className="w-180 max-w-full h-160 border rounded">
                <BindLogic logic={runStreamLogic} props={{ streamKey }}>
                    <ThreadView renderTurnTrailer={renderSyntheticTurnTrailer} />
                </BindLogic>
            </div>
        )
    },
}
