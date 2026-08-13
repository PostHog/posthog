import { HeatmapType } from '~/types'

import { isValidPageUrl, resolveHeatmapExportUrl } from './heatmapLogic'

describe('heatmapLogic', () => {
    describe('isValidPageUrl', () => {
        it.each([
            ['empty is valid, nothing typed yet', null, true],
            ['a plain absolute URL', 'https://example.com/pricing', true],
            // The reported bug: a query string was read as a wildcard and the URL was rejected.
            ['an absolute URL with a query string', 'https://example.com/pricing?plan=business', true],
            // Only `*` is a page-URL wildcard now, so other regex characters stay valid in the path.
            ['parentheses in the path', 'https://example.com/docs/(beta)', true],
            ['a wildcard page URL', 'https://example.com/*', false],
            ['a bare domain without a scheme', 'example.com', false],
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
})
