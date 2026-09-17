import { renderHook } from '@testing-library/react'

import { useViewServiceMetricsButton } from './ViewServiceMetricsButton'

jest.mock('lib/hooks/useFeatureFlag', () => ({
    useFeatureFlag: () => true,
}))
jest.mock('products/metrics/frontend/metricsAccess', () => ({
    canViewMetrics: () => true,
}))

describe('useViewServiceMetricsButton', () => {
    it('builds a metrics URL scoped to the service and window', () => {
        const { result } = renderHook(() =>
            useViewServiceMetricsButton({
                serviceName: 'billing-worker',
                dateFrom: '2026-06-11T07:00:00.000Z',
                dateTo: '2026-06-11T09:00:00.000Z',
            })
        )

        expect(result.current.enabled).toBe(true)
        expect(result.current.disabledReason).toBeUndefined()
        expect(result.current.to).toContain('billing-worker')
    })

    it('reports a disabled reason and no URL when there is no service name', () => {
        const { result } = renderHook(() => useViewServiceMetricsButton({ serviceName: null }))

        expect(result.current.enabled).toBe(true)
        expect(result.current.to).toBeUndefined()
        expect(result.current.disabledReason).toBe('No service associated with this event')
    })
})
