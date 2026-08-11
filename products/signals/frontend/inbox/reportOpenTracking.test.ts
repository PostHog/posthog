import { hasReportBeenOpenedThisSession, markReportOpenedThisSession } from './reportOpenTracking'

describe('reportOpenTracking', () => {
    beforeEach(() => {
        sessionStorage.clear()
    })

    it('reports an id as opened only after it is marked, so a reload can suppress the duplicate', () => {
        expect(hasReportBeenOpenedThisSession('report-1')).toBe(false)
        markReportOpenedThisSession('report-1')
        expect(hasReportBeenOpenedThisSession('report-1')).toBe(true)
    })

    it('tracks each report independently and persists across calls (a fresh read is a new tab reload)', () => {
        markReportOpenedThisSession('report-1')
        markReportOpenedThisSession('report-2')
        expect(hasReportBeenOpenedThisSession('report-1')).toBe(true)
        expect(hasReportBeenOpenedThisSession('report-2')).toBe(true)
        expect(hasReportBeenOpenedThisSession('report-3')).toBe(false)
    })

    it('treats corrupt sessionStorage as no history instead of throwing', () => {
        sessionStorage.setItem('inbox_opened_report_ids', 'not json')
        expect(hasReportBeenOpenedThisSession('report-1')).toBe(false)
        // A later mark still recovers the store rather than staying wedged on the bad value.
        markReportOpenedThisSession('report-1')
        expect(hasReportBeenOpenedThisSession('report-1')).toBe(true)
    })
})
