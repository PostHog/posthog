import type { Meta, StoryObj } from '@storybook/react'
import { BindLogic } from 'kea'
import { useEffect } from 'react'

import { mswDecorator } from '~/mocks/browser'
import { mockIntegration } from '~/test/mocks'

import { runStreamLogic } from '../logics/runStreamLogic'
import { ThreadView } from './ThreadView'
import { TurnFeedbackActions } from './TurnFeedbackActions'
import { TurnSuggestionCard } from './TurnSuggestionCard'

type Kind = 'scout' | 'notebook' | 'alert' | 'subscription' | 'error_alert'

interface StoryArgs {
    kind: Kind
    /** The scene width next to an open side panel on a 1280px window. */
    narrow?: boolean
}

const STREAM_KEY = 'turn-suggestion-story'
const SESSION_ID = 'turn-suggestion-story-task'

const notification = (method: string, params: Record<string, unknown>): Record<string, unknown> => ({
    type: 'notification',
    notification: { method, params },
})

const sessionUpdate = (update: Record<string, unknown>): Record<string, unknown> =>
    notification('session/update', { update })

const SCOUT_TURN_FRAMES: Record<string, unknown>[] = [
    notification('_posthog/run_started', {}),
    notification('_posthog/user_message', { content: 'How many signups did we get this week?' }),
    sessionUpdate({
        sessionUpdate: 'tool_call',
        toolCallId: 'story-query',
        title: 'Run SQL query',
        serverName: 'posthog',
        toolName: 'exec',
        status: 'completed',
        rawInput: {
            command:
                'call execute-sql {"query":"SELECT toStartOfDay(timestamp) AS day, count() AS signups FROM events WHERE event = \'signed_up\' AND timestamp > now() - INTERVAL 7 DAY GROUP BY day ORDER BY day"}',
        },
        rawOutput: { content: [{ type: 'text', text: 'day,signups\n2026-09-15,58' }] },
        _meta: { claudeCode: { toolName: 'mcp__posthog__exec' } },
    }),
    sessionUpdate({
        sessionUpdate: 'agent_message_chunk',
        messageId: 'story-answer',
        content: {
            type: 'text',
            text: 'You had **412 signups** in the last 7 days, up 8% on the week before. Tuesday was the strongest day with 74.',
        },
    }),
    notification('_posthog/turn_complete', { stopReason: 'end_turn' }),
    notification('_posthog/turn_suggestion', {
        turnIndex: 0,
        kind: 'scout',
        intent: 'metric_state',
        confidence: 0.93,
        title: 'Get this in Slack every week',
        description: 'A scout runs this analysis again every week and posts the results to Slack.',
        scout: {
            mode: 'report',
            displayName: 'Weekly signups',
            description: 'Counts signed_up events for the last 7 days and compares with the week before.',
            body: '# Weekly signups\n\nCount `signed_up` events for the last 7 days...',
            cadence: 'weekly',
        },
    }),
]

const NOTEBOOK_TURN_FRAMES: Record<string, unknown>[] = [
    notification('_posthog/run_started', {}),
    notification('_posthog/user_message', { content: 'Why did signups drop on Tuesday?' }),
    sessionUpdate({
        sessionUpdate: 'tool_call',
        toolCallId: 'story-daily',
        title: 'Run SQL query',
        serverName: 'posthog',
        toolName: 'exec',
        status: 'completed',
        rawInput: {
            command:
                'call execute-sql {"query":"SELECT toStartOfDay(timestamp) AS day, count() AS signups FROM events WHERE event = \'signed_up\' AND timestamp > now() - INTERVAL 7 DAY GROUP BY day ORDER BY day"}',
        },
        rawOutput: {
            query: {
                kind: 'HogQLQuery',
                query: "SELECT toStartOfDay(timestamp) AS day, count() AS signups FROM events WHERE event = 'signed_up' AND timestamp > now() - INTERVAL 7 DAY GROUP BY day ORDER BY day",
            },
            results: [['2026-09-15', 58]],
            columns: ['day', 'signups'],
        },
        _meta: { claudeCode: { toolName: 'mcp__posthog__exec' } },
    }),
    sessionUpdate({
        sessionUpdate: 'tool_call',
        toolCallId: 'story-recordings',
        title: 'Search recordings',
        serverName: 'posthog',
        toolName: 'exec',
        status: 'completed',
        rawInput: { command: 'call query-session-recordings-list {"date_from":"-7d","filter_test_accounts":true}' },
        rawOutput: { results: [], has_next: false },
        _meta: { claudeCode: { toolName: 'mcp__posthog__exec' } },
    }),
    sessionUpdate({
        sessionUpdate: 'agent_message_chunk',
        messageId: 'story-diagnosis',
        content: {
            type: 'text',
            text: "Tuesday's signups fell to **41**, a third below the weekday average. Recordings from that afternoon show a checkout error on the payment step, and the drop lines up with the release at 14:10. Signups recovered on Wednesday after the fix went out.",
        },
    }),
    notification('_posthog/turn_complete', { stopReason: 'end_turn' }),
    notification('_posthog/turn_suggestion', {
        turnIndex: 0,
        kind: 'notebook',
        intent: 'diagnostic',
        confidence: 0.88,
        title: 'Save this conversation as a notebook',
        description: 'The notebook keeps the messages, and each query becomes a cell you can run again.',
        notebook: {
            title: 'Why signups dropped on Tuesday',
            summary:
                'A checkout error on the payment step cut Tuesday signups by a third until the 14:10 release was fixed.',
            incident: null,
        },
    }),
]

