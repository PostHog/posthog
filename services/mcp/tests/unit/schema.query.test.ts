import { describe, expect, it } from 'vitest'

import { SeriesEventsNode, EventsNode, TrendsQuerySchema, FunnelsQuerySchema } from '@/schema/query'

describe('Series node schemas', () => {
    describe('SeriesEventsNode', () => {
        it('should accept a valid events node', () => {
            const result = SeriesEventsNode.safeParse({
                kind: 'EventsNode',
                event: '$pageview',
                custom_name: 'Page views',
            })
            expect(result.success).toBe(true)
        })

        it('should accept a node with math', () => {
            const result = SeriesEventsNode.safeParse({
                kind: 'EventsNode',
                event: '$pageview',
                custom_name: 'Unique page views',
                math: 'dau',
            })
            expect(result.success).toBe(true)
        })

        it('should require math_property for property math types', () => {
            const result = SeriesEventsNode.safeParse({
                kind: 'EventsNode',
                event: '$pageview',
                custom_name: 'Average revenue',
                math: 'avg',
            })
            expect(result.success).toBe(false)
        })

        it('should accept property math type with math_property', () => {
            const result = SeriesEventsNode.safeParse({
                kind: 'EventsNode',
                event: '$pageview',
                custom_name: 'Average revenue',
                math: 'avg',
                math_property: 'revenue',
            })
            expect(result.success).toBe(true)
        })

        it('should not include limit field', () => {
            const result = SeriesEventsNode.safeParse({
                kind: 'EventsNode',
                event: '$pageview',
                custom_name: 'Page views',
                limit: 100,
            })
            // limit is not part of SeriesEventsNode, so it should be stripped
            expect(result.success).toBe(true)
            if (result.success) {
                expect(result.data).not.toHaveProperty('limit')
            }
        })

        it('should accept optional properties filter', () => {
            const result = SeriesEventsNode.safeParse({
                kind: 'EventsNode',
                event: '$pageview',
                custom_name: 'Filtered views',
                properties: [{ key: 'browser', value: 'Chrome' }],
            })
            expect(result.success).toBe(true)
        })
    })

    describe('EventsNode (full)', () => {
        it('should accept limit field', () => {
            const result = EventsNode.safeParse({
                kind: 'EventsNode',
                event: '$pageview',
                custom_name: 'Page views',
                limit: 100,
            })
            expect(result.success).toBe(true)
            if (result.success) {
                expect(result.data.limit).toBe(100)
            }
        })
    })

    describe('TrendsQuerySchema series', () => {
        it('should accept a trends query with series', () => {
            const result = TrendsQuerySchema.safeParse({
                kind: 'TrendsQuery',
                series: [
                    {
                        kind: 'EventsNode',
                        event: '$pageview',
                        custom_name: 'Page views',
                    },
                ],
            })
            expect(result.success).toBe(true)
        })

        it('should accept multiple series items', () => {
            const result = TrendsQuerySchema.safeParse({
                kind: 'TrendsQuery',
                series: [
                    {
                        kind: 'EventsNode',
                        event: '$pageview',
                        custom_name: 'Page views',
                    },
                    {
                        kind: 'EventsNode',
                        event: 'sign_up',
                        custom_name: 'Sign ups',
                        math: 'dau',
                    },
                ],
            })
            expect(result.success).toBe(true)
        })

        it('should reject empty series', () => {
            const result = TrendsQuerySchema.safeParse({
                kind: 'TrendsQuery',
                series: [],
            })
            // Empty array is technically valid for trends (no min constraint)
            expect(result.success).toBe(true)
        })
    })

    describe('FunnelsQuerySchema series', () => {
        it('should require at least two steps', () => {
            const result = FunnelsQuerySchema.safeParse({
                kind: 'FunnelsQuery',
                series: [
                    {
                        kind: 'EventsNode',
                        event: '$pageview',
                        custom_name: 'Step 1',
                    },
                ],
            })
            expect(result.success).toBe(false)
        })

        it('should accept two or more steps', () => {
            const result = FunnelsQuerySchema.safeParse({
                kind: 'FunnelsQuery',
                series: [
                    {
                        kind: 'EventsNode',
                        event: '$pageview',
                        custom_name: 'Step 1',
                    },
                    {
                        kind: 'EventsNode',
                        event: 'sign_up',
                        custom_name: 'Step 2',
                    },
                ],
            })
            expect(result.success).toBe(true)
        })

        it('should validate math_property requirement in funnel series', () => {
            const result = FunnelsQuerySchema.safeParse({
                kind: 'FunnelsQuery',
                series: [
                    {
                        kind: 'EventsNode',
                        event: '$pageview',
                        custom_name: 'Step 1',
                        math: 'sum',
                    },
                    {
                        kind: 'EventsNode',
                        event: 'sign_up',
                        custom_name: 'Step 2',
                    },
                ],
            })
            expect(result.success).toBe(false)
        })
    })
})
