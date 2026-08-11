import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'

import { initKeaTests } from '~/test/init'

import {
    PagePreflight,
    heatmapsBrowserLogic,
    normalizeHeatmapDataUrl,
    preflightBannerMessage,
} from './heatmapsBrowserLogic'

describe('heatmapsBrowserLogic', () => {
    describe('normalizeHeatmapDataUrl', () => {
        it.each([
            ['example.com', null],
            ['   ', null],
            ['', null],
            [null, null],
            ['h', null],
            ['https://', null],
            ['https://example.com', { href: 'https://example.com/', matchType: 'exact' }],
            ['https://example.com/pricing', { href: 'https://example.com/pricing', matchType: 'exact' }],
            ['  https://example.com/pricing  ', { href: 'https://example.com/pricing', matchType: 'exact' }],
            ['https://example.com/users/*', { href: 'https://example.com/users/*', matchType: 'pattern' }],
        ] as const)('normalizeHeatmapDataUrl(%s) → %s', (input, expected) => {
            expect(normalizeHeatmapDataUrl(input)).toEqual(expected)
        })
    })

    describe('preflightBannerMessage', () => {
        const base: PagePreflight = {
            url: 'https://shop.example.com/p',
            framing: 'allowed',
            blocked_by: null,
            http_status: 200,
            body_excerpt: null,
        }

        it.each([
            ['blocked by csp', { framing: 'blocked', blocked_by: 'frame_ancestors' }, 'content security policy'],
            ['blocked by xfo', { framing: 'blocked', blocked_by: 'x_frame_options' }, 'X-Frame-Options'],
        ] as const)('explains why the live preview cannot load when %s', (_name, overrides, expected) => {
            const message = preflightBannerMessage({ ...base, ...overrides })
            expect(message).toContain('shop.example.com')
            expect(message).toContain(expected)
        })

        it('attributes a non-2xx to the customer host and quotes what it returned', () => {
            const message = preflightBannerMessage({
                ...base,
                framing: 'unknown',
                http_status: 429,
                body_excerpt: 'local_rate_limited',
            })

            expect(message).toContain('429')
            expect(message).toContain('local_rate_limited')
            expect(message).toContain('host or CDN')
            expect(message).not.toContain('embedding')
        })

        it.each([
            ['a healthy page', base],
            ['an inconclusive probe', { ...base, framing: 'unknown', http_status: null }],
            // A redirect is how a healthy page normally answers, and the browser follows it, so it
            // must never be reported as the customer's host refusing us.
            ['a redirect', { ...base, framing: 'unknown', http_status: 301 }],
        ] as const)('stays silent for %s', (_name, preflight) => {
            expect(preflightBannerMessage(preflight)).toBeNull()
        })
    })

    describe('page URL query-param sync', () => {
        beforeEach(() => {
            initKeaTests()
            jest.spyOn(api, 'queryHogQL').mockResolvedValue({ results: [] } as any)
            router.actions.push('/heatmaps/new')
        })

        afterEach(() => {
            jest.restoreAllMocks()
        })

        it('keeps the page URL cleared on the first delete instead of resurrecting it from the querystring', async () => {
            const logic = heatmapsBrowserLogic()
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            logic.actions.setDisplayUrl('https://example.com/pricing')
            await expectLogic(logic).toFinishAllListeners()
            expect(router.values.searchParams.pageURL).toBe('https://example.com/pricing')

            logic.actions.setDisplayUrl('')
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.displayUrl).toBe('')
            expect(router.values.searchParams.pageURL).toBeUndefined()
        })
    })

    describe('iframeBanner', () => {
        beforeEach(() => {
            initKeaTests()
            jest.spyOn(api, 'queryHogQL').mockResolvedValue({ results: [] } as any)
            router.actions.push('/heatmaps/abc123')
        })

        afterEach(() => {
            jest.restoreAllMocks()
        })

        // A frame blocked by X-Frame-Options still fires onload, and onIframeLoad nulls the load-timeout
        // banner via stopTrackingLoading. Before the probe result outranked it, that wiped the explanation
        // and the user was left with a blank frame and no message at all.
        it('keeps explaining a blocked page after the iframe reports it loaded', async () => {
            const logic = heatmapsBrowserLogic({ iframeRef: { current: null } })
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            logic.actions.setDisplayUrl('https://shop.example.com/p')
            logic.actions.checkPagePreflightSuccess({
                url: 'https://shop.example.com/p',
                framing: 'blocked',
                blocked_by: 'x_frame_options',
                http_status: 200,
                body_excerpt: null,
            })
            logic.actions.onIframeLoad()
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.loadTimeoutBanner).toBeNull()
            expect(logic.values.iframeBanner?.level).toBe('error')
            expect(logic.values.iframeBanner?.message).toContain('X-Frame-Options')

            // Editing the URL must drop the old verdict rather than blaming the new page for it.
            logic.actions.setDisplayUrl('https://other.example.com/p')
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.iframeBanner).toBeNull()
        })
    })
})
