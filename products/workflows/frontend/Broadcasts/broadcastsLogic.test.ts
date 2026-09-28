import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { broadcastsLogic } from './broadcastsLogic'

describe('broadcastsLogic', () => {
    let logic: ReturnType<typeof broadcastsLogic.build>
    let patchedStatuses: string[]
    let releasePatch: () => void

    beforeEach(() => {
        patchedStatuses = []
        const patchReleased = new Promise<void>((resolve) => {
            releasePatch = resolve
        })
        useMocks({
            get: {
                '/api/projects/:team_id/hog_flows/': () => [200, { results: [], count: 0 }],
            },
            patch: {
                '/api/projects/:team_id/hog_flows/:id/': async ({ request }) => {
                    const { status } = (await request.json()) as { status: string }
                    patchedStatuses.push(status)
                    await patchReleased
                    return [200, {}]
                },
            },
        })
        initKeaTests()
        logic = broadcastsLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('sends one restore request when restore is clicked again while the first is in flight', async () => {
        const broadcast = { id: 'broadcast-1', name: 'Spring sale' }
        logic.actions.restoreBroadcast(broadcast)
        logic.actions.restoreBroadcast(broadcast)
        expect(logic.values.pendingBroadcastIds).toEqual({ 'broadcast-1': true })

        releasePatch()
        await expectLogic(logic).toDispatchActions([
            logic.actionCreators.setBroadcastPending('broadcast-1', false),
            'loadBroadcasts',
        ])
        expect(patchedStatuses).toEqual(['draft'])
        expect(logic.values.pendingBroadcastIds).toEqual({})
    })
})
