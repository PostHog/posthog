import { isUrlCoveredByAllowlist } from './heatmapCaptureSettingsLogic'

describe('isUrlCoveredByAllowlist', () => {
    it.each<[string, string, string[], boolean]>([
        ['exact match', 'https://example.com/pricing', ['https://example.com/pricing'], true],
        ['no match', 'https://example.com/blog', ['https://example.com/pricing'], false],
        ['wildcard matches deeper path', 'https://example.com/docs/setup', ['https://example.com/docs/*'], true],
        ['wildcard matches zero characters', 'https://example.com/docs/', ['https://example.com/docs/*'], true],
        ['dot is literal, not a wildcard', 'https://exampleXcom/a', ['https://example.com/a'], false],
        ['empty allowlist covers nothing', 'https://example.com/a', [], false],
    ])('%s', (_name, url, allowlist, expected) => {
        expect(isUrlCoveredByAllowlist(url, allowlist)).toBe(expected)
    })
})
