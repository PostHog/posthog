import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { productSetupStatusLogic } from 'lib/components/ProductEmptyState/productSetupStatusLogic'
import { recordingMetaJson } from 'scenes/session-recordings/__mocks__/recording_meta'

import { ProductKey } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import type { TeamType } from '~/types'

import { sessionReplaySetupLogic } from './sessionReplaySetupLogic'

describe('sessionReplaySetupLogic', () => {
    // Guards the three-state mapping the scene gate hangs off: recordings must
    // outrank the toggle (turning recording off keeps old recordings, and this
    // scene is the only place to watch them), and opt-in without recordings must
    // read as waiting, not as "install".
    it.each([
        [true, false, 'has-data'],
        [true, true, 'has-data'],
        [false, true, 'waiting-for-data'],
        [false, false, 'needs-setup'],
    ])('recordings=%s, optIn=%s maps to %s', async (hasRecordings, optIn, expected) => {
        initKeaTests(true, { ...MOCK_DEFAULT_TEAM, session_recording_opt_in: optIn } as TeamType)
        jest.spyOn(api.recordings, 'list').mockResolvedValue({
            results: hasRecordings ? [recordingMetaJson] : [],
            has_next: false,
        })
        sessionReplaySetupLogic.mount()
        await expectLogic(sessionReplaySetupLogic).toFinishAllListeners()
        expect(productSetupStatusLogic({ productKey: ProductKey.SESSION_REPLAY }).values.status).toBe(expected)
    })

    // Without an explicit range the list falls back to the last 3 days, so a project whose newest
    // recording is older than that reads as "nothing captured" and loses the scene to the gate.
    it.each([
        ['30d', '-30d'],
        ['1y', '-1y'],
        ['legacy', '-90d'],
        [null, '-90d'],
    ])('retention %s probes back to %s', async (period, expected) => {
        initKeaTests(true, { ...MOCK_DEFAULT_TEAM, session_recording_retention_period: period } as TeamType)
        const list = jest.spyOn(api.recordings, 'list').mockResolvedValue({ results: [], has_next: false })
        sessionReplaySetupLogic.mount()
        await expectLogic(sessionReplaySetupLogic).toFinishAllListeners()
        expect(list).toHaveBeenCalledWith(expect.objectContaining({ date_from: expected }))
    })
})
