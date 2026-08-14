import { router } from 'kea-router'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { ANALYSIS_NUDGE_THRESHOLD, analysisNudgeLogic } from './analysisNudgeLogic'

describe('analysisNudgeLogic', () => {
    let logic: ReturnType<typeof analysisNudgeLogic.build>

    const setFlagEnabled = (enabled: boolean): void => {
        featureFlagLogic.actions.setFeatureFlags(
            enabled ? [FEATURE_FLAGS.REPLAY_VISION_ANALYSIS_NUDGE] : [],
            enabled ? { [FEATURE_FLAGS.REPLAY_VISION_ANALYSIS_NUDGE]: true } : {}
        )
    }

    beforeEach(() => {
        // The suppression reducer persists to localStorage; isolate tests from each other.
        localStorage.clear()
        // Access control fails closed, and the shown capture is gated on scanner editor access.
        window.POSTHOG_APP_CONTEXT = {
            ...window.POSTHOG_APP_CONTEXT,
            resource_access_control: {
                [AccessControlResourceType.ReplayScanner]: AccessControlLevel.Editor,
                [AccessControlResourceType.SessionRecording]: AccessControlLevel.Editor,
            },
        } as any
        initKeaTests()
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

    it('shows only after enough unique recordings, so re-watching one never triggers it', () => {
        logic.actions.recordingAnalyzed('recording-0')
        logic.actions.recordingAnalyzed('recording-0')
        logic.actions.recordingAnalyzed('recording-1')
        expect(logic.values.nudgeVisible).toBe(false)
        logic.actions.recordingAnalyzed('recording-2')
        expect(logic.values.nudgeVisible).toBe(true)
    })

    it('stays hidden past the threshold when the feature flag is off', () => {
        setFlagEnabled(false)
        analyzeUpToThreshold()
        expect(logic.values.nudgeVisible).toBe(false)
    })

    it('captures shown once, not again for every further analyzed recording', () => {
        const captureSpy = jest.spyOn(posthog, 'capture').mockImplementation(() => undefined as any)
        analyzeUpToThreshold()
        logic.actions.recordingAnalyzed('recording-extra')
        const shownCalls = captureSpy.mock.calls.filter((call) => call[0] === 'replay vision analysis nudge shown')
        expect(shownCalls).toHaveLength(1)
    })

    it.each([
        ['dismissing', () => logic.actions.dismissNudge()],
        ['submitting', () => logic.actions.submitGoal('find rage clicks')],
    ])('%s suppresses the nudge even as more recordings are analyzed', (_name, act) => {
        analyzeUpToThreshold()
        act()
        logic.actions.recordingAnalyzed('recording-after')
        expect(logic.values.suppressed).toBe(true)
        expect(logic.values.nudgeVisible).toBe(false)
    })

    it('submitting hands the goal to the creation wizard via the goal search param', () => {
        analyzeUpToThreshold()
        logic.actions.submitGoal('find rage clicks in checkout')
        expect(router.values.location.pathname).toContain(urls.replayVisionTemplates())
        expect(router.values.searchParams.goal).toEqual('find rage clicks in checkout')
    })
})