const SAVED_INSIGHT_FRAMES: Record<string, unknown>[] = [
    notification('_posthog/run_started', {}),
    notification('_posthog/user_message', { content: 'Save a chart of daily signups for the last month' }),
    sessionUpdate({
        sessionUpdate: 'tool_call',
        toolCallId: 'story-insight',
        title: 'Create insight',
        serverName: 'posthog',
        toolName: 'exec',
        status: 'completed',
        rawInput: { command: 'call insight-create {"name":"Daily signups"}' },
        rawOutput: {
            id: 42,
            short_id: 'abc123',
            name: 'Daily signups',
            query: { kind: 'TrendsQuery', series: [{ event: 'signed_up', kind: 'EventsNode' }] },
        },
        _meta: { claudeCode: { toolName: 'mcp__posthog__exec' } },
    }),
    sessionUpdate({
        sessionUpdate: 'agent_message_chunk',
        messageId: 'story-insight-answer',
        content: {
            type: 'text',
            text: 'Saved **Daily signups**: one line of signed_up events per day for the last 30 days.',
        },
    }),
    notification('_posthog/turn_complete', { stopReason: 'end_turn' }),
]

const INSIGHT_REF = { insightShortId: 'abc123', insightId: 42, insightName: 'Daily signups' }

const ALERT_TURN_FRAMES: Record<string, unknown>[] = [
    ...SAVED_INSIGHT_FRAMES,
    notification('_posthog/turn_suggestion', {
        turnIndex: 0,
        kind: 'alert',
        intent: 'metric_state',
        confidence: 0.9,
        title: 'Get an alert when this drops',
        description: 'The alert checks once a day, compares with the day before, and posts to Slack.',
        alert: { ...INSIGHT_REF, direction: 'decrease', changePercent: 20 },
    }),
]

const SUBSCRIPTION_TURN_FRAMES: Record<string, unknown>[] = [
    ...SAVED_INSIGHT_FRAMES,
    notification('_posthog/turn_suggestion', {
        turnIndex: 0,
        kind: 'subscription',
        intent: 'metric_state',
        confidence: 0.87,
        title: 'Send this chart to Slack every week',
        description: 'The chart posts to a Slack channel every Monday at 9:00.',
        subscription: { ...INSIGHT_REF, cadence: 'weekly' },
    }),
]

const ERROR_ALERT_TURN_FRAMES: Record<string, unknown>[] = [
    notification('_posthog/run_started', {}),
    notification('_posthog/user_message', { content: 'Why did checkout break on Tuesday?' }),
    sessionUpdate({
        sessionUpdate: 'tool_call',
        toolCallId: 'story-issues',
        title: 'List issues',
        serverName: 'posthog',
        toolName: 'exec',
        status: 'completed',
        rawInput: { command: 'call query-error-tracking-issues-list {"date_from":"-7d"}' },
        rawOutput: {
            results: [{ id: '0199c0de-1111-7000-8000-0000000000aa', name: 'TypeError: cart.total is undefined' }],
        },
        _meta: { claudeCode: { toolName: 'mcp__posthog__exec' } },
    }),
    sessionUpdate({
        sessionUpdate: 'agent_message_chunk',
        messageId: 'story-issue-answer',
        content: {
            type: 'text',
            text: 'A **TypeError on the checkout page** started at 14:25 on Tuesday, right after the 14:10 release, and stopped once the fix shipped at 17:05. It is resolved now.',
        },
    }),
    notification('_posthog/turn_complete', { stopReason: 'end_turn' }),
    notification('_posthog/turn_suggestion', {
        turnIndex: 0,
        kind: 'error_alert',
        intent: 'diagnostic',
        confidence: 0.86,
        title: 'Get an alert if this error comes back',
        description: 'Slack gets a message if this issue reopens after it was resolved.',
        errorAlert: {
            issueId: '0199c0de-1111-7000-8000-0000000000aa',
            issueName: 'TypeError: cart.total is undefined',
        },
    }),
]

