import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { watchFeedGroupLogic } from './watchFeedGroupLogic'

describe('watchFeedGroupLogic', () => {
    let listSpy: jest.Mock

    beforeEach(() => {
        listSpy = jest.fn(() => [200, { count: 9, results: [{ id: 'card' }, { id: 'copy-1' }, { id: 'copy-2' }] }])
        useMocks({ get: { '/api/projects/:team/vision/scanners/:scanner/observations/': listSpy } })
        initKeaTests()
    })

    it('loads the group once on first expand, without the card it hangs under', async () => {
        const logic = watchFeedGroupLogic({ observationId: 'card', scannerId: 'scanner-a', dateFrom: '-30d' })
        logic.mount()
        expect(listSpy).not.toHaveBeenCalled()

        await expectLogic(logic, () => logic.actions.toggleExpanded()).toFinishAllListeners()
        const params = new URL(listSpy.mock.calls[0][0].request.url).searchParams
        expect([params.get('watch_group'), params.get('date_from')]).toEqual(['card', '-30d'])
        expect(logic.values.members?.shown.map((member) => member.id)).toEqual(['copy-1', 'copy-2'])
        expect(logic.values.members?.total).toBe(8)

        logic.actions.toggleExpanded()
        await expectLogic(logic, () => logic.actions.toggleExpanded()).toFinishAllListeners()
        expect(listSpy).toHaveBeenCalledTimes(1)
        logic.unmount()
    })
})
