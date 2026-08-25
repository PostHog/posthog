import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { consumeGoalDraftIntent } from '../replay_scanners/goalDraftIntent'
import { ANALYSIS_NUDGE_THRESHOLD, analysisNudgeLogic } from './analysisNudgeLogic'

describe('analysisNudgeLogic', () => {
    let logic: ReturnType<typeof analysisNudgeLogic.build>
    let scannersSpy: jest.Mock

    const setFlagEnabled = (enabled: boolean): void => {
        featureFlagLogic.actions.setFeatureFlags(
            enabled ? [FEATURE_FLAGS.REPLAY_VISION_ANALYSIS_NUDGE] : [],
            enabled ? { [FEATURE_FLAGS.REPLAY_VISION_ANALYSIS_NUDGE]: true } : {}
        )
    }

    beforeEach(() => {
        // The suppression reducers persist to localStorage and the goal hand-off to
        // sessionStorage; isolate tests from each other.
        localStorage.clear()
        sessionStorage.clear()
        // Access control fails closed, and the shown capture is gated on scanner editor access.
        window.POSTHOG_APP_CONTEXT = {
            ...window.POSTHOG_APP_CONTEXT,
            resource_access_control: {
                [AccessControlResourceType.ReplayScanner]: AccessControlLevel.Editor,
                [AccessControlResourceType.SessionRecording]: AccessControlLevel.Editor,
            },
        } as any
        scannersSpy = jest.fn(() => [200, { count: 0, next: null, previous: null, results: [] }])
        useMocks({ get: { '/api/projects/:team/vision/scanners/': scannersSpy } })
        initKeaTests()
        teamLogic.mount()
        featureFlagLogic.mount()
        setFlagEnabled(true)
        logic = analysisNudgeLogic.build()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    const analyzeUpToThreshold = (): void => {
        for (let i = 0; i < ANALYSIS_NUDGE_THRESHOLD; i++) {
            logic.actions.recordingAnalyzed(`recording-${i}`)
        }
    }

    it('shows only after enough unique recordings, so re-watching one never triggers it', async () => {
        logic.actions.recordingAnalyzed('recording-0')
        logic.actions.recordingAnalyzed('recording-0')
        for (let i = 1; i < ANALYSIS_NUDGE_THRESHOLD - 1; i++) {
            logic.actions.recordingAnalyzed(`recording-${i}`)
        }
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.nudgeVisible).toBe(false)
        expect(scannersSpy).not.toHaveBeenCalled()

        await expectLogic(logic, () =>
            logic.actions.recordingAnalyzed(`recording-${ANALYSIS_NUDGE_THRESHOLD - 1}`)
        ).toDispatchActions(['checkTeamScannersSuccess'])
        expect(logic.values.nudgeVisible).toBe(true)
    })

    it('stays hidden past the threshold when the feature flag is off', async () => {
        setFlagEnabled(false)
        analyzeUpToThreshold()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.nudgeVisible).toBe(false)
    })

    it('stays hidden for a team already running scanners', async () => {
        scannersSpy.mockReturnValue([200, { count: 1, next: null, previous: null, results: [{ id: 'existing' }] }])
        await expectLogic(logic, analyzeUpToThreshold).toDispatchActions(['checkTeamScannersSuccess'])
        expect(logic.values.teamHasScanners).toBe(true)
        expect(logic.values.nudgeVisible).toBe(false)
    })

    it('captures shown once, not again for every further analyzed recording', async () => {
        const captureSpy = jest.spyOn(posthog, 'capture').mockImplementation(() => undefined as any)
        await expectLogic(logic, analyzeUpToThreshold).toDispatchActions(['checkTeamScannersSuccess'])
        logic.actions.recordingAnalyzed('recording-extra')
        await expectLogic(logic).toFinishAllListeners()
        const shownCalls = captureSpy.mock.calls.filter((call) => call[0] === 'replay vision analysis nudge shown')
        expect(shownCalls).toHaveLength(1)
    })

    it('a shown-but-ignored nudge stays hidden on the next mount, so ignoring is not re-pitched every session', async () => {
        await expectLogic(logic, analyzeUpToThreshold).toDispatchActions(['nudgeShown'])
        expect(logic.values.nudgeVisible).toBe(true)

        logic.unmount()
        logic = analysisNudgeLogic.build()
        logic.mount()
        analyzeUpToThreshold()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.nudgeVisible).toBe(false)
    })

    it.each([
        ['dismissing', () => logic.actions.dismissNudge()],
        ['submitting', () => logic.actions.submitGoal('find rage clicks')],
    ])('%s suppresses the nudge even as more recordings are analyzed', async (_name, act) => {
        analyzeUpToThreshold()
        act()
        logic.actions.recordingAnalyzed('recording-after')
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.suppressed).toBe(true)
        expect(logic.values.nudgeVisible).toBe(false)
    })

    it('submitting hands the goal to the creation wizard via sessionStorage, never the URL', () => {
        analyzeUpToThreshold()
        logic.actions.submitGoal('find rage clicks in checkout')
        expect(router.values.location.pathname).toContain(urls.replayVisionTemplates())
        expect(router.values.searchParams.goal).toBeUndefined()
        expect(consumeGoalDraftIntent()).toEqual('find rage clicks in checkout')
    })
})
