import type { Meta, StoryObj } from '@storybook/react'
import { BindLogic } from 'kea'
import { useEffect } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'

import { mswDecorator } from '~/mocks/browser'

import { runStreamLogic } from '../../../logics/runStreamLogic'
import { RunChatActionComposerProvider } from '../../RunChatActionComposerProvider'
import { ThreadView } from '../../ThreadView'

const STREAM_KEY = 'suggest-actions-story'

const SUGGESTED = {
    actions: [
        {
            key: 'workflows-create.test-send',
            label: 'Fire a real send to your address',
            kind: 'insert',
            message: 'Send a real test of this workflow to ',
        },
        { key: 'workflows-create.enable', label: 'Enable the workflow', kind: 'run', message: 'Enable workflow wf_1.' },
    ],
    errors: [],
}

function frame(update: Record<string, unknown>): Parameters<typeof runStreamLogic.actions.ingestAcpFrame>[0] {
    return {
        type: 'notification',
        notification: { method: 'session/update', params: { update } },
    } as Parameters<typeof runStreamLogic.actions.ingestAcpFrame>[0]
}

function SuggestActionsThread({
    narrow = false,
    turnComplete = true,
}: {
    narrow?: boolean
    turnComplete?: boolean
}): JSX.Element {
    useEffect(() => {
        const logic = runStreamLogic({ streamKey: STREAM_KEY })
        const unmount = logic.mount()
        logic.actions.ingestAcpFrame(
            frame({
                sessionUpdate: 'agent_message_chunk',
                content: {
                    type: 'text',
                    text: 'The workflow is saved as a draft. It does not run until you enable it.',
                },
            }),
            'replay'
        )
        logic.actions.ingestAcpFrame(
            frame({
                sessionUpdate: 'tool_call',
                toolCallId: 'suggest-1',
                title: 'Suggest actions',
                serverName: 'posthog',
                toolName: 'exec',
                status: 'in_progress',
                rawInput: {
                    command:
                        'call suggest-actions {"actions":[{"key":"workflows-create.test-send"},{"key":"workflows-create.enable","args":{"id":"wf_1"}}]}',
                },
                _meta: { claudeCode: { toolName: 'mcp__posthog__exec' } },
            }),
            'replay'
        )
        logic.actions.ingestAcpFrame(
            frame({
                sessionUpdate: 'tool_call_update',
                toolCallId: 'suggest-1',
                status: 'completed',
                rawOutput: { content: [{ type: 'text', text: 'ok' }], structuredContent: SUGGESTED },
            }),
            'replay'
        )
        if (turnComplete) {
            logic.actions.markTurnComplete(true)
        }
        return unmount
    }, [turnComplete])
    return (
        <div className={`${narrow ? 'w-130' : 'w-180'} max-w-full h-100 border rounded`}>
            <RunChatActionComposerProvider logicProps={{ taskId: 'story-task', runId: 'story-run' }}>
                <BindLogic logic={runStreamLogic} props={{ streamKey: STREAM_KEY }}>
                    <ThreadView />
                </BindLogic>
            </RunChatActionComposerProvider>
        </div>
    )
}

const meta: Meta<typeof SuggestActionsThread> = {
    title: 'Products/PostHog AI/Suggested actions',
    component: SuggestActionsThread,
    parameters: {
        featureFlags: [FEATURE_FLAGS.POSTHOG_AI_CHAT_ACTIONS],
        testOptions: { waitForLoadersToDisappear: false },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team/tasks/@me/config/': { ai_run_preferences: {}, resolved_ai_run_defaults: {} },
                '/api/projects/:team/tasks/repositories/': { repositories: [] },
            },
        }),
    ],
}
export default meta
type Story = StoryObj<typeof SuggestActionsThread>

export const TurnComplete: Story = {}
export const TurnRunning: Story = { args: { turnComplete: false } }
export const Narrow: Story = { args: { narrow: true } }
