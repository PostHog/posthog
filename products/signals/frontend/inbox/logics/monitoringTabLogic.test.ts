/* oxlint-disable react-hooks/rules-of-hooks -- useMocks is a test helper. */
import { waitFor } from '@testing-library/react'
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { monitoringTabLogic } from './monitoringTabLogic'

const REPORTS_URL = '/api/projects/:team_id/signals/reports/'

const page = (ids: string[], next: string | null = null): Record<string, unknown> => ({
    count: ids.length,
    next,
    previous: null,
    results: ids.map((id) => ({ id, metrics: [], monitoring_summary: null, monitoring_outcome: null })),
})

describe('monitoringTabLogic', () => {
    let logic: ReturnType<typeof monitoringTabLogic.build>

    beforeEach(() => {
        localStorage.clear()
        initKeaTests()
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('keeps the newer scope page when a request for the previous scope fails after it', async () => {
        let failConnected: () => void = () => {}
        const requested: (string | null)[] = []
        useMocks({
            get: {
                [REPORTS_URL]: async ({ request }) => {
                    const connected = new URL(request.url).searchParams.get('connected')
                    requested.push(connected)
                    if (connected) {
                        await new Promise<void>((resolve) => (failConnected = resolve))
                        return [500, { detail: 'boom' }]
                    }
                    return [200, page(['everyone-report'])]
                },
            },
        })
        logic = monitoringTabLogic()
        logic.mount()
        await waitFor(() => expect(requested).toEqual(['assigned,suggested_reviewer']))

        logic.actions.setScope({ everyone: true, connections: [] })
        expect(logic.values.page).toBeNull()
        await waitFor(() => expect(logic.values.page?.results.map((r) => r.id)).toEqual(['everyone-report']))
        failConnected()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.loadFailed).toBe(false)
        expect(logic.values.page?.results.map((r) => r.id)).toEqual(['everyone-report'])
    })

    it('appends the next page without repeating rows', async () => {
        useMocks({
            get: {
                [REPORTS_URL]: ({ request }) => {
                    const offset = Number(new URL(request.url).searchParams.get('offset') ?? 0)
                    return [200, offset === 0 ? { ...page(['a', 'b'], 'next'), count: 3 } : page(['b', 'c'])]
                },
            },
        })
        logic = monitoringTabLogic()
        await expectLogic(logic, () => {
            logic.mount()
        }).toFinishAllListeners()
        expect(logic.values.page?.hasMore).toBe(true)

        await expectLogic(logic, () => logic.actions.loadMore()).toFinishAllListeners()

        expect(logic.values.page?.results.map((r) => r.id)).toEqual(['a', 'b', 'c'])
        expect(logic.values.page?.hasMore).toBe(false)
    })
})
