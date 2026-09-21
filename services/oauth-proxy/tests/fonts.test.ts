import { describe, expect, it } from 'vitest'

import { FONT_PATHS, handleFont } from '@/handlers/fonts'

import REGION_PICKER_HTML from '../src/static/region-picker.html'

// woff2 files start with this signature, so a wrong bundler rule shows up as a different body.
const WOFF2_SIGNATURE = 'wOF2'

describe('handleFont', () => {
    it.each(FONT_PATHS)('serves %s as a woff2 font', async (path) => {
        const response = handleFont(new Request(`https://oauth.posthog.com${path}`))

        expect(response.status).toBe(200)
        expect(response.headers.get('content-type')).toBe('font/woff2')

        const body = await response.arrayBuffer()
        expect(body.byteLength).toBeGreaterThan(0)
        expect(new TextDecoder().decode(body.slice(0, 4))).toBe(WOFF2_SIGNATURE)
    })

    it('serves every face the region picker asks for', () => {
        const requested = [...REGION_PICKER_HTML.matchAll(/url\('(\/static\/fonts\/[^']+)'\)/g)].map(
            (match) => match[1]
        )

        expect(requested.length).toBeGreaterThan(0)
        expect(new Set(requested)).toEqual(new Set(FONT_PATHS))
    })

    it('returns 404 for a face it does not bundle', () => {
        expect(handleFont(new Request('https://oauth.posthog.com/static/fonts/RoundHog-Bold.woff2')).status).toBe(404)
    })
})
