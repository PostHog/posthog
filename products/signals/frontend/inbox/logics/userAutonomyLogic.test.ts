/* oxlint-disable react-hooks/rules-of-hooks -- useMocks is a test helper, not a React hook */
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { userAutonomyLogic } from './userAutonomyLogic'

const ENDPOINT = '/api/users/@me/signal_autonomy/'

describe('userAutonomyLogic', () => {
    let logic: ReturnType<typeof userAutonomyLogic.build>

    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => logic?.unmount())

    test.each([
        ['an auth failure', [401, { detail: 'Authentication credentials were not provided.' }]],
        ['a scope failure', [403, { detail: 'API key missing required scope' }]],
        ['a server error', [500, { detail: 'Server error' }]],
    ])('degrades %s on the first load to no config without a failure', async (_, response) => {
        useMocks({ get: { [ENDPOINT]: () => response } })
        logic = userAutonomyLogic()

        await expectLogic(logic, () => {
            logic.mount()
        })
            .toDispatchActions(['loadAutonomyConfigSuccess'])
            .toNotHaveDispatchedActions(['loadAutonomyConfigFailure'])
            .toMatchValues({ autonomyConfig: null })
    })

    it('keeps the loaded config when a reload fails', async () => {
        const saved = { autostart_priority: 'P1', github_assign_on_pull_request: true }
        useMocks({ get: { [ENDPOINT]: () => [200, saved] } })
        logic = userAutonomyLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadAutonomyConfigSuccess']).toMatchValues({
            autonomyConfig: saved,
        })

        useMocks({ get: { [ENDPOINT]: () => [500, { detail: 'Server error' }] } })
        await expectLogic(logic, () => logic.actions.loadAutonomyConfig())
            .toDispatchActions(['loadAutonomyConfigSuccess'])
            .toNotHaveDispatchedActions(['loadAutonomyConfigFailure'])
            .toMatchValues({ autonomyConfig: saved })
    })
})
