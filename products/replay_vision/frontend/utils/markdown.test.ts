import { defangMarkdownLinks, flattenMarkdownToLine } from './markdown'

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

describe('defangMarkdownLinks', () => {
    it.each<{ name: string; text: string; expected: string }>([
        { name: 'keeps an inline link label', text: 'Saw [an offer](https://e.example).', expected: 'Saw an offer.' },
        { name: 'keeps an image alt', text: '![a banner](https://e.example/b.png)', expected: 'a banner' },
        { name: 'inerts an autolink', text: 'Went to <https://e.example>.', expected: 'Went to `https://e.example`.' },
        // remark-gfm turns a bare URL into a link on its own, so leaving one bare is the same exposure.
        { name: 'inerts a bare url', text: 'Went to https://e.example/x.', expected: 'Went to `https://e.example/x`.' },
        { name: 'inerts a www url', text: 'Went to www.e.example.', expected: 'Went to `www.e.example`.' },
        {
            name: 'leaves a url already in a code span alone',
            text: 'At `https://e.example`.',
            expected: 'At `https://e.example`.',
        },
        {
            name: 'leaves ordinary prose alone',
            text: 'The user gave up on /checkout.',
            expected: 'The user gave up on /checkout.',
        },
    ])('$name', ({ text, expected }) => {
        expect(defangMarkdownLinks(text)).toBe(expected)
    })
})
