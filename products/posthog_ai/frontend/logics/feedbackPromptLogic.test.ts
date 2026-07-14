import { expectLogic } from 'kea-test-utils'

import * as featureFlagLogic from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'

import { feedbackPromptLogic } from './feedbackPromptLogic'

const MOCK_STREAM_KEY = 'test-run-123'
const MOCK_SESSION_ID = 'test-session-123'
const STORAGE_KEY = 'posthog_ai_run_feedback_last_shown'

const DEFAULT_CONFIG = {
    cooldownMs: 86400000, // 24 hours
    messageInterval: 10,
    samplingRate: 0.05,
    retryThreshold: 2,
    cancelThreshold: 3,
}

describe('feedbackPromptLogic', () => {
    let logic: ReturnType<typeof feedbackPromptLogic.build>

    beforeEach(() => {
        initKeaTests()
        localStorage.clear()

        jest.spyOn(featureFlagLogic, 'getFeatureFlagPayload').mockReturnValue(DEFAULT_CONFIG)

        logic = feedbackPromptLogic({ streamKey: MOCK_STREAM_KEY, sessionId: MOCK_SESSION_ID })
        logic.mount()
    })

    afterEach(() => {
        logic?.unmount()
        jest.restoreAllMocks()
        localStorage.clear()
    })

    describe('checkShouldShowPrompt', () => {
        it('does not show prompt when config is not available', async () => {
            jest.spyOn(featureFlagLogic, 'getFeatureFlagPayload').mockReturnValue(null)

            await expectLogic(logic, () => {
                logic.actions.checkShouldShowPrompt(10)
            }).toMatchValues({
                isPromptVisible: false,
            })
        })

        it('does not show prompt when already visible', async () => {
            logic.actions.showPrompt('manual')

            await expectLogic(logic, () => {
                logic.actions.checkShouldShowPrompt(10)
            }).toMatchValues({
                isPromptVisible: true,
                currentTriggerType: 'manual', // Should not change
            })
        })

        it('does not show prompt when cooldown is active', async () => {
            localStorage.setItem(STORAGE_KEY, Date.now().toString())

            await expectLogic(logic, () => {
                logic.actions.checkShouldShowPrompt(10)
            }).toMatchValues({
                isPromptVisible: false,
            })
        })

        it('shows prompt with message_interval trigger at correct intervals', async () => {
            await expectLogic(logic, () => {
                logic.actions.checkShouldShowPrompt(10)
            }).toMatchValues({
                isPromptVisible: true,
                currentTriggerType: 'message_interval',
                lastTriggeredIntervalIndex: 1,
            })
        })

        it('does not trigger message_interval twice for same interval', async () => {
            // Avoid the random-sampling trigger
            jest.spyOn(Math, 'random').mockReturnValue(0.9)

            logic.actions.checkShouldShowPrompt(10)
            expect(logic.values.isPromptVisible).toBe(true)
            expect(logic.values.lastTriggeredIntervalIndex).toBe(1)

            logic.actions.hidePrompt()

            await expectLogic(logic, () => {
                logic.actions.checkShouldShowPrompt(10)
            }).toMatchValues({
                isPromptVisible: false,
                lastTriggeredIntervalIndex: 1,
            })
        })

        it('triggers message_interval at next interval', async () => {
            jest.spyOn(Math, 'random').mockReturnValue(0.9)

            logic.actions.checkShouldShowPrompt(10)
            logic.actions.hidePrompt()

            await expectLogic(logic, () => {
                logic.actions.checkShouldShowPrompt(20)
            }).toMatchValues({
                isPromptVisible: true,
                currentTriggerType: 'message_interval',
                lastTriggeredIntervalIndex: 2,
            })
        })

        it('does not show prompt when message count is not at interval', async () => {
            jest.spyOn(Math, 'random').mockReturnValue(0.9)

            await expectLogic(logic, () => {
                logic.actions.checkShouldShowPrompt(7)
            }).toMatchValues({
                isPromptVisible: false,
            })
        })
    })

    describe('showPrompt and hidePrompt', () => {
        it('hidePrompt resets visibility and trigger type', async () => {
            logic.actions.showPrompt('message_interval')

            await expectLogic(logic, () => {
                logic.actions.hidePrompt()
            }).toMatchValues({
                isPromptVisible: false,
                currentTriggerType: 'manual',
            })
        })
    })

    describe('recordFeedbackShown', () => {
        it('sets localStorage timestamp', async () => {
            const beforeTime = Date.now()

            await expectLogic(logic, () => {
                logic.actions.recordFeedbackShown()
            })

            const storedTime = parseInt(localStorage.getItem(STORAGE_KEY) || '0', 10)
            expect(storedTime).toBeGreaterThanOrEqual(beforeTime)
            expect(storedTime).toBeLessThanOrEqual(Date.now())
        })
    })

    describe('canShowPrompt selector', () => {
        it('returns true when no cooldown is active', () => {
            expect(logic.values.canShowPrompt).toBe(true)
        })

        it('returns false when cooldown is active', () => {
            localStorage.setItem(STORAGE_KEY, Date.now().toString())

            // Remount to pick up the new localStorage value (selector reads it at build time)
            logic.unmount()
            logic = feedbackPromptLogic({ streamKey: MOCK_STREAM_KEY, sessionId: MOCK_SESSION_ID })
            logic.mount()

            expect(logic.values.canShowPrompt).toBe(false)
        })

        it('returns false when config is not available', () => {
            jest.spyOn(featureFlagLogic, 'getFeatureFlagPayload').mockReturnValue(null)

            logic.unmount()
            logic = feedbackPromptLogic({ streamKey: MOCK_STREAM_KEY, sessionId: MOCK_SESSION_ID })
            logic.mount()

            expect(logic.values.canShowPrompt).toBe(false)
        })
    })

    describe('per-run isolation', () => {
        it('maintains separate state for different runs', () => {
            const logic1 = feedbackPromptLogic({ streamKey: 'run-1', sessionId: 'run-1' })
            const logic2 = feedbackPromptLogic({ streamKey: 'run-2', sessionId: 'run-2' })

            logic1.mount()
            logic2.mount()

            logic1.actions.showPrompt('message_interval')
            logic1.actions.setLastTriggeredIntervalIndex(3)

            expect(logic1.values.isPromptVisible).toBe(true)
            expect(logic1.values.lastTriggeredIntervalIndex).toBe(3)

            expect(logic2.values.isPromptVisible).toBe(false)
            expect(logic2.values.lastTriggeredIntervalIndex).toBe(0)

            logic1.unmount()
            logic2.unmount()
        })
    })
})
