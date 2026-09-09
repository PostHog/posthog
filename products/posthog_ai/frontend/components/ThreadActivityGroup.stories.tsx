import type { Meta, StoryObj } from '@storybook/react'

import type { ToolInvocation } from '../types/streamTypes'
import type { ThreadActivityGroup as ActivityGroup } from '../utils/groupThreadActivity'
import { ThreadActivityGroup } from './ThreadActivityGroup'
import { ThreadRow } from './ThreadRow'

const tools = new Map<string, ToolInvocation>(
    Array.from({ length: 300 }, (_, index) => {
        const id = `example-call-${index}`
        return [
            id,
            {
                toolCallId: id,
                rawServerName: 'example',
                rawToolName: 'read_report',
                title: `Read example report ${index + 1}`,
                input: { report: index + 1 },
                status: index === 148 ? 'failed' : 'completed',
                error: index === 148 ? { message: 'Example report is unavailable' } : undefined,
                contentBlocks: [
                    {
                        type: 'text',
                        text: Array.from({ length: 30 }, (_, line) => `Example result ${line + 1}`).join('\n'),
                    },
                ],
            },
        ]
    })
)
const group: ActivityGroup = {
    id: 'example-activity',
    type: 'activity_group',
    startedAt: 1000,
    endedAt: 65000,
    items: [...tools.keys()].map((id) => ({ id, type: 'tool_invocation', toolCallId: id })),
}

const meta: Meta<typeof ThreadActivityGroup> = {
    title: 'Products/PostHog AI/ThreadActivityGroup',
    component: ThreadActivityGroup,
    args: {
        group,
        toolInvocations: tools,
        active: false,
        cancelled: false,
        renderItem: (item) => (
            <ThreadRow
                item={item}
                isLast={false}
                isThinking={false}
                toolInvocations={tools}
                turnComplete
                turnCancelled={false}
            />
        ),
    },
    decorators: [
        (Story, { parameters }) => (
            <div className={parameters.narrow ? 'w-96 p-4' : 'w-180 p-4'}>
                <Story />
            </div>
        ),
    ],
}
export default meta
type Story = StoryObj<typeof ThreadActivityGroup>

export const LongHistory: Story = {}
export const ShortHistory: Story = { args: { group: { ...group, items: group.items.slice(0, 4) } } }
export const UnknownTiming: Story = { args: { group: { ...group, startedAt: undefined } } }
export const Narrow: Story = { parameters: { narrow: true } }
export const ThoughtOnly: Story = {
    args: {
        group: {
            id: 'example-thought',
            type: 'activity_group',
            items: [{ id: 'thought', type: 'assistant_thought', text: 'Compare the available approaches.' }],
        },
    },
}
