import { router, Slot } from 'expo-router'
import { act, renderRouter } from 'expo-router/testing-library'
import type { ReactElement } from 'react'
import { View } from 'react-native'

import { setAnalyticsClient } from './analytics'
import { useScreenTracking } from './useScreenTracking'

function TrackedLayout(): ReactElement {
    useScreenTracking(true)
    return <Slot />
}

function Stub(): ReactElement {
    return <View />
}

describe('useScreenTracking', () => {
    afterEach(() => {
        setAnalyticsClient(null)
    })

    test('sends one $screen per route, named by pattern, with a new report id counting as a new screen', () => {
        const screen = jest.fn()
        setAnalyticsClient({ capture: jest.fn(), screen, identify: jest.fn(), reset: jest.fn() })
        renderRouter(
            {
                _layout: TrackedLayout,
                index: Stub,
                '(tabs)/inbox': Stub,
                'report/[id]/index': Stub,
                'report/[id]/details': Stub,
            },
            { initialUrl: '/' }
        )

        act(() => router.push('/inbox'))
        act(() => router.setParams({ unrelated: '1' }))
        act(() => router.push('/report/report-a'))
        act(() => router.push('/report/report-b'))
        act(() => router.push('/report/report-b/details'))

        expect(screen.mock.calls).toEqual([
            ['inbox', undefined],
            ['report/[id]', { report_id: 'report-a' }],
            ['report/[id]', { report_id: 'report-b' }],
            ['report/[id]/details', { report_id: 'report-b' }],
        ])
    })
})
