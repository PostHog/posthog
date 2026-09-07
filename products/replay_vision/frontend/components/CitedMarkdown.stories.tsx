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

export const PlainProse: Story = {
    args: {
        text: 'The user opened the pricing page, scrolled to the comparison table, and left without starting a trial.',
        segments: [],
    },
}

/** Only `test-storybook` checks this: `react-markdown` is ESM-only and mocked out under Jest. */
export const HostileLinks: Story = {
    args: {
        text: [
            'Inline [click here](https://evil.example/phish).',
            'Reference [click here][ref] and collapsed [click here][].',
            'Image by reference ![a banner][img].',
            'Same-origin image ![a probe](/api/projects/@current/session_recordings) fires a credentialed GET.',
            'Autolink <https://evil.example/auto> and bare https://evil.example/bare.',
            'Scheme [click here](javascript:alert(1)).',
            'Mentions @member:1 and @role:1 name whoever holds those ids.',
            '',
            '[ref]: https://evil.example/phish',
            '[img]: https://evil.example/banner.png',
        ].join('\n'),
        segments: [],
    },
    // `storybook/test` belongs to the frontend workspace and does not resolve from `products/`.
    play: ({ canvasElement }) => {
        const check = (ok: boolean, failure: string): void => {
            if (!ok) {
                throw new Error(failure)
            }
        }
        const text = canvasElement.textContent ?? ''
        check(canvasElement.querySelectorAll('a').length === 0, 'a clickable link reached the reader')
        check(canvasElement.querySelectorAll('img').length === 0, 'an image fired a request')
        check(text.includes('click here'), 'a link label was dropped instead of kept as text')
        check(text.includes('@member:1 and @role:1'), 'a mention resolved into a chip')
    },
}
