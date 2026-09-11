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

    // `t=0` is not "no timestamp": it force-expands the recording on the reader's page and seeks to the
    // start, so an emptied field has to drop the param rather than fall back to zero.
    it('drops the timestamp when the time field is emptied', async () => {
        await expectLogic(logic, () => logic.actions.setTime('')).toMatchValues({
            shareUrl: expect.not.stringContaining('t='),
        })
    })

    it('keeps a deliberate 00:00 as a shared start', async () => {
        await expectLogic(logic, () => logic.actions.setTime('00:00')).toMatchValues({
            shareUrl: expect.stringContaining('?t=0'),
        })
    })

    it('rejects a time it cannot turn into seconds', async () => {
        await expectLogic(logic, () => logic.actions.setTime('halfway')).toMatchValues({
            timeError: expect.stringContaining('valid time'),
        })
    })
})
