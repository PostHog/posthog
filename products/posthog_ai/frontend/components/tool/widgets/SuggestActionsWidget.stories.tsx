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
            label: 'Send yourself a test email',
            kind: 'insert',
            message: 'Send a test email of workflow wf_1 to ',
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

/** The turn an "Enable the workflow" click starts when the email sender is not verified yet. */
function ingestEnableBlockedTurn(logic: ReturnType<typeof runStreamLogic>): void {
    logic.actions.ingestAcpFrame(
        {
            type: 'notification',
            notification: { method: '_posthog/turn_complete', params: {} },
        } as Parameters<typeof runStreamLogic.actions.ingestAcpFrame>[0],
        'replay'
    )
    logic.actions.ingestAcpFrame(
        frame({ sessionUpdate: 'user_message_chunk', content: { type: 'text', text: 'Enable workflow wf_1.' } }),
        'replay'
    )
    logic.actions.ingestAcpFrame(
        frame({
            sessionUpdate: 'tool_call',
            toolCallId: 'enable-1',
            title: 'Enable workflow',
            serverName: 'posthog',
            toolName: 'exec',
            status: 'in_progress',
            rawInput: { command: 'call workflows-enable {"id":"wf_1"}' },
            _meta: { claudeCode: { toolName: 'mcp__posthog__exec' } },
        }),
        'replay'
    )
    logic.actions.ingestAcpFrame(
        frame({
            sessionUpdate: 'tool_call_update',
            toolCallId: 'enable-1',
            status: 'failed',
            content: [
                {
                    type: 'content',
                    content: {
                        type: 'text',
                        text: 'The email sender "hello@example.com" is not verified yet. Verify its domain before the workflow can go live.',
                    },
                },
            ],
        }),
        'replay'
    )
    logic.actions.ingestAcpFrame(
        frame({
            sessionUpdate: 'agent_message_chunk',
            messageId: 'enable-blocked',
            content: {
                type: 'text',
                text: 'I could not enable the workflow because its email sender hello@example.com is not verified yet. Verify the domain in Channels, then ask me to enable it again.',
            },
        }),
        'replay'
    )
    logic.actions.markTurnComplete(true)
}

function SuggestActionsThread({
    narrow = false,
    turnComplete = true,
    skin = 'lemon',
    enableBlocked = false,
}: {
    narrow?: boolean
    turnComplete?: boolean
    skin?: 'lemon' | 'quill'
    enableBlocked?: boolean
}): JSX.Element {
    useEffect(() => {
        const logic = runStreamLogic({ streamKey: STREAM_KEY })
        const unmount = logic.mount()
        logic.actions.ingestAcpFrame(
            frame({
                sessionUpdate: 'user_message_chunk',
                content: { type: 'text', text: 'Send a welcome email to new signups.' },
            }),
            'replay'
        )
        logic.actions.ingestAcpFrame(
            frame({
                sessionUpdate: 'agent_message_chunk',
                messageId: 'draft-saved',
                content: {
                    type: 'text',
                    text: 'The workflow is saved as a draft. It does not run until you enable it.',
                },
            }),
            'replay'
        )
        // A tool call right before the card, so a skin that folds tool runs would have to fold the buttons too.
        logic.actions.ingestAcpFrame(
            frame({
                sessionUpdate: 'tool_call',
                toolCallId: 'create-1',
                title: 'Create workflow',
                serverName: 'posthog',
                toolName: 'exec',
                status: 'in_progress',
                rawInput: { command: 'call workflows-create {"name":"Welcome email"}' },
                _meta: { claudeCode: { toolName: 'mcp__posthog__exec' } },
            }),
            'replay'
        )
        logic.actions.ingestAcpFrame(
            frame({
                sessionUpdate: 'tool_call_update',
                toolCallId: 'create-1',
                status: 'completed',
                rawOutput: { content: [{ type: 'text', text: '{"id":"wf_1"}' }] },
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
                        'call suggest-actions {"actions":[{"key":"workflows-create.test-send","args":{"id":"wf_1"}},{"key":"workflows-create.enable","args":{"id":"wf_1"}}]}',
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
        if (enableBlocked) {
            ingestEnableBlockedTurn(logic)
        }
        return unmount
    }, [turnComplete, enableBlocked])
    return (
        <div className={`${narrow ? 'w-130' : 'w-180'} max-w-full h-100 border rounded`}>
            <RunChatActionComposerProvider
                logicProps={{ taskId: 'story-task', runId: 'story-run' }}
                focusComposer={() => {}}
            >
                <BindLogic logic={runStreamLogic} props={{ streamKey: STREAM_KEY }}>
                    <ThreadView skin={skin} />
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
export const QuillSkin: Story = { args: { skin: 'quill' } }
export const EnableBlockedBySender: Story = { args: { enableBlocked: true } }
