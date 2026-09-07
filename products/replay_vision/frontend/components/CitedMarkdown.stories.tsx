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

/**
 * Reasoning is model output derived from a page a stranger wrote, so a link in it is a phishing vector, an
 * image is a request it gets to aim from the reader's browser, and a mention is a colleague it gets to
 * name. Every markdown form that reaches one of those is here, including the reference forms that a regex
 * over the source misses and the same-origin image that the ordinary `disableImages` lets through. The
 * assertion runs in a real browser under `test-storybook`, which is the only place this can be checked:
 * `react-markdown` is ESM-only and mocked out under Jest.
 */
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
    // `storybook/test` is a dependency of the frontend workspace, which a file under `products/` cannot
    // resolve, so the assertions are plain throws. A play function that throws is a failed story.
    play: ({ canvasElement }) => {
        const check = (ok: boolean, failure: string): void => {
            if (!ok) {
                throw new Error(failure)
            }
        }
        const text = canvasElement.textContent ?? ''
        check(canvasElement.querySelectorAll('a').length === 0, 'a clickable link reached the reader')
        check(canvasElement.querySelectorAll('img').length === 0, 'an image fired a request')
        // The labels and the raw mention syntax survive as plain text, so the reader still sees what the
        // model wrote. A chip would show the member's name in its place.
        check(text.includes('click here'), 'a link label was dropped instead of kept as text')
        check(text.includes('@member:1 and @role:1'), 'a mention resolved into a chip')
    },
}
