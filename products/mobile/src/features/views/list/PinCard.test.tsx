import { fireEvent, render } from '@testing-library/react-native'

import type { InsightApi } from '@/api/insights'
import { insightSnapshot } from '@/model/adapters/insightSnapshot'
import type { PinView } from '@/model/views'

import { type PinData, usePinData } from '../pinHooks'
import { ModeSegment } from './ModeSegment'
import { PinCard } from './PinCard'

jest.mock('react-native-reanimated', () => {
    const { View } = jest.requireActual<typeof import('react-native')>('react-native')
    return {
        __esModule: true,
        default: { View },
        useReducedMotion: () => true,
        useSharedValue: (value: number) => ({ value }),
        useAnimatedStyle: (style: () => unknown) => style(),
        cancelAnimation: jest.fn(),
    }
})
jest.mock('react-native-worklets', () => ({ scheduleOnRN: jest.fn() }))
jest.mock('../useViewsContext', () => ({ useViewsContext: () => ({ scope: null }) }))
jest.mock('../pinHooks', () => ({ usePinData: jest.fn() }))
jest.mock('../viewsCache', () => ({ ...jest.requireActual('../viewsCache'), useSnapshot: () => undefined }))

const pin: PinView = {
    shortcutId: 'real-shortcut',
    shortcutIds: ['real-shortcut'],
    kind: 'dashboard',
    ref: '42',
    name: 'Product overview',
    href: '/dashboard/42',
    native: true,
    rank: null,
    type: 'dashboard',
    serverOrder: 0,
    display: { mode: 'number', tileId: 9, insightId: 7, insightShortId: 'signups' },
}
const response: InsightApi = {
    id: 7,
    short_id: 'signups',
    name: 'Daily signups',
    derived_name: null,
    query: {
        kind: 'InsightVizNode',
        source: {
            kind: 'TrendsQuery',
            interval: 'day',
            series: [{ kind: 'EventsNode', event: 'signed_up' }],
            trendsFilter: { display: 'ActionsLineGraph' },
            dateRange: { date_from: '-7d' },
        },
    },
    result: [{ data: [10, 12, 14], days: ['2026-10-18', '2026-10-19', '2026-10-20'], label: 'signed_up' }],
    last_refresh: '2026-10-20T11:55:00Z',
    cache_target_age: '2026-10-20T12:55:00Z',
    next_allowed_client_refresh: '2026-10-20T12:00:00Z',
    is_cached: true,
    resolved_date_range: { date_from: '2026-10-18T00:00:00Z', date_to: '2026-10-20T23:59:59Z' },
}
const snapshot = insightSnapshot(response, undefined, { readAt: 1, serverNow: Date.parse('2026-10-20T12:00:00Z') })
const data: PinData = {
    target: null,
    itemKey: null,
    snapshot,
    updating: false,
    error: null,
    tileRemoved: false,
    rangeLabel: 'Last 7 days',
}
const callbacks = { onOpen: jest.fn(), onMenu: jest.fn(), onChooseTile: jest.fn(), onUnpin: jest.fn() }

