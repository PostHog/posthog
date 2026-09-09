import { defaultScannerTemplates, findScannerTemplate, newScanner } from './scannerTemplates'

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
