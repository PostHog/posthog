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
    // Guards the state mapping the scene gate hangs off: recordings must outrank
    // the toggle (turning recording off keeps old recordings, and this scene is the
    // only place to watch them), opt-in without recordings must read as waiting, not
    // as "install", and a project that never ingested an event must read as
    // no-events, because waiting for a session it cannot receive is a dead end.
    it.each([
        [true, false, true, 'has-data'],
        [true, true, false, 'has-data'],
        [false, true, true, 'waiting-for-data'],
        [false, true, false, 'no-events'],
        [false, false, false, 'needs-setup'],
    ])(
        'recordings=%s, optIn=%s, ingestedEvent=%s maps to %s',
        async (hasRecordings, optIn, ingestedEvent, expected) => {
            initKeaTests(true, {
                ...MOCK_DEFAULT_TEAM,
                session_recording_opt_in: optIn,
                ingested_event: ingestedEvent,
            } as TeamType)
            jest.spyOn(api.recordings, 'list').mockResolvedValue({
                results: hasRecordings ? [recordingMetaJson] : [],
                has_next: false,
            })
            sessionReplaySetupLogic.mount()
            await expectLogic(sessionReplaySetupLogic).toFinishAllListeners()
            expect(productSetupStatusLogic({ productKey: ProductKey.SESSION_REPLAY }).values.status).toBe(expected)
        }
    )
})
