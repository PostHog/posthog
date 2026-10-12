import type { Meta, StoryObj } from '@storybook/react'
import { BindLogic } from 'kea'
import { useEffect } from 'react'

import { runStreamLogic } from '../../logics/runStreamLogic'
import type { StoredLogEntry } from '../../types/wireTypes'
import type { TurnTrailer } from '../../utils/turnTrailers'
import { ThreadView } from '../ThreadView'
import { TurnFeedbackActions } from '../TurnFeedbackActions'

function notification(timestamp: string, method: string, params: Record<string, unknown>): StoredLogEntry {
    return { type: 'notification', timestamp, notification: { method, params } }
}

function update(timestamp: string, sessionUpdate: Record<string, unknown>): StoredLogEntry {
    return notification(timestamp, 'session/update', { update: sessionUpdate })
}

function toolCall(
    timestamp: string,
    id: string,
    toolName: string,
    title: string,
    rawInput: Record<string, unknown>,
    kind?: string
): StoredLogEntry {
    return update(timestamp, {
        sessionUpdate: 'tool_call',
        toolCallId: id,
        title,
        kind,
        status: 'in_progress',
        rawInput,
        _meta: { claudeCode: { toolName } },
    })
}

function posthogCall(timestamp: string, id: string, tool: string, args: object, context: string): StoredLogEntry {
    return update(timestamp, {
        sessionUpdate: 'tool_call',
        toolCallId: id,
        title: 'exec',
        kind: 'other',
        status: 'in_progress',
        rawInput: { command: `call ${tool} ${JSON.stringify(args)}`, context },
        _meta: { claudeCode: { toolName: 'mcp__posthog__exec' } },
    })
}

function toolResult(timestamp: string, id: string, status: string, text: string): StoredLogEntry {
    return update(timestamp, {
        sessionUpdate: 'tool_call_update',
        toolCallId: id,
        status,
        content: [{ type: 'content', content: { type: 'text', text } }],
    })
}

const COMPLETED_TURN: StoredLogEntry[] = [
    update('2024-03-11T14:02:10Z', {
        sessionUpdate: 'user_message_chunk',
        content: { type: 'text', text: 'Why did signups drop last week? Check the funnel and the recent deploys.' },
    }),
    update('2024-03-11T14:02:12Z', {
        sessionUpdate: 'agent_thought_chunk',
        content: { type: 'text', text: 'Start with the signup funnel, then compare it with the deploy log.' },
    }),
    toolCall(
        '2024-03-11T14:02:13Z',
        'read-funnel',
        'Read',
        'Read signup_funnel.sql',
        { file_path: 'queries/signup_funnel.sql' },
        'read'
    ),
    toolResult('2024-03-11T14:02:14Z', 'read-funnel', 'completed', 'SELECT step, count() FROM funnel GROUP BY step'),
    toolCall('2024-03-11T14:02:15Z', 'grep-deploys', 'Grep', 'Search deploy log', { pattern: 'signup' }, 'search'),
    toolResult('2024-03-11T14:02:16Z', 'grep-deploys', 'completed', 'deploys.log:42: signup form validation changed'),
    toolCall(
        '2024-03-11T14:02:17Z',
        'run-tests',
        'Bash',
        'Run signup tests',
        { command: 'pnpm test signup' },
        'execute'
    ),
    toolResult('2024-03-11T14:02:19Z', 'run-tests', 'failed', '1 test failed: email validation rejects plus signs'),
    update('2024-03-11T14:02:21Z', {
        sessionUpdate: 'agent_message_chunk',
        messageId: 'answer',
        content: {
            type: 'text',
            text: 'Signups dropped **18%** after the deploy on Tuesday.\n\nThe new email validation rejects addresses with a `+`, so those users never reach the second funnel step.',
        },
    }),
    notification('2024-03-11T14:02:22Z', '_posthog/turn_complete', {}),
]

const STREAMING_TURN: StoredLogEntry[] = [
    ...COMPLETED_TURN,
    update('2024-03-11T14:03:00Z', {
        sessionUpdate: 'user_message_chunk',
        content: { type: 'text', text: 'Can you fix the validation?' },
    }),
    toolCall(
        '2024-03-11T14:03:02Z',
        'read-validator',
        'Read',
        'Read emailValidator.ts',
        { file_path: 'src/emailValidator.ts' },
        'read'
    ),
]

