import type { Meta, StoryObj } from '@storybook/react'
import type { ReactElement } from 'react'

import { MarkdownMessage } from './MarkdownMessage'

const meta: Meta<typeof MarkdownMessage> = {
    title: 'Products/PostHog AI/MarkdownMessage',
    component: MarkdownMessage,
    args: {
        id: 'example-desktop-message',
        content: [
            'Summary before the embedded objects.',
            '<insight id="example">Signup funnel</insight>',
            '<hogql display="block" title="Daily signups">SELECT 1</hogql>',
            '<replay id="example-recording" display="block"/>',
            '<report id="example-report">Report title</report>',
            'Summary after the embedded objects.',
            '```text\nKeep this code.\n<insight id="code-example">Code reference</insight>\n```',
        ].join('\n\n'),
    },
}
export default meta

type Story = StoryObj<typeof MarkdownMessage>

export const DesktopConversation: Story = {}

export const Narrow: Story = {
    decorators: [
        (Story): ReactElement => (
            <div className="w-[520px]">
                <Story />
            </div>
        ),
    ],
}
