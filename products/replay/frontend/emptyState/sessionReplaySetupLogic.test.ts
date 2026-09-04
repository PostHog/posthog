import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { productSetupStatusLogic } from 'lib/components/ProductEmptyState/productSetupStatusLogic'
import { recordingMetaJson } from 'scenes/session-recordings/__mocks__/recording_meta'

import { useMocks } from '~/mocks/jest'
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
    // `ingestedEvent` is the value the page booted with and `serverIngestedEvent` is
    // what a re-read of the team reports, which is the only way this screen learns
    // that the first event landed while it stayed open.
    it.each([
        [true, false, true, true, 'has-data'],
        [true, true, false, false, 'has-data'],
        [false, true, true, true, 'waiting-for-data'],
        [false, true, false, false, 'no-events'],
        [false, true, false, true, 'waiting-for-data'],
        [false, false, false, false, 'needs-setup'],
    ])(
        'recordings=%s, optIn=%s, ingestedEvent=%s, serverIngestedEvent=%s maps to %s',
        async (hasRecordings, optIn, ingestedEvent, serverIngestedEvent, expected) => {
            const team = { ...MOCK_DEFAULT_TEAM, session_recording_opt_in: optIn, ingested_event: ingestedEvent }
            useMocks({
                get: { '/api/environments/@current/': { ...team, ingested_event: serverIngestedEvent } },
            })
            initKeaTests(true, team as TeamType)
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
