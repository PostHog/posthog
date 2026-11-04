import { ApiError } from 'lib/api-error'

import { forgetUnreachableReports, isReportUnreachable, rememberUnreachableReport } from './unreachableReports'

describe('unreachableReports', () => {
    beforeEach(() => {
        forgetUnreachableReports()
    })

    it('remembers a report the endpoint answered 404 for', () => {
        rememberUnreachableReport('report-1', new ApiError('Not found', 404))
        expect(isReportUnreachable('report-1')).toBe(true)
        expect(isReportUnreachable('report-2')).toBe(false)
    })

    test.each([
        ['server error', new ApiError('Boom', 500)],
        ['gateway error', new ApiError('Bad gateway', 502)],
        ['no response at all', new TypeError('Failed to fetch')],
    ])('keeps a report retryable after %s', (_label, reason) => {
        rememberUnreachableReport('report-1', reason)
        expect(isReportUnreachable('report-1')).toBe(false)
    })
})