const FRAMES_BY_KIND: Record<Kind, Record<string, unknown>[]> = {
    scout: SCOUT_TURN_FRAMES,
    notebook: NOTEBOOK_TURN_FRAMES,
    alert: ALERT_TURN_FRAMES,
    subscription: SUBSCRIPTION_TURN_FRAMES,
    error_alert: ERROR_ALERT_TURN_FRAMES,
}

function TurnSuggestionStory({ kind, narrow }: StoryArgs): JSX.Element {
    useEffect(() => {
        const stream = runStreamLogic({ streamKey: STREAM_KEY })
        const unmountStream = stream.mount()
        for (const frame of FRAMES_BY_KIND[kind]) {
            stream.actions.ingestAcpFrame(frame as any, 'replay')
        }
        stream.actions.setTurnSuggestionLedger({ taskId: SESSION_ID, muted: false, resolvedTurns: [] })
        return unmountStream
    }, [kind])

    return (
        <div className={`${narrow ? 'w-130' : 'w-180'} max-w-full rounded border p-4`}>
            <BindLogic logic={runStreamLogic} props={{ streamKey: STREAM_KEY }}>
                <ThreadView
                    virtualized={false}
                    renderTurnTrailer={(trailer) => (
                        <>
                            {trailer.isLastTurn ? (
                                <TurnSuggestionCard
                                    streamKey={STREAM_KEY}
                                    turnIndex={trailer.turnIndex}
                                    sessionId={SESSION_ID}
                                    revealDelayMs={0}
                                />
                            ) : null}
                            <TurnFeedbackActions
                                sessionId={SESSION_ID}
                                turnIndex={trailer.turnIndex}
                                run={{ taskId: SESSION_ID }}
                                traceId={trailer.traceId}
                                turnText={trailer.turnText}
                            />
                        </>
                    )}
                />
            </BindLogic>
        </div>
    )
}

const CHANNELS = {
    channels: [
        { id: 'C0123456789', name: 'growth', is_private: false, is_ext_shared: false, is_member: true },
        { id: 'C0987654321', name: 'product', is_private: false, is_ext_shared: false, is_member: true },
    ],
    lastRefreshedAt: '2026-09-16T09:00:00Z',
}

const QUERY_RESULT = {
    results: [['2026-09-15', 58]],
    columns: ['day', 'signups'],
    types: [
        ['day', 'Date'],
        ['signups', 'UInt64'],
    ],
}

function mocks(): Parameters<typeof mswDecorator>[0] {
    const integrations = { results: [mockIntegration] }
    return {
        get: {
            '/api/environments/:team_id/integrations/': integrations,
            '/api/projects/:team_id/integrations/': integrations,
            '/api/environments/:team_id/integrations/:id/channels/': CHANNELS,
        },
        post: {
            '/api/environments/:team_id/query/': () => [200, QUERY_RESULT],
            '/api/environments/:team_id/query/:query_kind/': () => [200, QUERY_RESULT],
        },
    }
}

const meta: Meta<StoryArgs> = {
    title: 'Products/PostHog AI/TurnSuggestionCard',
    parameters: { mockDate: '2026-09-16', testOptions: { waitForLoadersToDisappear: true } },
    args: { kind: 'scout' },
    decorators: [mswDecorator(mocks())],
    render: ({ kind, narrow }) => <TurnSuggestionStory kind={kind} narrow={narrow} />,
}
export default meta

type Story = StoryObj<StoryArgs>

export const ScoutSuggestion: Story = {}

export const ScoutSuggestionNarrow: Story = { args: { kind: 'scout', narrow: true } }

export const NotebookSuggestion: Story = { args: { kind: 'notebook' } }

export const AlertSuggestion: Story = { args: { kind: 'alert' } }

export const SubscriptionSuggestion: Story = { args: { kind: 'subscription' } }

export const ErrorAlertSuggestion: Story = { args: { kind: 'error_alert' } }
