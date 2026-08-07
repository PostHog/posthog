import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { exceptionIngestionLogic } from './exceptionIngestionLogic'

const EXISTS_PATH = '/api/environments/:team_id/error_tracking/issues/exists/'

describe('exceptionIngestionLogic', () => {
    let logic: ReturnType<typeof exceptionIngestionLogic.build>

    afterEach(() => logic?.unmount())

    it('records the confirmed no-events state as false', async () => {
        useMocks({ get: { [EXISTS_PATH]: { exists: false } } })
        initKeaTests()
        logic = exceptionIngestionLogic()
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadExceptionIngestionStateSuccess'])
        expect(logic.values.hasSentExceptionEvent).toBe(false)
    })

    it('leaves the state unknown (null) when the check fails instead of collapsing to false', async () => {
        // Guards the false "No exception events" banner: a 500/403/503 must not read as "no events".
        useMocks({ get: { [EXISTS_PATH]: () => [500] } })
        initKeaTests()
        logic = exceptionIngestionLogic()
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadExceptionIngestionStateFailure'])
        expect(logic.values.hasSentExceptionEvent).toBeNull()
    })
})
