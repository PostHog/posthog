import { parseOptOutRows, remapEntryErrors } from './optOutCsvImport'

describe('optOutCsvImport', () => {
    describe('parseOptOutRows', () => {
        it.each(['identifier', 'email', 'recipient', 'email_address', ' Email '])(
            'accepts "%s" as the recipient column',
            (column) => {
                const parsed = parseOptOutRows([[column], ['ally@example.com']])

                expect(parsed.entries).toEqual([{ identifier: 'ally@example.com', category_key: undefined, row: 2 }])
                expect(parsed.total).toBe(1)
            }
        )

        it('reports a missing recipient column instead of importing nothing silently', () => {
            const parsed = parseOptOutRows([['name'], ['Ally']])

            expect(parsed.entries).toEqual([])
            expect(parsed.errors).toHaveLength(1)
            expect(parsed.errors[0]).toContain('No recipient column found')
        })

        // The export quote-prefixes formula-leading identifiers so spreadsheets don't evaluate
        // them; the round trip only works if parsing strips that escape back off. A quote not
        // followed by a formula trigger is a real identifier and must survive.
        it.each([
            { value: "'=SUM(A1:B1)", expected: '=SUM(A1:B1)' },
            { value: "'+15551234567", expected: '+15551234567' },
            { value: "'quoted@example.com", expected: "'quoted@example.com" },
        ])('unescapes the formula-neutralizing quote prefix in "$value"', ({ value, expected }) => {
            const parsed = parseOptOutRows([['identifier'], [value]])

            expect(parsed.entries).toEqual([{ identifier: expected, category_key: undefined, row: 2 }])
        })

        it('reads the category column and skips rows missing a recipient, keeping file row numbers', () => {
            const parsed = parseOptOutRows([
                ['email', 'category_key'],
                ['ally@example.com', 'newsletter'],
                ['', 'newsletter'],
                ['  ', ''],
                ['sam@example.com', ''],
            ])

            expect(parsed.entries).toEqual([
                { identifier: 'ally@example.com', category_key: 'newsletter', row: 2 },
                { identifier: 'sam@example.com', category_key: undefined, row: 5 },
            ])
            expect(parsed.total).toBe(3)
            expect(parsed.skipped).toBe(1)
            expect(parsed.errors).toEqual(['Row 3: missing a recipient'])
        })
    })

    describe('remapEntryErrors', () => {
        it('rewrites entry numbers to the file rows the entries came from', () => {
            const chunk = [
                { identifier: 'a@example.com', row: 1002 },
                { identifier: 'b@example.com', row: 1003 },
            ]

            expect(
                remapEntryErrors(["Entry 2: no message category with key 'nope'", 'Unrelated error'], chunk)
            ).toEqual(["Row 1003: no message category with key 'nope'", 'Unrelated error'])
        })
    })
})
