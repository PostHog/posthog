import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { observationShareLogic } from './observationShareLogic'

describe('observationShareLogic', () => {
    let logic: ReturnType<typeof observationShareLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = observationShareLogic({ observationId: 'obs-1', seconds: 95 })
        logic.mount()
    })

    afterEach(() => {
        logic?.unmount()
    })

    // The point of the feature: the link opens the observation page, not the bare recording, and the
    // recording inside it starts where the sharer was watching.
    it('links to the observation page at the current player time', () => {
        expect(logic.values.time).toBe('01:35')
        expect(logic.values.shareUrl).toContain('/replay-vision/observations/obs-1?t=95')
    })

    it('drops the timestamp when the sharer opts out', async () => {
        await expectLogic(logic, () => logic.actions.setIncludeTime(false)).toMatchValues({
            shareUrl: expect.not.stringContaining('t='),
        })
    })

    it('rejects a time it cannot turn into seconds', async () => {
        await expectLogic(logic, () => logic.actions.setTime('halfway')).toMatchValues({
            timeError: expect.stringContaining('valid time'),
        })
    })
})
