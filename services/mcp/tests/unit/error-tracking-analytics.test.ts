import { describe, expect, it } from 'vitest'

import { ErrorTrackingQueryIssuesListCreateBody } from '@/generated/error_tracking/api'
import { errorTrackingAnalyticsProperties } from '@/tools/errorTracking/analytics'

/**
 * These lock in two regressions: an issues list call that records no page size or
 * volume buckets (the whole point), and anything other than a bounded integer
 * reaching analytics.
 */
describe('errorTrackingAnalyticsProperties', () => {
    it('records the page size and volume buckets of an issues list call', () => {
        expect(
            errorTrackingAnalyticsProperties('query-error-tracking-issues-list', {
                limit: 50,
                volumeResolution: 24,
                searchQuery: 'private caller text',
            })
        ).toEqual({ error_tracking_limit: 50, error_tracking_volume_resolution: 24 })
    })

    it('records zero volume buckets, the value for no volume data', () => {
        expect(
            errorTrackingAnalyticsProperties('query-error-tracking-issues-list', { limit: 10, volumeResolution: 0 })
        ).toEqual({ error_tracking_limit: 10, error_tracking_volume_resolution: 0 })
    })

    it.each([
        // Stamping other tools would put unrelated `limit` arguments on their events.
        ['another tool', 'query-error-tracking-issue-events', { limit: 50, volumeResolution: 24 }],
        ['no tool name', undefined, { limit: 50 }],
        ['a non-object input', 'query-error-tracking-issues-list', 'limit=50'],
        ['an array input', 'query-error-tracking-issues-list', [50]],
        ['a null input', 'query-error-tracking-issues-list', null],
    ])('records nothing for %s', (_label, tool, args) => {
        expect(errorTrackingAnalyticsProperties(tool, args)).toEqual({})
    })

    it.each([
        ['a string', '50'],
        ['a fraction', 2.5],
        ['a negative number', -1],
        ['NaN', Number.NaN],
    ])('drops a value that is %s', (_label, value) => {
        expect(
            errorTrackingAnalyticsProperties('query-error-tracking-issues-list', {
                limit: value,
                volumeResolution: value,
            })
        ).toEqual({})
    })

    // The executor passes parsed input, so an omitted field is recorded as the
    // default the handler sent to the API.
    it('records schema defaults when the caller omits both fields', () => {
        const parsed = ErrorTrackingQueryIssuesListCreateBody().parse({})
        expect(errorTrackingAnalyticsProperties('query-error-tracking-issues-list', parsed)).toEqual({
            error_tracking_limit: 10,
            error_tracking_volume_resolution: 0,
        })
    })
})
