import type { Meta, StoryObj } from '@storybook/react'

import { CitedMarkdown } from './CitedMarkdown'

const meta: Meta<typeof CitedMarkdown> = {
    title: 'Replay Vision/Cited markdown',
    component: CitedMarkdown,
    args: { onSeek: () => {} },
}
export default meta

type Story = StoryObj<typeof CitedMarkdown>

export const Structured: Story = {
    args: {
        text: '**Checkout blocked at payment**\n\nThe user reached the payment step and never got past it:\n\n- The card form rejected the submission twice with no visible error\n- A third attempt on a different card behaved the same way\n\nThe session ends on the payment page.',
        segments: [
            { kind: 'text', value: '**Checkout blocked at payment**\n\nThe user reached the payment step' },
            { kind: 'chip', timestamp_ms: 92000 },
            {
                kind: 'text',
                value: ' and never got past it:\n\n- The card form rejected the submission twice with no visible error\n- A third attempt on a different card behaved the same way',
            },
            { kind: 'chip', timestamp_ms: 241000 },
            { kind: 'text', value: '\n\nThe session ends on the payment page.' },
        ],
    },
}

/** Reasoning written before the prompt asked for structure still has to render as the paragraph it is. */
export const PlainProse: Story = {
    args: {
        text: 'The user opened the pricing page, scrolled to the comparison table, and left without starting a trial.',
        segments: [],
    },
}
