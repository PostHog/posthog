import { combineUrl } from 'kea-router'

import { traceLookupDateRange, traceUrl, tracingUrlForService } from './traceLinks'

describe('traceLinks', () => {
    it.each([
        [{ traceId: 'abc123' }, '/tracing?trace=abc123'],
        [{ traceId: 'abc123', spanId: 'def456' }, '/tracing?trace=abc123&span=def456'],
        [
            { traceId: 'abc123', spanId: 'def456', ts: '2026-06-11T08:00:00.000Z' },
            '/tracing?trace=abc123&span=def456&ts=2026-06-11T08%3A00%3A00.000Z',
        ],
        // Null/undefined anchor and hint are simply omitted.
        [{ traceId: 'abc123', spanId: null, ts: null }, '/tracing?trace=abc123'],
    ])('traceUrl(%j) → %s', (params, expected) => {
        expect(traceUrl(params)).toBe(expected)
    })

    it('traceLookupDateRange bounds the lookup to ±1h around the hint', () => {
        expect(traceLookupDateRange('2026-06-11T08:00:00.000Z')).toEqual({
            date_from: '2026-06-11T07:00:00.000Z',
            date_to: '2026-06-11T09:00:00.000Z',
        })
    })

    describe('tracingUrlForService', () => {
        const paramsOf = (url: string): Record<string, any> => combineUrl(url).searchParams

        it('carries the service as a list, so a name with a comma stays one service', () => {
            // tracingSceneLogic reads this back through parseTagsFilter, which splits a bare
            // string on commas — 'checkout,v2' would arrive as two services.
            expect(paramsOf(tracingUrlForService('checkout,v2')).serviceNames).toEqual(['checkout,v2'])
        })

        it('carries the window the caller was looking at', () => {
            const url = tracingUrlForService('checkout', { dateRange: { date_from: '-30m', date_to: null } })
            expect(JSON.parse(paramsOf(url).dateRange)).toEqual({ date_from: '-30m', date_to: null })
        })

        it('omits the window when the caller has none', () => {
            expect(paramsOf(tracingUrlForService('checkout'))).not.toHaveProperty('dateRange')
        })
    })
})
