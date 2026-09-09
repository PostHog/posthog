import type { Meta, StoryObj } from '@storybook/react'

import { MarkdownMessage } from './MarkdownMessage'

const meta: Meta<typeof MarkdownMessage> = {
    title: 'Products/PostHog AI/MarkdownMessage',
    component: MarkdownMessage,
}
export default meta

type Story = StoryObj<typeof MarkdownMessage>

/**
 * An image off PostHog must draw as a click-to-open link, never as an <img>. Storybook is the only place
 * this is visible: Jest replaces `react-markdown` with a passthrough mock that renders no image at all.
 */
export const UntrustedImage: Story = {
    args: {
        id: 'untrusted-image',
        content:
            'Here is the chart you asked for:\n\n![Weekly signups](https://example.com/pixel.png?leak=conversation)',
    },
}
