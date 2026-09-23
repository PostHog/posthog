import { defaultScannerTemplates, findScannerTemplate, isSuggestedScannerName, newScanner } from './scannerTemplates'

describe('findScannerTemplate', () => {
    it('returns the matching template by key', () => {
        const first = defaultScannerTemplates[0]
        expect(findScannerTemplate(first.key)).toBe(first)
    })

    it.each([
        { label: 'undefined', input: undefined as string | undefined },
        { label: 'empty string', input: '' as string | undefined },
        { label: 'unknown key', input: 'nonexistent-key-xyz' as string | undefined },
    ])('returns undefined for $label', ({ input }) => {
        expect(findScannerTemplate(input)).toBeUndefined()
    })
})

describe('newScanner', () => {
    it.each([
        { label: 'null', input: null as string | null | undefined },
        { label: 'omitted', input: undefined as string | null | undefined },
        { label: 'unknown key', input: 'nonexistent-key-xyz' as string | null | undefined },
    ])('falls back to a blank monitor scanner when templateKey is $label', ({ input }) => {
        expect(newScanner(input)).toMatchObject({
            scanner_type: 'monitor',
            scanner_config: { prompt: '' },
            name: 'New monitor',
        })
    })

    it('blank scanner carries the expected default id, enabled, and sampling fields', () => {
        expect(newScanner(null)).toMatchObject({
            id: 'new',
            enabled: true,
            // Narrow by default so the budget step's first estimate isn't a whole-project number.
            sampling_rate: 0.2,
            sampling_mode: 'balanced',
            description: '',
            tags: [],
        })
    })

    it.each([
        // Every name the wizard fills in by itself is the same for everyone on the team, so it has
        // to read as proposed or the second scanner of that shape can never save.
        ['the scratch default', 'Hedgebox monitor', true],
        ['a template name', defaultScannerTemplates[0].scanner_name, true],
        ['an experiment-scoped default', 'Hedgebox monitor: Checkout test', true],
        ['a blank name', '   ', true],
        ['a name the user typed', 'Why people bounce', false],
        // A near miss must read as chosen: the API renames a proposed name without asking.
        ['a default the user edited', 'Hedgebox monitor v2', false],
    ])('reads %s correctly', (_case, name, expected) => {
        expect(isSuggestedScannerName(name, 'Hedgebox', 'monitor', 'Checkout test')).toBe(expected)
    })

    it.each(defaultScannerTemplates.map((t) => [t.key, t]))(
        'applies the %s template config and metadata when picked',
        (_key, template) => {
            const scanner = newScanner(template.key)
            expect(scanner).toMatchObject({
                name: template.scanner_name,
                description: template.scanner_description,
                scanner_type: template.scanner_type,
                scanner_config: template.scanner_config,
            })
        }
    )
})
