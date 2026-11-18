import { errorQuery, loadingQuery, successQuery } from '@/model/queryStates'
import type { MetricView, QueryState } from '@/model/types'

import { metricValueState } from './metricValue'

const NOW = new Date('2026-10-13T12:00:00Z')
const FORMAT: MetricView['format'] = { valueFormat: 'count', unit: null }
const SNAPSHOT = { value: 3721, at: '2026-10-13T10:00:00Z', series: [1, 2] }
const SETTLED_EMPTY: QueryState<number> = { ...loadingQuery<number>(), isLoading: false }

describe('metricValueState', () => {
    test.each<[string, QueryState<number>, MetricView['snapshot'], ReturnType<typeof metricValueState>]>([
        ['the live value wins over the snapshot', successQuery(4100), SNAPSHOT, { kind: 'live', text: '4,100' }],
        [
            'an error falls back to the snapshot and says so',
            errorQuery(new Error('403')),
            SNAPSHOT,
            { kind: 'saved', text: '3,721', measured: 'Measured 2h ago', failed: true },
        ],
        [
            'no query (redacted) shows the snapshot',
            SETTLED_EMPTY,
            SNAPSHOT,
            { kind: 'saved', text: '3,721', measured: 'Measured 2h ago', failed: false },
        ],
        [
            'a snapshot with no time has no measured label',
            SETTLED_EMPTY,
            { ...SNAPSHOT, at: null },
            { kind: 'saved', text: '3,721', failed: false },
        ],
        ['loading without a snapshot shows a spinner', loadingQuery(), undefined, { kind: 'loading' }],
    ])('%s', (_name, aggregate, snapshot, expected) => {
        expect(metricValueState(aggregate, { format: FORMAT, snapshot }, NOW)).toEqual(expected)
    })

    test('an error with no snapshot offers a retry', () => {
        const refetch = jest.fn()
        const state = metricValueState(errorQuery(new Error('500'), refetch), { format: FORMAT }, NOW)
        expect(state).toMatchObject({ kind: 'missing', failed: true })
        if (state.kind === 'missing') {
            state.retry()
        }
        expect(refetch).toHaveBeenCalledTimes(1)
    })
})
