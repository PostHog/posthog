import { expectLogic } from 'kea-test-utils'

import { ApiError } from 'lib/api-error'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { projectLogic } from 'scenes/projectLogic'

import { initKeaTests } from '~/test/init'

import { wizardSessionsLatestRetrieve } from './generated/api'
import type { WizardSessionDTOApi } from './generated/api.schemas'
import { wizardSessionStreamLogic } from './wizardSessionStreamLogic'

jest.mock('./generated/api', () => ({
    wizardSessionsLatestRetrieve: jest.fn(),
    getWizardSessionsStreamRetrieveUrl: jest.fn(() => '/mock-stream-url'),
}))

const mockLatestRetrieve = wizardSessionsLatestRetrieve as jest.Mock

function makeSession(overrides: Partial<WizardSessionDTOApi> = {}): WizardSessionDTOApi {
    return {
        session_id: 'sess-1',
        team_id: 997,
        workflow_id: 'posthog-integration',
        skill_id: 'install',
        started_at: '2026-01-01T00:00:00Z',
        run_phase: 'running',
        tasks: [],
        event_plan: null,
        error: null,
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
        is_stale: false,
        ...overrides,
    }
}

// Max jittered gap for the default 3s interval is 3.6s — advancing past it guarantees the next tick.
const PAST_MAX_JITTERED_INTERVAL_MS = 4000

describe('wizardSessionStreamLogic polling mode', () => {
    let logic: ReturnType<typeof wizardSessionStreamLogic.build>

    beforeEach(async () => {
        initKeaTests()
        mockLatestRetrieve.mockReset()
        logic = wizardSessionStreamLogic({ workflowId: 'posthog-integration' })
        logic.mount()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.ONBOARDING_WIZARD_SYNC_MODE], {
            [FEATURE_FLAGS.ONBOARDING_WIZARD_SYNC_MODE]: 'polling',
        })
        // connect() no-ops into an error without a project — wait for the test bootstrap to provide one.
        await expectLogic(projectLogic).toMatchValues({ currentProjectId: expect.any(Number) })
        jest.useFakeTimers()
    })

    afterEach(() => {
        logic?.unmount()
        jest.useRealTimers()
    })

    it('polls the latest session and feeds it through sessionUpdated', async () => {
        const session = makeSession()
        mockLatestRetrieve.mockResolvedValue(session)

        logic.actions.connect()
        await expectLogic(logic)
            .toDispatchActions(['connectionOpened', 'sessionUpdated'])
            .toMatchValues({ latestSession: session, connectionStatus: 'open' })

        expect(mockLatestRetrieve).toHaveBeenCalledWith(
            expect.any(String),
            {
                workflow_id: 'posthog-integration',
                skill_id: undefined,
            },
            { headers: { 'X-Wizard-Poll-Source': 'transport' } }
        )
    })

    it('keeps polling through a 204 (no session yet) without clobbering latestSession', async () => {
        // The generated client resolves an empty 204 body to null (getJSONOrNull), not undefined.
        mockLatestRetrieve.mockResolvedValue(null)

        logic.actions.connect()
        await expectLogic(logic)
            .toDispatchActions(['connectionOpened'])
            .toNotHaveDispatchedActions(['sessionUpdated'])
            .toMatchValues({ latestSession: null, connectionStatus: 'open' })

        jest.advanceTimersByTime(PAST_MAX_JITTERED_INTERVAL_MS)
        await Promise.resolve()
        expect(mockLatestRetrieve).toHaveBeenCalledTimes(2)
    })

    it('stops polling on disconnect', async () => {
        mockLatestRetrieve.mockResolvedValue(makeSession())

        logic.actions.connect()
        await expectLogic(logic).toDispatchActions(['sessionUpdated'])
        expect(mockLatestRetrieve).toHaveBeenCalledTimes(1)

        logic.actions.disconnect()
        jest.advanceTimersByTime(PAST_MAX_JITTERED_INTERVAL_MS)
        await Promise.resolve()
        expect(mockLatestRetrieve).toHaveBeenCalledTimes(1)
    })

    it('stops polling permanently on a 404', async () => {
        mockLatestRetrieve.mockRejectedValue(new ApiError('not found', 404))

        logic.actions.connect()
        await expectLogic(logic).toDispatchActions(['connectionErrored']).toMatchValues({ connectionStatus: 'error' })
        expect(mockLatestRetrieve).toHaveBeenCalledTimes(1)

        jest.advanceTimersByTime(10 * PAST_MAX_JITTERED_INTERVAL_MS)
        await Promise.resolve()
        expect(mockLatestRetrieve).toHaveBeenCalledTimes(1)
    })

    it('backs off after a transient error instead of retrying at full cadence', async () => {
        mockLatestRetrieve.mockRejectedValueOnce(new Error('network hiccup')).mockResolvedValue(makeSession())

        logic.actions.connect()
        await expectLogic(logic).toDispatchActions(['connectionErrored'])
        expect(mockLatestRetrieve).toHaveBeenCalledTimes(1)

        // One failure doubles the 3s base to 6s (±20% jitter → at least 4.8s): the base window
        // must NOT produce a retry...
        jest.advanceTimersByTime(PAST_MAX_JITTERED_INTERVAL_MS)
        await Promise.resolve()
        expect(mockLatestRetrieve).toHaveBeenCalledTimes(1)

        // ...but the backed-off window must.
        jest.advanceTimersByTime(PAST_MAX_JITTERED_INTERVAL_MS)
        await expectLogic(logic).toDispatchActions(['sessionUpdated'])
        expect(mockLatestRetrieve).toHaveBeenCalledTimes(2)
    })
})
