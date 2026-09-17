import type { Meta, StoryObj } from '@storybook/react'
import { BindLogic } from 'kea'
import { useEffect } from 'react'

import { mswDecorator } from '~/mocks/browser'
import { mockIntegration } from '~/test/mocks'

import { runStreamLogic } from '../logics/runStreamLogic'
import { slackDestinationLogic } from '../logics/slackDestinationLogic'
import { suggestionActionLogic } from '../logics/suggestionActionLogic'
import type { AcceptedSuggestion } from '../utils/acceptSuggestion'
import { ThreadView } from './ThreadView'
import { TurnFeedbackActions } from './TurnFeedbackActions'
import { TurnSuggestionCard } from './TurnSuggestionCard'

type Outcome = 'offered' | 'ready' | 'waiting_for_slack' | 'created' | 'failed'
type Kind = 'scout' | 'watch_scout' | 'notebook' | 'incident_notebook' | 'alert' | 'subscription' | 'error_alert'

interface StoryArgs {
    kind: Kind
    outcome: Outcome
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
        title: 'Get this every week in Slack',
        description: 'A scout can rerun this count on a schedule and post what moved.',
        scout: {
            mode: 'report',
            displayName: 'Weekly signups',
            description: 'Counts signed_up events for the last 7 days and compares with the week before.',
            body: '# Weekly signups\n\nCount `signed_up` events for the last 7 days...',
            cadence: 'weekly',
        },
    }),
]

