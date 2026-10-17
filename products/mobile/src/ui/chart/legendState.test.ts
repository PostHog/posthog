import { type LegendChange, type LegendState, soloSeries, toggleSeries } from './legendState'
import type { ChartSeries } from './types'

const series: ChartSeries[] = [
    { key: 'ios', label: 'iOS', color: '#1D4AFF', points: [] },
    { key: 'web', label: 'Web', color: '#621DA6', points: [] },
    { key: 'ios-previous', label: 'Previous period', color: '#1D4AFF', compareOf: 'ios', points: [] },
]

describe('legendState', () => {
    test.each<[string, 'tap' | 'hold', LegendState, string, LegendChange | null]>([
        [
            'a tap hides a series',
            'tap',
            { hiddenKeys: [], soloKey: null },
            'ios',
            { state: { hiddenKeys: ['ios'], soloKey: null }, action: 'toggle' },
        ],
        ['a tap never hides the last current series', 'tap', { hiddenKeys: ['ios'], soloKey: null }, 'web', null],
        [
            'a tap on the solo series shows every series again',
            'tap',
            { hiddenKeys: ['web', 'ios-previous'], soloKey: 'ios' },
            'ios',
            { state: { hiddenKeys: [], soloKey: null }, action: 'restore' },
        ],
        [
            'a hold shows only that series',
            'hold',
            { hiddenKeys: [], soloKey: null },
            'web',
            { state: { hiddenKeys: ['ios', 'ios-previous'], soloKey: 'web' }, action: 'solo' },
        ],
        [
            'a hold on the previous period acts as a tap',
            'hold',
            { hiddenKeys: [], soloKey: null },
            'ios-previous',
            { state: { hiddenKeys: ['ios-previous'], soloKey: null }, action: 'toggle' },
        ],
    ])('%s', (_, gesture, state, key, expected) => {
        const change = gesture === 'tap' ? toggleSeries(series, state, key) : soloSeries(series, state, key)
        expect(change).toEqual(expected)
    })
})
