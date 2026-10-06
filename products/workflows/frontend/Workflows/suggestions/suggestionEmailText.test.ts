import {
    changedWordCounts,
    condenseEmailTextDiff,
    diffEmailText,
    emailVisibleText,
    isSummaryShortened,
} from './suggestionEmailText'

const email = (cta: string): string =>
    `<!DOCTYPE html><html><head><title>Onboarding</title><style>.button { color: red; }</style></head>
    <body><!--[if mso]><table><![endif]--><p>Hi there,</p><p>You have done the setup. Here is one more thing to try
    before the week is out, and it only takes a minute.</p><a class="button" href="https://example.com">${cta}</a>
    <p>Thanks, the team</p></body></html>`

describe('suggestionEmailText', () => {
    it('reads only the text a person sees', () => {
        expect(emailVisibleText(email('Run the play'))).toEqual(
            'Hi there, You have done the setup. Here is one more thing to try before the week is out, and it only takes a minute. Run the play Thanks, the team'
        )
    })

    it.each([
        [
            'a reworded button',
            'Run the play',
            'Create your first workflow',
            [
                { kind: 'gap' },
                { kind: 'same', text: 'it only takes a minute.' },
                { kind: 'removed', text: 'Run the play' },
                { kind: 'added', text: 'Create your first workflow' },
                { kind: 'same', text: 'Thanks, the team' },
            ],
        ],
        [
            'one word swapped inside a phrase',
            'Run the play',
            'Run the workflow',
            [
                { kind: 'gap' },
                { kind: 'same', text: 'takes a minute. Run the' },
                { kind: 'removed', text: 'play' },
                { kind: 'added', text: 'workflow' },
                { kind: 'same', text: 'Thanks, the team' },
            ],
        ],
    ])('summarizes %s as only the words that changed', (_name, before, after, expected) => {
        const parts = diffEmailText(emailVisibleText(email(before)), emailVisibleText(email(after)))

        expect(condenseEmailTextDiff(parts)).toEqual(expected)
    })

    it('shows a rewritten passage as one removed and one added passage', () => {
        const before =
            'Hi Sam, You finished setup. Here is one more thing to try before the week is out. Run the play Thanks, the team'
        const after = 'Hi Sam, Teams that launch a workflow in week one keep using it. Build it now Thanks, the team'

        expect(diffEmailText(before, after)).toEqual([
            { kind: 'same', text: 'Hi Sam,' },
            {
                kind: 'removed',
                text: 'You finished setup. Here is one more thing to try before the week is out. Run the play',
            },
            { kind: 'added', text: 'Teams that launch a workflow in week one keep using it. Build it now' },
            { kind: 'same', text: 'Thanks, the team' },
        ])
    })

    it('cuts a long rewrite short on the card and counts what it changes', () => {
        const before = Array.from({ length: 200 }, (_, i) => `old${i}`).join(' ')
        const after = Array.from({ length: 150 }, (_, i) => `new${i}`).join(' ')
        const parts = diffEmailText(before, after)

        const condensed = condenseEmailTextDiff(parts)

        expect(condensed.map((part) => (part.kind === 'gap' ? 0 : part.text.split(' ').length))).toEqual([31, 31])
        expect(changedWordCounts(parts)).toEqual({ removed: 200, added: 150 })
        expect(isSummaryShortened(parts)).toBe(true)
    })

    it('shows only the first few of many scattered edits', () => {
        const sentences = Array.from(
            { length: 10 },
            (_, i) => `Paragraph ${i} keeps its first words and ends with old${i}.`
        )
        const edited = sentences.map((sentence, i) => sentence.replace(`old${i}`, `new${i}`))
        const parts = diffEmailText(sentences.join(' '), edited.join(' '))

        const condensed = condenseEmailTextDiff(parts)

        expect(condensed.filter((part) => part.kind === 'added').map((part) => 'text' in part && part.text)).toEqual([
            'new0.',
            'new1.',
            'new2.',
            'new3.',
            'new4.',
            'new5.',
        ])
        expect(condensed[condensed.length - 1]).toEqual({ kind: 'gap' })
        expect(isSummaryShortened(parts)).toBe(true)
    })

    it('reports no text change when only markup differs', () => {
        const restyled = email('Run the play').replace('class="button"', 'class="button" style="padding: 12px"')

        const parts = diffEmailText(emailVisibleText(email('Run the play')), emailVisibleText(restyled))

        expect(parts.every((part) => part.kind === 'same')).toBe(true)
    })
})