describe('PinCard', () => {
    beforeEach(() => {
        jest.useFakeTimers()
        jest.setSystemTime(new Date('2026-10-20T12:00:00Z'))
        jest.clearAllMocks()
        jest.mocked(usePinData).mockReturnValue(data)
    })
    afterEach(() => jest.useRealTimers())

    it.each(['number', 'chart'] as const)('shows dashboard and metric context on the actual %s pin', (mode) => {
        const shown = { ...pin, display: { ...pin.display, mode } }
        const screen = render(<PinCard pin={shown} index={0} demo={false} {...callbacks} />)
        expect(screen.getAllByText('Product overview')).toHaveLength(1)
        expect(screen.getAllByText('Daily signups')).toHaveLength(1)
        expect(screen.getByText('Last 7 days')).toBeTruthy()
        expect(screen.getByText('Updated 5 min ago')).toBeTruthy()
        expect(screen.getByTestId('views-pin-value-dashboard-42').props.children).toBe('12')
        fireEvent.press(screen.getByTestId('views-pin-value-dashboard-42'))
        expect(callbacks.onOpen).toHaveBeenCalledWith(shown)
    })

    it('shows a standalone insight range once in its footer', () => {
        const shown = { ...pin, kind: 'insight' as const, ref: 'signups', name: 'Daily signups' }
        const screen = render(<PinCard pin={shown} index={0} demo={false} {...callbacks} />)
        expect(screen.getByText('Insight')).toBeTruthy()
        expect(screen.getAllByText('Last 7 days')).toHaveLength(1)
    })

    it.each(['series', 'breakdown', 'sql'] as const)(
        'keeps every %s in a chart pin without an ambiguous headline',
        (shape) => {
            const multi = insightSnapshot(
                {
                    ...response,
                    query:
                        shape === 'sql'
                            ? {
                                  kind: 'DataVisualizationNode',
                                  display: 'ActionsBar',
                                  source: { kind: 'HogQLQuery', query: 'select 1' },
                              }
                            : {
                                  kind: 'InsightVizNode',
                                  source: {
                                      kind: 'TrendsQuery',
                                      series:
                                          shape === 'series'
                                              ? [
                                                    { kind: 'EventsNode', event: 'signed_up' },
                                                    { kind: 'EventsNode', event: 'invited' },
                                                ]
                                              : [{ kind: 'EventsNode', event: 'signed_up' }],
                                      ...(shape === 'breakdown' ? { breakdownFilter: { breakdown: 'source' } } : {}),
                                      trendsFilter: { display: 'ActionsBar' },
                                  },
                              },
                    ...(shape === 'sql'
                        ? {
                              columns: ['day', 'Signups', 'Invites'],
                              types: [
                                  ['day', 'Date'],
                                  ['Signups', 'UInt64'],
                                  ['Invites', 'UInt64'],
                              ],
                          }
                        : {}),
                    result:
                        shape === 'sql'
                            ? [
                                  ['2026-10-19', 20, 5],
                                  ['2026-10-20', 30, 8],
                              ]
                            : [
                                  {
                                      label: 'Signups',
                                      action: { order: 0 },
                                      days: ['2026-10-19', '2026-10-20'],
                                      data: [20, 30],
                                      ...(shape === 'breakdown' ? { breakdown_value: 'direct' } : {}),
                                  },
                                  {
                                      label: 'Invites',
                                      action: { order: shape === 'series' ? 1 : 0 },
                                      days: ['2026-10-19', '2026-10-20'],
                                      data: [5, 8],
                                      ...(shape === 'breakdown' ? { breakdown_value: 'referral' } : {}),
                                  },
                              ],
                },
                undefined,
                { readAt: 1, serverNow: Date.now() }
            )
            expect(multi.capabilities).toMatchObject({ chart: true, number: false })
            jest.mocked(usePinData).mockReturnValue({ ...data, snapshot: multi })
            const shown = { ...pin, display: { ...pin.display, mode: 'chart' as const } }
            const screen = render(<PinCard pin={shown} index={0} demo={false} {...callbacks} />)
            expect(screen.queryByTestId('views-pin-value-dashboard-42')).toBeNull()
            const first = shape === 'breakdown' ? 'Signups · direct' : 'Signups'
            const second = shape === 'breakdown' ? 'Invites · referral' : 'Invites'
            expect(screen.getByLabelText(first).props.accessibilityState.checked).toBe(true)
            expect(screen.getByLabelText(second).props.accessibilityState.checked).toBe(true)
            fireEvent.press(screen.getByLabelText(second))
            expect(screen.getByLabelText(second).props.accessibilityState.checked).toBe(false)
        }
    )

    it('unpins the real shortcut when its metric is no longer accessible', () => {
        const shown = { ...pin, kind: 'insight' as const, ref: 'signups' }
        jest.mocked(usePinData).mockReturnValue({ ...data, snapshot: undefined, error: 'no_access' })
        const screen = render(<PinCard pin={shown} index={0} demo={false} {...callbacks} />)
        fireEvent.press(screen.getByLabelText('Unpin'))
        expect(callbacks.onUnpin).toHaveBeenCalledWith(shown)
        expect(callbacks.onUnpin.mock.calls[0]?.[0].shortcutId).toBe('real-shortcut')
    })
    it('lets a selected automatic mode become an explicit choice', () => {
        const onChange = jest.fn()
        const screen = render(
            <ModeSegment
                value="chart"
                available={['row', 'chart']}
                onChange={onChange}
                variant="icons"
                name="Product overview"
                testIDFor={(mode) => `mode-${mode}`}
            />
        )
        fireEvent.press(screen.getByTestId('mode-chart'))
        expect(onChange).toHaveBeenCalledWith('chart')
        expect(screen.getByTestId('mode-number').props.accessibilityState.disabled).toBe(true)
    })
})
