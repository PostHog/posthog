import type { Meta, StoryObj } from '@storybook/react'

import { expect } from 'storybook/test'

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

/**
 * Reasoning is model output derived from a page a stranger wrote, so a link in it is a phishing vector.
 * Every markdown form that reaches a link is here, including the reference forms that a regex over the
 * source misses. The assertion runs in a real browser under `test-storybook`, which is the only place
 * this can be checked: `react-markdown` is ESM-only and mocked out under Jest.
 */
export const HostileLinks: Story = {
    args: {
        text: [
            'Inline [click here](https://evil.example/phish).',
            'Reference [click here][ref] and collapsed [click here][].',
            'Image by reference ![a banner][img].',
            'Autolink <https://evil.example/auto> and bare https://evil.example/bare.',
            'Scheme [click here](javascript:alert(1)).',
            '',
            '[ref]: https://evil.example/phish',
            '[img]: https://evil.example/banner.png',
        ].join('\n'),
        segments: [],
    },
    play: async ({ canvasElement }) => {
        await expect(canvasElement.querySelectorAll('a')).toHaveLength(0)
        // The labels survive as plain text, so the reader still sees what the model wrote.
        await expect(canvasElement.textContent).toContain('click here')
    },
}
