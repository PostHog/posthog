import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { highlightFeedGroupLogic } from './highlightFeedGroupLogic'

describe('highlightFeedGroupLogic', () => {
    let listSpy: jest.Mock

    beforeEach(() => {
        listSpy = jest.fn(() => [200, { count: 9, results: [{ id: 'card' }, { id: 'copy-1' }, { id: 'copy-2' }] }])
        useMocks({ get: { '/api/projects/:team/vision/scanners/:scanner/observations/': listSpy } })
        initKeaTests()
    })

    it('lists the group without the card it hangs under', async () => {
        const logic = highlightFeedGroupLogic({
            observationId: 'card',
            scannerId: 'scanner-a',
            dateFrom: '-30d',
            categories: 'failure',
        })
        logic.mount()
        expect(listSpy).not.toHaveBeenCalled()
        await expectLogic(logic, () => logic.actions.loadMembers()).toFinishAllListeners()
        const params = new URL(listSpy.mock.calls[0][0].request.url).searchParams
        expect([params.get('watch_group'), params.get('date_from'), params.get('watch_category')]).toEqual([
            'card',
            '-30d',
            'failure',
        ])
        expect(logic.values.members?.shown.map((member) => member.id)).toEqual(['copy-1', 'copy-2'])
        expect(logic.values.members?.total).toBe(8)
        logic.unmount()
    })
})
