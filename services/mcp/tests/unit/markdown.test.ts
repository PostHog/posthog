import { describe, expect, it } from 'vitest'

import { parseInline, parseMarkdown } from '@/ui-apps/lib/markdown-parser'

describe('markdown parser', () => {
    it.each([
        [
            'an unsafe link as plain text',
            '[click me](data:text/html;base64,PHNjcmlwdD4=)',
            [{ kind: 'text', text: 'click me' }],
        ],
        [
            'a web link as a link',
            '[the funnel](https://example.com/insights/1)',
            [{ kind: 'link', url: 'https://example.com/insights/1', children: [{ kind: 'text', text: 'the funnel' }] }],
        ],
        [
            'event names without emphasis',
            'Count purchase_completed and order_id events.',
            [{ kind: 'text', text: 'Count purchase_completed and order_id events.' }],
        ],
        [
            'bold and code',
            '**Lift:** `6.8%`',
            [
                { kind: 'strong', children: [{ kind: 'text', text: 'Lift:' }] },
                { kind: 'text', text: ' ' },
                { kind: 'code', text: '6.8%' },
            ],
        ],
    ])('reads %s', (_label, source, expected) => {
        expect(parseInline(source)).toEqual(expected)
    })

    it('splits an answer into paragraph, table and list blocks', () => {
        const blocks = parseMarkdown('Variant B wins.\n\n| Variant | Rate |\n|---|---|\n| B | 6.8% |\n\n- one\n- two')

        expect(blocks).toEqual([
            { kind: 'paragraph', text: 'Variant B wins.' },
            { kind: 'table', header: ['Variant', 'Rate'], rows: [['B', '6.8%']] },
            { kind: 'list', ordered: false, items: ['one', 'two'] },
        ])
    })
})
