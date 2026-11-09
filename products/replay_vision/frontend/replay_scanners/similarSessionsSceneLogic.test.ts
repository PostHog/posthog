import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { similarSessionsSceneLogic, similarSessionsUrl } from './similarSessionsSceneLogic'

describe('similarSessionsSceneLogic', () => {
    let listSpy: jest.Mock

    beforeEach(() => {
        listSpy = jest.fn(() => [200, { count: 2, results: [{ id: 'card' }, { id: 'copy-1' }] }])
        useMocks({ get: { '/api/projects/:team/vision/scanners/:scanner/observations/': listSpy } })
        initKeaTests()
    })

    it('lists the group the feed card linked to, with the card scanner and the feed window', async () => {
        const logic = similarSessionsSceneLogic()
        logic.mount()
        router.actions.push(
            similarSessionsUrl({
                observationId: 'card',
                scannerId: 'scanner-a',
                dateFrom: '-30d',
                categories: 'failure,struggle',
            })
        )
        await expectLogic(logic).toFinishAllListeners()

        const url = new URL(listSpy.mock.calls[0][0].request.url)
        expect(url.pathname).toContain('/vision/scanners/scanner-a/observations/')
        expect([
            url.searchParams.get('watch_group'),
            url.searchParams.get('date_from'),
            url.searchParams.get('watch_category'),
        ]).toEqual(['card', '-30d', 'failure,struggle'])
        expect(logic.values.sessions?.results.map((session) => session.id)).toEqual(['card', 'copy-1'])
        logic.unmount()
    })
})
