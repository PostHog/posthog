import { router, Slot } from 'expo-router'
import { act, renderRouter } from 'expo-router/testing-library'
import type { ReactElement } from 'react'
import { View } from 'react-native'

import { setAnalyticsClient } from './analytics'
import { screenEntityProperties, useScreenTracking } from './useScreenTracking'

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
                'report/[id]': Stub,
                'report/[id]/details': Stub,
            },
            { initialUrl: '/' }
        )

        act(() => router.push('/inbox'))
        act(() => router.setParams({ unrelated: '1' }))
        act(() => router.push('/report/00000000-0000-4000-8000-000000000001'))
        act(() => router.push('/report/00000000-0000-4000-8000-000000000002'))

        act(() => router.push('/report/00000000-0000-4000-8000-000000000002/details'))

        expect(screen.mock.calls).toEqual([
            ['inbox', { client_surface: 'mobile', screen: 'inbox' }],
            [
                'report/[id]',
                { report_id: '00000000-0000-4000-8000-000000000001', client_surface: 'mobile', screen: 'report/[id]' },
            ],
            [
                'report/[id]',
                { report_id: '00000000-0000-4000-8000-000000000002', client_surface: 'mobile', screen: 'report/[id]' },
            ],
            [
                'report/[id]/details',
                {
                    report_id: '00000000-0000-4000-8000-000000000002',
                    client_surface: 'mobile',
                    screen: 'report/[id]/details',
                },
            ],
        ])
    })
})

test('entity context is bounded and separates chats, dashboard and insight destinations', () => {
    const taskId = '00000000-0000-4000-8000-000000000003'
    expect(screenEntityProperties('chat', { taskId, draft: 'private message' })).toEqual({ task_id: taskId })
    expect(screenEntityProperties('chat', { taskId: 'private message' })).toEqual({})
    expect(screenEntityProperties('views/dashboard/[id]', { id: '12', title: 'private dashboard' })).toEqual({
        dashboard_id: '12',
    })
    expect(screenEntityProperties('views/insight/[shortId]', { shortId: 'example-chart' })).toEqual({
        insight_short_id: 'example-chart',
    })
})
