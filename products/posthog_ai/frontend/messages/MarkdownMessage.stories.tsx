import type { Meta, StoryObj } from '@storybook/react'

import { MarkdownMessage } from './MarkdownMessage'

const meta: Meta<typeof MarkdownMessage> = {
    title: 'Products/PostHog AI/MarkdownMessage',
    component: MarkdownMessage,
    args: {
        id: 'example-desktop-message',
        content: [
            'The <insight id="example">signup funnel</insight> changed after <flag id="1">new signup</flag>.',
            '<hogql display="block" title="Daily signups">SELECT 1</hogql>',
            'Read <report id="example-report">the report</report> for details.',
            'Example syntax: `<insight id="example">Signup funnel</insight>`.',
        ].join('\n\n'),
    },
}
export default meta

type Story = StoryObj<typeof MarkdownMessage>

export const DesktopConversation: Story = {}

export const Narrow: Story = {
    decorators: [
        (Story) => (
            <div className="w-[520px]">
                <Story />
            </div>
        ),
    ],
}
