import { collapseUnchangedLines, diffLines } from './diffLines'

const page = (lines: string[]): string => lines.join('\n')
const longIntro = Array.from({ length: 20 }, (_, index) => `Intro line ${index + 1}`)

describe('diffLines', () => {
    test.each([
        {
            name: 'an inserted section marks only the new lines',
            before: page(['# Title', 'Intro', '## Setup', 'Install it']),
            after: page(['# Title', 'Intro', '## Pitfalls', 'Reuse one client', '## Setup', 'Install it']),
            expected: [
                ['same', '# Title'],
                ['same', 'Intro'],
                ['added', '## Pitfalls'],
                ['added', 'Reuse one client'],
                ['same', '## Setup'],
                ['same', 'Install it'],
            ],
        },
        {
            name: 'an edited line shows as removed then added',
            before: page(['# Title', 'Node 18 or newer', 'Done']),
            after: page(['# Title', 'Node 20 or newer', 'Done']),
            expected: [
                ['same', '# Title'],
                ['removed', 'Node 18 or newer'],
                ['added', 'Node 20 or newer'],
                ['same', 'Done'],
            ],
        },
        {
            name: 'removing a markdown hard break is a change',
            before: page(['# Title', 'Line one  ', 'Line two']),
            after: page(['# Title', 'Line one', 'Line two']),
            expected: [
                ['same', '# Title'],
                ['removed', 'Line one  '],
                ['added', 'Line one'],
                ['same', 'Line two'],
            ],
        },
    ])('$name', ({ before, after, expected }) => {
        expect(diffLines(before, after).map(({ kind, text }) => [kind, text])).toEqual(expected)
    })

    it('collapses long unchanged runs around a change', () => {
        const before = page([...longIntro, 'Old ending'])
        const after = page([...longIntro, 'New ending'])

        const segments = collapseUnchangedLines(diffLines(before, after))

        expect(segments.map((segment) => (segment.kind === 'collapsed' ? segment.count : segment.line.text))).toEqual([
            18,
            'Intro line 19',
            'Intro line 20',
            'Old ending',
            'New ending',
        ])
    })
})
