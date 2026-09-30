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
    rawInput: Record<string, unknown>
): StoredLogEntry {
    return update(timestamp, {
        sessionUpdate: 'tool_call',
        toolCallId: id,
        title,
        status: 'in_progress',
        rawInput,
        _meta: { claudeCode: { toolName } },
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
    toolCall('2024-03-11T14:02:13Z', 'read-funnel', 'Read', 'Read signup_funnel.sql', {
        file_path: 'queries/signup_funnel.sql',
    }),
    toolResult('2024-03-11T14:02:14Z', 'read-funnel', 'completed', 'SELECT step, count() FROM funnel GROUP BY step'),
    toolCall('2024-03-11T14:02:15Z', 'grep-deploys', 'Grep', 'Search deploy log', { pattern: 'signup' }),
    toolResult('2024-03-11T14:02:16Z', 'grep-deploys', 'completed', 'deploys.log:42: signup form validation changed'),
    toolCall('2024-03-11T14:02:17Z', 'run-tests', 'Bash', 'Run signup tests', { command: 'pnpm test signup' }),
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
    toolCall('2024-03-11T14:03:02Z', 'read-validator', 'Read', 'Read emailValidator.ts', {
        file_path: 'src/emailValidator.ts',
    }),
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
export const StreamingTurn: Story = { args: { streamKey: 'example-quill-streaming', entries: STREAMING_TURN } }
export const ComparedWithLemon: Story = {
    args: { streamKey: 'example-quill-compare', skin: 'both' },
    parameters: { testOptions: { skip: true } },
}
