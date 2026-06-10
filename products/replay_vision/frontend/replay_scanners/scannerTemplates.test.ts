import { defaultScannerTemplates, findScannerTemplate, newScanner } from './scannerTemplates'

describe('findScannerTemplate', () => {
    it('returns the matching template by key', () => {
        const first = defaultScannerTemplates[0]
        expect(findScannerTemplate(first.key)).toBe(first)
    })

    it('returns undefined for missing or unknown keys', () => {
        expect(findScannerTemplate(undefined)).toBeUndefined()
        expect(findScannerTemplate('')).toBeUndefined()
        expect(findScannerTemplate('nonexistent-key-xyz')).toBeUndefined()
    })
})

describe('newScanner', () => {
    it('returns a blank monitor scanner when no template is provided', () => {
        const scanner = newScanner(null)
        expect(scanner).toMatchObject({
            id: 'new',
            enabled: true,
            sampling_rate: 1,
            name: '',
            description: '',
            scanner_type: 'monitor',
            scanner_config: { prompt: '' },
        })
    })

    it('returns a blank monitor scanner when templateKey is omitted', () => {
        expect(newScanner()).toMatchObject({ scanner_type: 'monitor', scanner_config: { prompt: '' } })
    })

    it('falls back to a blank scanner when templateKey is unknown', () => {
        expect(newScanner('nonexistent-key-xyz')).toMatchObject({
            scanner_type: 'monitor',
            scanner_config: { prompt: '' },
            name: '',
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
