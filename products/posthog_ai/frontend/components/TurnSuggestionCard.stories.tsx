import type { Meta, StoryObj } from '@storybook/react'
import { BindLogic } from 'kea'
import { useEffect } from 'react'

import { mswDecorator } from '~/mocks/browser'
import { mockIntegration } from '~/test/mocks'

import { notebookSuggestionLogic } from '../logics/notebookSuggestionLogic'
import { runStreamLogic } from '../logics/runStreamLogic'
import { scoutSuggestionLogic } from '../logics/scoutSuggestionLogic'
import { ThreadView } from './ThreadView'
import { TurnFeedbackActions } from './TurnFeedbackActions'
import { TurnSuggestionCard } from './TurnSuggestionCard'

type Outcome = 'offered' | 'created' | 'failed'
type Kind = 'scout' | 'notebook'

interface StoryArgs {
    kind: Kind
    slackConnected: boolean
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
        title: 'Save this investigation to a notebook',
        description: 'Keep the question, the queries and the findings together to share and revisit.',
        notebook: {
            title: 'Why signups dropped on Tuesday',
            summary:
                'A checkout error on the payment step cut Tuesday signups by a third until the 14:10 release was fixed.',
        },
    }),
]

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

function TurnSuggestionStory({ kind, outcome }: { kind: Kind; outcome: Outcome }): JSX.Element {
    useEffect(() => {
        const stream = runStreamLogic({ streamKey: STREAM_KEY })
        const unmountStream = stream.mount()
        for (const frame of kind === 'scout' ? SCOUT_TURN_FRAMES : NOTEBOOK_TURN_FRAMES) {
            stream.actions.ingestAcpFrame(frame as any, 'replay')
        }
        const logicProps = { streamKey: STREAM_KEY, turnIndex: 0, sessionId: SESSION_ID }
        const unmountSuggestion =
            kind === 'scout'
                ? (() => {
                      const suggestion = scoutSuggestionLogic(logicProps)
                      const unmount = suggestion.mount()
                      if (outcome !== 'offered') {
                          suggestion.actions.setSlackIntegrationId(mockIntegration.id)
                          suggestion.actions.setSlackChannel('C0123456789|#growth')
                      }
                      if (outcome === 'created') {
                          suggestion.actions.createScoutSuccess(CREATED_SCOUT as any)
                      } else if (outcome === 'failed') {
                          suggestion.actions.createScoutFailure('Request failed with status 500')
                      }
                      return unmount
                  })()
                : (() => {
                      const suggestion = notebookSuggestionLogic(logicProps)
                      const unmount = suggestion.mount()
                      if (outcome === 'created') {
                          suggestion.actions.saveNotebookSuccess(SAVED_NOTEBOOK as any)
                      } else if (outcome === 'failed') {
                          suggestion.actions.saveNotebookFailure('Request failed with status 500')
                      }
                      return unmount
                  })()
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
            '/api/environments/:team_id/query/': () => [200, QUERY_RESULT],
            '/api/environments/:team_id/query/:query_kind/': () => [200, QUERY_RESULT],
        },
    }
}

const meta: Meta<StoryArgs> = {
    title: 'Products/PostHog AI/TurnSuggestionCard',
    parameters: { mockDate: '2026-09-16', testOptions: { waitForLoadersToDisappear: true } },
    args: { kind: 'scout', slackConnected: true, outcome: 'offered' },
    decorators: [mswDecorator(mocksFor(true))],
    render: ({ kind, outcome }) => <TurnSuggestionStory kind={kind} outcome={outcome} />,
}
export default meta

type Story = StoryObj<StoryArgs>

export const ScoutSuggestion: Story = {}

export const ScoutSuggestionWithoutSlack: Story = {
    args: { slackConnected: false },
    decorators: [mswDecorator(mocksFor(false))],
}

export const ScoutCreated: Story = { args: { outcome: 'created' } }

export const ScoutCreationFailed: Story = { args: { outcome: 'failed' } }

export const NotebookSuggestion: Story = { args: { kind: 'notebook' } }

export const NotebookSaved: Story = { args: { kind: 'notebook', outcome: 'created' } }