const LONG_RUN_TURN: StoredLogEntry[] = [
    update('2024-03-11T14:10:00Z', {
        sessionUpdate: 'user_message_chunk',
        content: { type: 'text', text: 'Why did the weekly digest email go out twice on Monday?' },
    }),
    notification('2024-03-11T14:10:02Z', '_posthog/status', { status: 'setup_hooks' }),
    notification('2024-03-11T14:10:09Z', '_posthog/status', { status: 'sdk_initialization' }),
    update('2024-03-11T14:10:12Z', {
        sessionUpdate: 'agent_message_chunk',
        messageId: 'plan',
        content: { type: 'text', text: "I'll check Monday's digest send events first, then the scheduler." },
    }),
    posthogCall(
        '2024-03-11T14:10:13Z',
        'sql-sends',
        'execute-sql',
        { query: "SELECT project_id, count() FROM events WHERE event = 'digest sent' GROUP BY project_id" },
        'Count digest sends per project on Monday'
    ),
    toolResult('2024-03-11T14:10:15Z', 'sql-sends', 'completed', 'project_id | count\n101 | 2\n102 | 1'),
    posthogCall(
        '2024-03-11T14:10:16Z',
        'sql-doubles',
        'execute-sql',
        { query: "SELECT project_id, timestamp FROM events WHERE event = 'digest sent' ORDER BY timestamp" },
        'List the projects that got two sends'
    ),
    toolResult('2024-03-11T14:10:18Z', 'sql-doubles', 'completed', '101 | 09:00:02\n101 | 09:15:04'),
    posthogCall(
        '2024-03-11T14:10:19Z',
        'sql-scheduler',
        'execute-sql',
        { query: "SELECT timestamp FROM events WHERE event = 'digest retry scheduled'" },
        'Compare send times with the retry job'
    ),
    toolResult('2024-03-11T14:10:21Z', 'sql-scheduler', 'completed', '09:15:00'),
    update('2024-03-11T14:10:22Z', {
        sessionUpdate: 'agent_thought_chunk',
        content: { type: 'text', text: 'The second send lines up with the retry job. Check the scheduler code.' },
    }),
    toolCall(
        '2024-03-11T14:10:23Z',
        'git-log',
        'Bash',
        'git log --oneline -5 -- digest/scheduler.py',
        { command: 'git log --oneline -5 -- digest/scheduler.py' },
        'execute'
    ),
    toolResult('2024-03-11T14:10:24Z', 'git-log', 'completed', 'a1b2c3d Retry digests that time out'),
    toolCall(
        '2024-03-11T14:10:25Z',
        'read-scheduler',
        'Read',
        'Read digest/scheduler.py',
        { file_path: 'digest/scheduler.py' },
        'read'
    ),
    toolResult('2024-03-11T14:10:26Z', 'read-scheduler', 'completed', 'def retry_digest(project):\n    send(project)'),
    toolCall(
        '2024-03-11T14:10:27Z',
        'grep-retry',
        'Grep',
        'Search for retry_digest',
        { pattern: 'retry_digest' },
        'search'
    ),
    toolResult('2024-03-11T14:10:28Z', 'grep-retry', 'completed', 'digest/scheduler.py:40\ndigest/jobs.py:12'),
    toolCall(
        '2024-03-11T14:10:29Z',
        'run-scheduler-tests',
        'Bash',
        'pytest digest/tests/test_scheduler.py',
        { command: 'pytest digest/tests/test_scheduler.py' },
        'execute'
    ),
    toolResult('2024-03-11T14:10:33Z', 'run-scheduler-tests', 'failed', '1 failed: retry ignores the sent marker'),
    update('2024-03-11T14:10:35Z', {
        sessionUpdate: 'agent_message_chunk',
        messageId: 'finding',
        content: {
            type: 'text',
            text: 'The retry job sends the digest again when the first send is slow, because it never checks whether that send finished.',
        },
    }),
    notification('2024-03-11T14:10:36Z', '_posthog/compact_boundary', { trigger: 'auto', preTokens: 152000 }),
    notification('2024-03-11T14:10:37Z', '_posthog/turn_complete', {}),
]

function renderTrailer(trailer: TurnTrailer): JSX.Element {
    return (
        <TurnFeedbackActions
            sessionId="example-task"
            turnIndex={trailer.turnIndex}
            run={{ taskId: 'example-task' }}
            turnText={trailer.turnText}
            timestamp={trailer.timestamp}
        />
    )
}

interface FixtureProps {
    streamKey: string
    entries: StoredLogEntry[]
    skin: 'quill' | 'lemon' | 'both'
}

function Fixture({ streamKey, entries, skin }: FixtureProps): JSX.Element {
    useEffect(() => {
        const logic = runStreamLogic({ streamKey })
        const unmount = logic.mount()
        // Strict mode reruns this effect; ingest once.
        if (logic.values.threadItems.length === 0) {
            for (const entry of entries) {
                logic.actions.ingestAcpFrame(entry, 'replay')
            }
        }
        return unmount
    }, [streamKey, entries])
    return (
        <BindLogic logic={runStreamLogic} props={{ streamKey }}>
            <div className="flex gap-4">
                {skin !== 'lemon' && (
                    <div className="h-160 w-180 max-w-full rounded border p-4">
                        <ThreadView skin="quill" renderTurnTrailer={renderTrailer} />
                    </div>
                )}
                {skin !== 'quill' && (
                    <div className="h-160 w-180 max-w-full rounded border p-4">
                        <ThreadView renderTurnTrailer={renderTrailer} />
                    </div>
                )}
            </div>
        </BindLogic>
    )
}

const meta: Meta<FixtureProps> = {
    title: 'Products/PostHog AI/ThreadView/Quill',
    parameters: { mockDate: '2024-03-11T14:05:00Z' },
    args: { streamKey: 'example-quill-completed', entries: COMPLETED_TURN, skin: 'quill' },
    render: (props) => <Fixture {...props} />,
}
export default meta

type Story = StoryObj<typeof meta>

export const CompletedTurn: Story = {}
export const StreamingTurn: Story = {
    args: { streamKey: 'example-quill-streaming', entries: STREAMING_TURN },
    // A turn that is still running shows its progress spinner for as long as the story is open.
    parameters: { testOptions: { waitForLoadersToDisappear: false } },
}
export const LongRun: Story = {
    args: { streamKey: 'example-quill-long-run', entries: LONG_RUN_TURN },
    parameters: { mockDate: '2024-03-11T14:15:00Z' },
}
export const ComparedWithLemon: Story = {
    args: { streamKey: 'example-quill-compare', skin: 'both' },
    parameters: { testOptions: { skip: true } },
}
