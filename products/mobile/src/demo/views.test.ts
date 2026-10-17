import { insightDisplay, insightRenderState } from '@/features/views/snapshotChart'
import { insightSnapshot } from '@/model/adapters/insightSnapshot'

import { DEMO_DASHBOARD_SQL, demoDashboardResponse } from './views'

jest.mock('@react-native-async-storage/async-storage', () =>
    require('@react-native-async-storage/async-storage/jest/async-storage-mock')
)

const ANCHOR = Date.parse('2026-10-14T12:00:00Z')

describe('demo views', () => {
    test('draws every tile of the SQL dashboard on the phone', () => {
        const dashboard = demoDashboardResponse(DEMO_DASHBOARD_SQL, null, ANCHOR, () => undefined)

        const tiles = (dashboard?.tiles ?? []).map((tile) => {
            const snapshot = tile.insight
                ? insightSnapshot(tile.insight, undefined, { readAt: ANCHOR, serverNow: ANCHOR })
                : undefined
            return snapshot && [snapshot.name, insightDisplay(snapshot), insightRenderState(snapshot)]
        })

        expect(tiles).toEqual([
            ['Top pages this week', 'table', 'ready'],
            ['Signups vs activations by day', 'chart', 'ready'],
            ['Revenue by plan', 'bars', 'ready'],
            ['Paying accounts', 'number', 'ready'],
            ['Signups by country', 'table', 'ready'],
        ])
    })
})
