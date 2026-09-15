import { flattenMarkdownToLine } from './markdown'

describe('flattenMarkdownToLine', () => {
    it.each<{ name: string; text: string; expected: string }>([
        { name: 'strips bold', text: 'The user **abandoned** checkout.', expected: 'The user abandoned checkout.' },
        { name: 'strips italics', text: 'The user *hesitated* here.', expected: 'The user hesitated here.' },
        { name: 'strips inline code', text: 'Clicked `Submit`.', expected: 'Clicked Submit.' },
        {
            name: 'turns a heading and its body into one sentence pair',
            text: '## Checkout blocked\nThe form rejected it.',
            expected: 'Checkout blocked. The form rejected it.',
        },
        {
            name: 'leaves a tab-indented hash as text',
            text: '\t# literal hash',
            expected: '# literal hash',
        },
        {
            name: 'reads a bullet list as prose',
            text: '- Reached payment\n- Card rejected',
            expected: 'Reached payment. Card rejected',
        },
        {
            name: 'does not double up punctuation the model already wrote',
            text: 'Two problems:\n- one\n- two',
            expected: 'Two problems: one. two',
        },
        {
            name: 'strips a link to its label',
            text: 'Landed on [pricing](https://e.com).',
            expected: 'Landed on pricing.',
        },
        {
            name: 'strips a reference link to its label and drops the definition line',
            text: 'Landed on [pricing][p].\n\n[p]: https://e.example/pricing',
            expected: 'Landed on pricing.',
        },
        {
            name: 'leaves bracketed prose alone',
            text: 'The user clicked [Save].',
            expected: 'The user clicked [Save].',
        },
        {
            name: 'keeps a sentence that merely opens like a reference definition',
            text: '[Save]: clicked twice before it took',
            expected: '[Save]: clicked twice before it took',
        },
        { name: 'leaves snake_case alone', text: 'Read team_id_override.', expected: 'Read team_id_override.' },
        { name: 'leaves multiplication alone', text: 'Retried 3 * 4 times.', expected: 'Retried 3 * 4 times.' },
        { name: 'renders plain prose unchanged', text: 'The user gave up.', expected: 'The user gave up.' },
    ])('$name', ({ text, expected }) => {
        expect(flattenMarkdownToLine(text)).toBe(expected)
    })

    it('never emits a line break, so a one-line surface stays one line', () => {
        expect(flattenMarkdownToLine('# Title\n\n- one\n- two\n\nEnd.')).not.toContain('\n')
    })
})
