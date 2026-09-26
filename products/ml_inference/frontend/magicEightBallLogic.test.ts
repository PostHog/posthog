import { initKeaTests } from '~/test/init'

import { MAX_OPTIONS_PER_QUESTION } from './decisionPlaygroundLogic'
import {
    ANSWER_QUESTION_ID,
    EIGHT_BALL_ANSWERS,
    buildEightBallRequest,
    magicEightBallLogic,
} from './magicEightBallLogic'

describe('magicEightBallLogic', () => {
    it('fits inside the decision model option limit', () => {
        expect(Object.keys(EIGHT_BALL_ANSWERS).length).toBeLessThanOrEqual(MAX_OPTIONS_PER_QUESTION)
    })

    it('asks one choice question about the trimmed product question', () => {
        const request = buildEightBallRequest('  Will the new onboarding lift activation?  ')

        expect(request.state).toBe('Will the new onboarding lift activation?')
        expect(Object.keys(request.questions)).toEqual([ANSWER_QUESTION_ID])
    })

    describe('motion permission', () => {
        const originalDeviceMotionEvent = Object.getOwnPropertyDescriptor(window, 'DeviceMotionEvent')

        afterEach(() => {
            if (originalDeviceMotionEvent) {
                Object.defineProperty(window, 'DeviceMotionEvent', originalDeviceMotionEvent)
            } else {
                delete (window as { DeviceMotionEvent?: unknown }).DeviceMotionEvent
            }
        })

        it.each([
            ['granted', true, (): Promise<string> => Promise.resolve('granted')],
            ['denied', false, (): Promise<string> => Promise.resolve('denied')],
            ['rejected', false, (): Promise<string> => Promise.reject(new Error('not from a tap'))],
        ])('turns a %s permission request into motionAllowed %s', async (_, expected, requestPermission) => {
            Object.defineProperty(window, 'DeviceMotionEvent', {
                value: { requestPermission },
                configurable: true,
                writable: true,
            })
            initKeaTests()
            const logic = magicEightBallLogic()
            logic.mount()
            expect(logic.values.motionAllowed).toBe(false)

            await logic.asyncActions.requestMotionPermission()

            expect(logic.values.motionAllowed).toBe(expected)
        })
    })
})
