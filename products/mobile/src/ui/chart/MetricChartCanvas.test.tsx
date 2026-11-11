import { act, fireEvent, render, screen } from '@testing-library/react-native'
import { getCalendars } from 'expo-localization'
import { AppState } from 'react-native'
import 'react-native-gesture-handler/jestSetup'

import { MetricChartCanvas } from './MetricChartCanvas'
import type { ChartVariant } from './types'

jest.unmock('./MetricChartCanvas')
jest.mock('@/lib/useClockPreference', () => jest.requireActual('@/lib/useClockPreference.android'))
jest.mock('react-native-worklets', () => jest.requireActual('react-native-worklets/src/mock'))
jest.mock('react-native-reanimated', () => jest.requireActual('react-native-reanimated/mock'))
jest.mock('./MetricChartRenderer', () => ({ MetricChartRenderer: () => null }))

describe('MetricChartCanvas', () => {
    test('updates hourly axis labels when returning from Android clock settings', () => {
        const calendar = getCalendars()[0]
        render(
            <MetricChartCanvas
                kind="line"
                accent="opportunity"
                interval="hour"
                label="Events"
                formatValue={String}
                points={[{ at: new Date(2026, 9, 13, 17).getTime(), value: 1 }]}
                testID="metric"
            />
        )
        fireEvent(screen.getByTestId('metric'), 'layout', { nativeEvent: { layout: { width: 320 } } })
        expect(screen.getByText('5:00 PM')).toBeOnTheScreen()

        jest.mocked(getCalendars).mockReturnValue([{ ...calendar, uses24hourClock: true }])
        act(() => {
            for (const [event, listener] of jest.mocked(AppState.addEventListener).mock.calls) {
                if (event === 'change') listener('active')
            }
        })
        expect(screen.getByText('17:00')).toBeOnTheScreen()
        jest.mocked(getCalendars).mockReturnValue([calendar])
    })

    test.each<[ChartVariant, number | undefined, number, number]>([
        ['inline', undefined, 48, 100],
        ['inline', 240, 48, 196],
        ['fullscreen', 400, 48, 356],
        ['inline', undefined, 1, 144],
        ['compact', undefined, 48, 96],
    ])('fits the pager within the reserved height: %s, %s, %s buckets', (variant, height, count, plotHeight) => {
        render(
            <MetricChartCanvas
                kind="bar"
                accent="opportunity"
                interval="hour"
                label="Events"
                formatValue={String}
                variant={variant}
                height={height}
                points={Array.from({ length: count }, (_, index) => ({
                    at: new Date(2026, 9, 13, index).getTime(),
                    value: index + 1,
                }))}
                testID="metric"
            />
        )
        fireEvent(screen.getByTestId('metric'), 'layout', { nativeEvent: { layout: { width: 320 } } })

        expect(screen.getByTestId('metric')).toHaveStyle({ height: plotHeight })
        if (variant !== 'compact' && count > 1) {
            expect(screen.getByTestId('chart-dates-earlier')).toBeTruthy()
        } else {
            expect(screen.queryByTestId('chart-dates-earlier')).toBeNull()
        }
    })
})
