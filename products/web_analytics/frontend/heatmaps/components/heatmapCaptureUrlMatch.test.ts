import { isUrlCoveredByAllowlist } from './heatmapCaptureSettingsLogic'

describe('isUrlCoveredByAllowlist', () => {
    it.each<[string, string, string[], boolean]>([
        ['exact match', 'https://example.com/pricing', ['https://example.com/pricing'], true],
        ['no match', 'https://example.com/blog', ['https://example.com/pricing'], false],
        ['wildcard matches deeper path', 'https://example.com/docs/setup', ['https://example.com/docs/*'], true],
        ['wildcard matches zero characters', 'https://example.com/docs/', ['https://example.com/docs/*'], true],
        ['dot is literal, not a wildcard', 'https://exampleXcom/a', ['https://example.com/a'], false],
        ['empty allowlist covers nothing', 'https://example.com/a', [], false],
        ['several wildcards match in order', 'https://example.com/a/x/b/y', ['https://example.com/*/x/*/y'], true],
        [
            'several wildcards reject out of order',
            'https://example.com/a/y/b/x',
            ['https://example.com/*/x/*/y'],
            false,
        ],
        ['wildcard segment cannot overlap the suffix', 'https://example.com/ab', ['https://example.com/*ab*b'], false],
        [
            'repeated wildcards reject a long url without backtracking',
            `https://example.com/${'a'.repeat(5000)}`,
            [`https://example.com/${'*a'.repeat(12)}b`],
            false,
        ],
    ])('%s', (_name, url, allowlist, expected) => {
        expect(isUrlCoveredByAllowlist(url, allowlist)).toBe(expected)
    })
})
