import { useMocks } from '~/mocks/jest'
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

    it('hides the previous answer when the question changes', async () => {
        useMocks({
            post: {
                '/api/projects/:team_id/ml_inference/decisions/decide/': () => [
                    200,
                    {
                        model: 'jevk5',
                        answers: {
                            [ANSWER_QUESTION_ID]: {
                                type: 'choice',
                                probability: null,
                                choice: 'Yes',
                                score: null,
                                confidence: 0.9,
                                probabilities: null,
                            },
                        },
                        input_tokens: 10,
                        latency_ms: 5,
                    },
                ],
            },
        })
        initKeaTests()
        const logic = magicEightBallLogic()
        logic.mount()
        logic.actions.setQuestion('Will it ship?')

        await logic.asyncActions.ask()
        expect(logic.values.answer).toBe('Yes')
        expect(logic.values.confidence).toBe(0.9)

        logic.actions.setQuestion('Will it ship on time?')
        expect(logic.values.answer).toBeNull()
        expect(logic.values.confidence).toBeNull()
    })

    it.each([
        ['shows the error of a failed ask', false, expect.any(String)],
        ['hides the error of a failed ask when the question changes during the ask', true, null],
    ])('%s', async (_, editWhileAsking, expectedError) => {
        useMocks({
            post: {
                '/api/projects/:team_id/ml_inference/decisions/decide/': () => [500, { detail: 'Model unavailable' }],
            },
        })
        initKeaTests()
        const logic = magicEightBallLogic()
        logic.mount()
        logic.actions.setQuestion('Will it ship?')

        const pendingAsk = logic.asyncActions.ask()
        if (editWhileAsking) {
            logic.actions.setQuestion('Will it ship on time?')
        }
        await pendingAsk

        expect(logic.values.askError).toEqual(expectedError)
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
