import type { Meta, StoryObj } from '@storybook/react'
import { BindLogic } from 'kea'
import { useEffect } from 'react'

import { runStreamLogic } from '../logics/runStreamLogic'
import { ThreadView } from './ThreadView'

const meta: Meta<{ streamKey: string }> = {
    title: 'Products/PostHog AI/ThreadView',
    args: { streamKey: 'synthetic-conversation' },
    render: ({ streamKey }) => {
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
                                toolCallId: 'synthetic-notebook',
                                title: 'Create notebook',
                                serverName: 'posthog',
                                toolName: 'exec',
                                status: 'in_progress',
                                rawInput: { command: 'call notebooks-create {"title":"Synthetic notebook"}' },
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
                                toolCallId: 'synthetic-notebook',
                                status: 'completed',
                                rawOutput: { short_id: 'example-notebook', title: 'Synthetic notebook' },
                            },
                        },
                    },
                },
                'replay'
            )
            return unmount
        }, [streamKey])
        return (
            <div className="w-180 h-96 border rounded">
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
