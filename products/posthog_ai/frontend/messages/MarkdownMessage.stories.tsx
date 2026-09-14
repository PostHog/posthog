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

/**
 * A PostHog-hosted image must draw as a link too, because a PostHog host reads request data from the query
 * string. Plain `disableImages` renders this case as an <img>, so the story catches a drop back to it.
 */
export const PostHogHostedImage: Story = {
    args: {
        id: 'posthog-hosted-image',
        content:
            'Here is the chart you asked for:\n\n![Weekly signups](https://us.i.posthog.com/static/weekly-signups.png)',
    },
}