const WATCH_SCOUT_TURN_FRAMES: Record<string, unknown>[] = [
    notification('_posthog/run_started', {}),
    notification('_posthog/user_message', { content: 'Is checkout conversion down this week?' }),
    sessionUpdate({
        sessionUpdate: 'tool_call',
        toolCallId: 'story-funnel',
        title: 'Query funnel',
        serverName: 'posthog',
        toolName: 'exec',
        status: 'completed',
        rawInput: {
            command: 'call query-funnel {"series":[{"event":"checkout_started"},{"event":"order_completed"}]}',
        },
        rawOutput: { content: [{ type: 'text', text: 'conversion 31.2% (last week 33.8%)' }] },
        _meta: { claudeCode: { toolName: 'mcp__posthog__exec' } },
    }),
    sessionUpdate({
        sessionUpdate: 'agent_message_chunk',
        messageId: 'story-watch-answer',
        content: {
            type: 'text',
            text: 'Checkout conversion is **31.2%** this week against 33.8% last week, a 2.6 point drop. The dip is within the range of the last two months, so nothing looks broken yet.',
        },
    }),
    notification('_posthog/turn_complete', { stopReason: 'end_turn' }),
    notification('_posthog/turn_suggestion', {
        turnIndex: 0,
        kind: 'scout',
        intent: 'metric_state',
        confidence: 0.9,
        title: 'Get a Slack message if this keeps falling',
        description: 'A scout can check checkout conversion every day and stay quiet until it drops below 30%.',
        scout: {
            mode: 'watch',
            displayName: 'Checkout conversion watch',
            description: 'Checks the checkout funnel daily and posts only when conversion falls below 30%.',
            body: '# Checkout conversion watch\n\nRun the checkout funnel for the last 7 days...',
            cadence: 'daily',
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
        title: 'Save this investigation to a notebook',
        description: 'Keep the question, the queries and the findings together to share and revisit.',
        notebook: {
            title: 'Why signups dropped on Tuesday',
            summary:
                'A checkout error on the payment step cut Tuesday signups by a third until the 14:10 release was fixed.',
            incident: null,
        },
    }),
]

const INCIDENT_NOTEBOOK_TURN_FRAMES: Record<string, unknown>[] = [
    ...NOTEBOOK_TURN_FRAMES.slice(0, -1),
    notification('_posthog/turn_suggestion', {
        turnIndex: 0,
        kind: 'notebook',
        intent: 'diagnostic',
        confidence: 0.91,
        title: 'Write this up as an incident',
        description: 'A notebook with the timeline, the cause, the evidence and the fix, ready to share.',
        notebook: {
            title: 'Incident: checkout error cut Tuesday signups',
            summary: 'A checkout error on the payment step cut Tuesday signups by a third for about three hours.',
            incident: {
                timeline:
                    '- 14:10 release deployed\n- 14:25 first payment step errors\n- 17:05 fix released, signups recover',
                cause: 'The 14:10 release broke the payment step on checkout.',
                fix: 'The fix went out at 17:05 and signups recovered on Wednesday.',
            },
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
        title: 'Get a Slack message when signups drop',
        description: 'An alert on the saved insight posts to a channel when a day comes in well under the day before.',
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
        title: 'Get this chart in Slack every Monday',
        description: 'A subscription posts the saved insight to a channel on a schedule, no agent run needed.',
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
        title: 'Get told if this error comes back',
        description: 'An alert on the issue posts to Slack the moment it reopens.',
        errorAlert: {
            issueId: '0199c0de-1111-7000-8000-0000000000aa',
            issueName: 'TypeError: cart.total is undefined',
        },
    }),
]

const FRAMES_BY_KIND: Record<Kind, Record<string, unknown>[]> = {
    scout: SCOUT_TURN_FRAMES,
    watch_scout: WATCH_SCOUT_TURN_FRAMES,
    notebook: NOTEBOOK_TURN_FRAMES,
    incident_notebook: INCIDENT_NOTEBOOK_TURN_FRAMES,
    alert: ALERT_TURN_FRAMES,
    subscription: SUBSCRIPTION_TURN_FRAMES,
    error_alert: ERROR_ALERT_TURN_FRAMES,
}

const SAVED_NOTEBOOK = {
    id: 'notebook-1',
    short_id: 'nb12345',
    title: 'Why signups dropped on Tuesday',
    version: 1,
}

const CREATED_SCOUT = {
    created: true,
    skill: {
        id: 'skill-1',
        name: 'weekly-signups',
        description: 'Counts signed_up events for the last 7 days.',
        version: 1,
        allowed_tools: ['scout-emit-report'],
    },
    config: {
        id: 'config-1',
        skill_name: 'weekly-signups',
        description: 'Counts signed_up events for the last 7 days.',
        display_name: 'Weekly signups',
        scout_origin: 'custom',
        enabled: true,
        emit: true,
        run_cron_schedule: '0 9 * * 1',
    },
}

const CREATED_ALERT = {
    id: 'alert-1',
    name: 'Daily signups: 20% decrease',
    insight: 42,
    insight_short_id: 'abc123',
    subscribed_users: [],
    threshold: { configuration: { type: 'percentage', bounds: { upper: 0.2 } } },
    state: 'Not firing',
    enabled: true,
}

const CREATED_SUBSCRIPTION = {
    id: 11,
    insight: 42,
    insight_short_id: 'abc123',
    resource_type: 'insight',
    target_type: 'slack',
    target_value: 'C0123456789|#growth',
    frequency: 'weekly',
    interval: 1,
    byweekday: ['monday'],
    start_date: '2026-09-21T09:00:00Z',
    title: 'Weekly report: Daily signups',
    summary: 'sent every week on Monday',
}

const CREATED_HOG_FUNCTION = {
    id: 'hog-1',
    type: 'internal_destination',
    template_id: 'template-slack',
    name: 'Post to Slack on issue reopened: #growth',
    enabled: true,
}

type LogicProps = { streamKey: string; turnIndex: number; sessionId: string }

const SLACK_KINDS: Kind[] = ['scout', 'watch_scout', 'alert', 'subscription', 'error_alert']

const ACCEPTED_BY_KIND: Record<Kind, AcceptedSuggestion> = {
    scout: { url: '/inbox/scouts/weekly-signups', slackConnected: true },
    watch_scout: { url: '/inbox/scouts/checkout-conversion-watch', slackConnected: true },
    notebook: { url: '/notebooks/nb12345', slackConnected: true },
    incident_notebook: { url: '/notebooks/nb12345', slackConnected: true },
    alert: { url: '/alerts?alert_type=insights&alert_id=alert-1', slackConnected: true },
    subscription: { url: '/insights/abc123/subscriptions/11', slackConnected: true },
    error_alert: { url: '/error_tracking/alerts/hog-1', slackConnected: true },
}

function mountStory(kind: Kind, logicProps: LogicProps, outcome: Outcome): () => void {
    const logic = suggestionActionLogic(logicProps)
    const unmount = logic.mount()
    if (SLACK_KINDS.includes(kind)) {
        const slack = slackDestinationLogic(logicProps)
        if (outcome === 'waiting_for_slack') {
            slack.actions.connectSlackClicked()
        } else if (outcome !== 'offered') {
            slack.actions.setSlackIntegrationId(mockIntegration.id)
            slack.actions.setSlackChannel('C0123456789|#growth')
        }
    }
    if (outcome === 'created') {
        logic.actions.acceptSuccess(ACCEPTED_BY_KIND[kind])
    } else if (outcome === 'failed') {
        logic.actions.acceptFailure('Request failed with status 500')
    }
    return unmount
}

function TurnSuggestionStory({ kind, outcome }: { kind: Kind; outcome: Outcome }): JSX.Element {
    useEffect(() => {
        const stream = runStreamLogic({ streamKey: STREAM_KEY })
        const unmountStream = stream.mount()
        for (const frame of FRAMES_BY_KIND[kind]) {
            stream.actions.ingestAcpFrame(frame as any, 'replay')
        }
        const logicProps = { streamKey: STREAM_KEY, turnIndex: 0, sessionId: SESSION_ID }
        const unmountSuggestion = mountStory(kind, logicProps, outcome)
        return () => {
            unmountSuggestion()
            unmountStream()
        }
    }, [kind, outcome])

    return (
        <div className="w-180 max-w-full rounded border p-4">
            <BindLogic logic={runStreamLogic} props={{ streamKey: STREAM_KEY }}>
                <ThreadView
                    virtualized={false}
                    renderTurnTrailer={(trailer) => (
                        <>
                            <TurnSuggestionCard
                                streamKey={STREAM_KEY}
                                turnIndex={trailer.turnIndex}
                                isLastTurn={trailer.isLastTurn}
                                sessionId={SESSION_ID}
                                revealDelayMs={0}
                            />
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

function mocksFor(slackConnected: boolean): Parameters<typeof mswDecorator>[0] {
    const integrations = { results: slackConnected ? [mockIntegration] : [] }
    return {
        get: {
            '/api/environments/:team_id/integrations/': integrations,
            '/api/projects/:team_id/integrations/': integrations,
            '/api/environments/:team_id/integrations/:id/channels/': CHANNELS,
        },
        post: {
            '/api/projects/:team_id/signals/scout/': () => [201, CREATED_SCOUT],
            '/api/projects/:team_id/notebooks/': () => [201, SAVED_NOTEBOOK],
            '/api/projects/:team_id/alerts/': () => [201, CREATED_ALERT],
            '/api/projects/:team_id/alerts/:id/destinations/': () => [201, { hog_function_ids: ['hog-1'] }],
            '/api/projects/:team_id/subscriptions/': () => [201, CREATED_SUBSCRIPTION],
            '/api/projects/:team_id/hog_functions/': () => [201, CREATED_HOG_FUNCTION],
            '/api/environments/:team_id/query/': () => [200, QUERY_RESULT],
            '/api/environments/:team_id/query/:query_kind/': () => [200, QUERY_RESULT],
        },
    }
}

const meta: Meta<StoryArgs> = {
    title: 'Products/PostHog AI/TurnSuggestionCard',
    parameters: { mockDate: '2026-09-16', testOptions: { waitForLoadersToDisappear: true } },
    args: { kind: 'scout', outcome: 'offered' },
    decorators: [mswDecorator(mocksFor(true))],
    render: ({ kind, outcome }) => <TurnSuggestionStory kind={kind} outcome={outcome} />,
}
export default meta

type Story = StoryObj<StoryArgs>

export const ScoutSuggestion: Story = {}

export const ScoutSuggestionWithoutSlack: Story = { decorators: [mswDecorator(mocksFor(false))] }

export const ScoutSuggestionWaitingForSlack: Story = {
    args: { outcome: 'waiting_for_slack' },
    decorators: [mswDecorator(mocksFor(false))],
}

export const ScoutSuggestionReadyToCreate: Story = { args: { outcome: 'ready' } }

export const ScoutCreated: Story = { args: { outcome: 'created' } }

export const ScoutCreationFailed: Story = { args: { outcome: 'failed' } }

export const NotebookSuggestion: Story = { args: { kind: 'notebook' } }

export const NotebookSaved: Story = { args: { kind: 'notebook', outcome: 'created' } }

export const NotebookSaveFailed: Story = { args: { kind: 'notebook', outcome: 'failed' } }

export const WatchScoutSuggestion: Story = { args: { kind: 'watch_scout', outcome: 'ready' } }

export const IncidentNotebookSuggestion: Story = { args: { kind: 'incident_notebook' } }

export const AlertSuggestion: Story = { args: { kind: 'alert', outcome: 'ready' } }

export const AlertCreated: Story = { args: { kind: 'alert', outcome: 'created' } }

export const SubscriptionSuggestion: Story = { args: { kind: 'subscription', outcome: 'ready' } }

export const SubscriptionCreated: Story = { args: { kind: 'subscription', outcome: 'created' } }

export const ErrorAlertSuggestion: Story = { args: { kind: 'error_alert', outcome: 'ready' } }

export const ErrorAlertCreated: Story = { args: { kind: 'error_alert', outcome: 'created' } }
