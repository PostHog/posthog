import { renderHook } from '@testing-library/react-native'

import { ApiError, NotSignedInError } from '@/api/client'
import { setAnalyticsClient } from '@/lib/analytics'

import { apiErrorKind, useSheetFunnel } from './reportAnalytics'

describe('reportAnalytics', () => {
    afterEach(() => {
        setAnalyticsClient(null)
    })

    test.each<[string, unknown, string]>([
        ['a missing scope', new ApiError(403, { detail: "API key missing required scope 'task:read'" }), 'scope'],
        ['another 403', new ApiError(403, { detail: 'You do not have access.' }), 'forbidden'],
        ['a 401', new ApiError(401, {}), 'auth'],
        ['no session', new NotSignedInError(), 'auth'],
        ['a 404', new ApiError(404, {}), 'not_found'],
        ['a 502', new ApiError(502, {}), 'server'],
        ['a network failure', new TypeError('Network request failed'), 'network'],
    ])('apiErrorKind: %s', (_name, error, expected) => {
        expect(apiErrorKind(error)).toBe(expected)
    })

    test('a sheet counts as dismissed only when it closes before it completes', () => {
        const capture = jest.fn()
        setAnalyticsClient({ capture, identify: jest.fn(), reset: jest.fn() })
        const { result } = renderHook(() => useSheetFunnel('report-1'))

        result.current.opened('resolve', 'action_bar')
        result.current.completed()
        result.current.closed()
        result.current.opened('assignee', 'chip')
        result.current.closed()
        result.current.closed()

        expect(capture.mock.calls.map(([event, properties]) => [event, properties?.sheet])).toEqual([
            ['mobile_report_sheet_opened', 'resolve'],
            ['mobile_report_sheet_opened', 'assignee'],
            ['mobile_report_sheet_dismissed', 'assignee'],
        ])
    })
})
