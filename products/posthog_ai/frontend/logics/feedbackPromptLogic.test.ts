import { expectLogic } from 'kea-test-utils'

import * as featureFlagLogic from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'

import { feedbackPromptLogic } from './feedbackPromptLogic'
import { runStreamLogic } from './runStreamLogic'

const PROPS = { sessionId: 'session-1', streamKey: 'stream-1' }

const DEFAULT_CONFIG = {
    cooldownMs: 86400000,
    messageInterval: 10,
    samplingRate: 0.05,
    retryThreshold: 2,
    cancelThreshold: 3,
}

describe('feedbackPromptLogic (sandbox)', () => {
    let logic: ReturnType<typeof feedbackPromptLogic.build>

    beforeEach(() => {
        initKeaTests()
        localStorage.clear()
        jest.spyOn(featureFlagLogic, 'getFeatureFlagPayload').mockReturnValue(DEFAULT_CONFIG)
        // Sampling would otherwise fire nondeterministically on every check.
        jest.spyOn(Math, 'random').mockReturnValue(0.9)
        logic = feedbackPromptLogic(PROPS)
        logic.mount()
    })

    afterEach(() => {
        logic?.unmount()
        jest.restoreAllMocks()
        localStorage.clear()
    })

    describe('checkShouldShowPrompt', () => {
        it.each([
            ['no config', () => jest.spyOn(featureFlagLogic, 'getFeatureFlagPayload').mockReturnValue(null), 10],
            [
                'cooldown active',
                () => localStorage.setItem('posthog_ai_feedback_last_shown', Date.now().toString()),
                10,
            ],
            ['message count off the interval', () => {}, 7],
        ])('does not show the prompt with %s', async (_, arrange, messageCount) => {
            arrange()
            await expectLogic(logic, () => {
                logic.actions.checkShouldShowPrompt(messageCount)
            }).toMatchValues({ isPromptVisible: false })
        })

        it('does not change an already visible prompt', async () => {
            logic.actions.showPrompt('manual')
            await expectLogic(logic, () => {
                logic.actions.checkShouldShowPrompt(10)
            }).toMatchValues({ isPromptVisible: true, currentTriggerType: 'manual' })
        })

        it('triggers on the message interval once per interval, then again at the next', async () => {
            await expectLogic(logic, () => {
                logic.actions.checkShouldShowPrompt(10)
            }).toMatchValues({
                isPromptVisible: true,
                currentTriggerType: 'message_interval',
                lastTriggeredIntervalIndex: 1,
            })

            logic.actions.hidePrompt()
            await expectLogic(logic, () => {
                logic.actions.checkShouldShowPrompt(10)
            }).toMatchValues({ isPromptVisible: false, lastTriggeredIntervalIndex: 1 })

            await expectLogic(logic, () => {
                logic.actions.checkShouldShowPrompt(20)
            }).toMatchValues({
                isPromptVisible: true,
                currentTriggerType: 'message_interval',
                lastTriggeredIntervalIndex: 2,
            })
        })

        it('counts cancelled runs from the bound stream and triggers at the threshold', async () => {
            const stream = runStreamLogic({ streamKey: PROPS.streamKey })
            stream.mount()
            stream.actions.cancelRun()
            stream.actions.cancelRun()
            stream.actions.cancelRun()

            await expectLogic(logic, () => {
                logic.actions.checkShouldShowPrompt(5)
            }).toMatchValues({ cancelCount: 3, isPromptVisible: true, currentTriggerType: 'cancel' })
            stream.unmount()
        })

        it('triggers on random sampling when nothing else does', async () => {
            jest.spyOn(Math, 'random').mockReturnValue(0.01)
            await expectLogic(logic, () => {
                logic.actions.checkShouldShowPrompt(3)
            }).toMatchValues({ isPromptVisible: true, currentTriggerType: 'random_sample' })
        })
    })

    it('records the cooldown timestamp when feedback is shown', () => {
        const before = Date.now()
        logic.actions.recordFeedbackShown()
        const stored = parseInt(localStorage.getItem('posthog_ai_feedback_last_shown') || '0', 10)
        expect(stored).toBeGreaterThanOrEqual(before)
    })

    it('keeps state separate per session', () => {
        const other = feedbackPromptLogic({ sessionId: 'session-2', streamKey: 'stream-2' })
        other.mount()
        logic.actions.showPrompt('cancel')
        expect(logic.values.isPromptVisible).toBe(true)
        expect(other.values.isPromptVisible).toBe(false)
        other.unmount()
    })
})
