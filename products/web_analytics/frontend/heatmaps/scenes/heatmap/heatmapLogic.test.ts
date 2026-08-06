import { HeatmapType } from '~/types'

import { isValidPageUrl, resolveHeatmapExportUrl } from './heatmapLogic'

describe('isValidPageUrl', () => {
    it.each([
        ['empty is valid (nothing entered yet)', null, true],
        ['a plain absolute URL', 'https://example.com/pricing', true],
        // The reported bug: a query string was misread as a wildcard and rejected.
        ['an absolute URL with a query string', 'https://example.com/pricing?plan=business', true],
        ['an absolute URL with multiple query params', 'https://example.com/login?next=%2Fapp&ref=nav', true],
        // A bare domain used to throw in new URL(); it is now accepted as https.
        ['a bare domain', 'example.com', true],
        ['a wildcard page URL', 'https://example.com/*', false],
        ['gibberish', 'not a url', false],
    ])('%s', (_case, url, expected) => {
        expect(isValidPageUrl(url)).toBe(expected)
    })
})

describe('resolveHeatmapExportUrl', () => {
    const origin = 'https://us.posthog.com'

    it.each([
        [
            'screenshot',
            '/api/environments/1/heatmap_screenshots/42/content/?width=1400',
            'https://example.com/page',
            `${origin}/api/environments/1/heatmap_screenshots/42/content/?width=1400`,
        ],
        [
            'iframe',
            '/api/environments/1/heatmap_screenshots/42/content/',
            'https://example.com/page',
            'https://example.com/page',
        ],
        ['screenshot', null, 'https://example.com/page', ''],
        ['iframe', '/api/something', null, ''],
        [
            'screenshot',
            'https://another.posthog.com/api/environments/1/heatmap_screenshots/42/content/',
            null,
            'https://another.posthog.com/api/environments/1/heatmap_screenshots/42/content/',
        ],
    ] as const)(
        'resolveHeatmapExportUrl(%s, screenshotUrl=%s, displayUrl=%s) → %s',
        (type, screenshotUrl, displayUrl, expected) => {
            expect(resolveHeatmapExportUrl(type as HeatmapType, screenshotUrl, displayUrl, origin)).toBe(expected)
        }
    )
})
