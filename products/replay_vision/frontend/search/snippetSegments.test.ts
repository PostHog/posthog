import { snippetSegments } from './snippetSegments'

describe('snippetSegments', () => {
    it.each([
        [
            'bolds whole words starting with a query term, case-insensitively',
            'Rage-clicking the submit button',
            'rage click',
            ['Rage', '-', 'clicking', ' the submit button'],
            ['Rage', 'clicking'],
        ],
        [
            'regex special characters in the query are literal, not a crash',
            'checkout (step 2) failed',
            'checkout (step 2)?',
            ['checkout', ' (', 'step', ' 2) failed'],
            ['checkout', 'step'],
        ],
        [
            'stopwords and short words are never bolded',
            'the user gave up after an error',
            'the user who gave up',
            ['the ', 'user', ' ', 'gave', ' up after an error'],
            ['user', 'gave'],
        ],
        [
            'a semantic-only match stays one plain segment',
            'visitor abandoned their cart',
            'frustrated shopper',
            ['visitor abandoned their cart'],
            [],
        ],
        [
            'an accented query word is dropped whole, not fragmented into false matches',
            'usual riots of confusion',
            'usuário confusion',
            ['usual riots of ', 'confusion'],
            ['confusion'],
        ],
    ])('%s', (_name, text, query, expectedTexts, expectedHighlights) => {
        const segments = snippetSegments(text, query)

        expect(segments.map((s) => s.text)).toEqual(expectedTexts)
        expect(segments.filter((s) => s.highlighted).map((s) => s.text)).toEqual(expectedHighlights)
        expect(segments.map((s) => s.text).join('')).toBe(text)
    })

    it('windows a late match into view behind a leading ellipsis', () => {
        const text = `${'lead '.repeat(40)}rage clicking at checkout`

        const segments = snippetSegments(text, 'rage clicking')

        const joined = segments.map((s) => s.text).join('')
        expect(joined.startsWith('… ')).toBe(true)
        expect(joined.endsWith('rage clicking at checkout')).toBe(true)
        expect(joined.length).toBeLessThan(80)
        expect(segments.filter((s) => s.highlighted).map((s) => s.text)).toEqual(['rage', 'clicking'])
    })
})
