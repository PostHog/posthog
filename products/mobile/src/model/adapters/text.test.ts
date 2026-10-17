import { displayTitle, headlineFor, plainText, splitLeadingNumber } from './text'

describe('report text', () => {
    test.each([
        ['3,721 errors since 9 AM', { number: '3,721', rest: 'errors since 9 AM' }],
        ['+2.3s p95 load time on reports', { number: '+2.3s', rest: 'p95 load time on reports' }],
        ['0 of 860 digests sent on Monday', { number: '0 of 860', rest: 'digests sent on Monday' }],
        ['$184k in renewals at risk', { number: '$184k', rest: 'in renewals at risk' }],
        ['12% fewer signups', { number: '12%', rest: 'fewer signups' }],
        ['5xx errors on the export endpoint', { rest: '5xx errors on the export endpoint' }],
        ['v1.2 broke the legend', { rest: 'v1.2 broke the legend' }],
        ['Shared report links returned 404', { rest: 'Shared report links returned 404' }],
    ])('splits %j', (input, expected) => {
        expect(splitLeadingNumber(input)).toEqual(expected)
    })

    test.each([
        ['title with a number wins', '3 support tickets about exports', '612 users hit it.', '3'],
        ['lead number when the title has none', 'Exports fail for guests', '**612 users** hit it. More later.', '612'],
        ['no number anywhere', 'Exports fail for guests', 'Guests cannot export.', undefined],
    ])('%s', (_name, title, lead, number) => {
        expect(headlineFor(title, lead).number).toBe(number)
    })

    test.each([
        ['fix(exports): Guests cannot export', 'Guests cannot export'],
        ['feat!: Shared links for guests', 'Shared links for guests'],
        ['Error: export timed out', 'export timed out'],
        ['Exports fail for guests', 'Exports fail for guests'],
        ['fix(exports):', 'fix(exports):'],
        ['  ', 'Untitled report'],
        [null, 'Untitled report'],
    ])('displays %j without its commit prefix', (input, expected) => {
        expect(displayTitle(input, 'Untitled report')).toBe(expected)
    })

    test('turns markdown into one plain line', () => {
        expect(plainText('**Bold** and [a link](https://example.com)\n\nSee [chart](chart:abc) `code`.')).toBe(
            'Bold and a link See code.'
        )
    })
})
