import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { symbolSetLogic } from './symbolSetLogic'

describe('symbolSetLogic', () => {
    let logic: ReturnType<typeof symbolSetLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team_id/error_tracking/symbol_sets': { count: 0, results: [] },
            },
        })
        initKeaTests()
        logic = symbolSetLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    // A control character in `search` fails DRF's `ProhibitNullCharactersValidator`, which rejects
    // the whole listing, so the reducer has to drop it before the request is built.
    it.each([
        ['app\u0000.js', 'app.js'],
        ['app\u001f.js', 'app.js'],
        ['app.js', 'app.js'],
    ])('strips control characters from %j', async (typed, expected) => {
        await expectLogic(logic, () => logic.actions.setSearchQuery(typed)).toMatchValues({
            searchQuery: expected,
        })
    })

    it('marks the listing as failed when it cannot load', async () => {
        useMocks({
            get: {
                '/api/environments/:team_id/error_tracking/symbol_sets': () => [400, { detail: 'Bad request' }],
            },
        })

        await expectLogic(logic, () => logic.actions.loadSymbolSets())
            .toDispatchActions(['loadSymbolSetsFailure'])
            .toMatchValues({ symbolSetsLoadFailed: true })

        useMocks({
            get: {
                '/api/environments/:team_id/error_tracking/symbol_sets': { count: 0, results: [] },
            },
        })

        await expectLogic(logic, () => logic.actions.loadSymbolSets())
            .toDispatchActions(['loadSymbolSetsSuccess'])
            .toMatchValues({ symbolSetsLoadFailed: false })
    })
})
