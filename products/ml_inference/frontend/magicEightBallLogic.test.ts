import { MAX_OPTIONS_PER_QUESTION } from './decisionPlaygroundLogic'
import { ANSWER_QUESTION_ID, EIGHT_BALL_ANSWERS, buildEightBallRequest } from './magicEightBallLogic'

describe('magicEightBallLogic', () => {
    it('fits inside the decision model option limit', () => {
        expect(Object.keys(EIGHT_BALL_ANSWERS).length).toBeLessThanOrEqual(MAX_OPTIONS_PER_QUESTION)
    })

    it('asks one choice question about the trimmed product question', () => {
        const request = buildEightBallRequest('  Will the new onboarding lift activation?  ')

        expect(request.state).toBe('Will the new onboarding lift activation?')
        expect(Object.keys(request.questions)).toEqual([ANSWER_QUESTION_ID])
    })
})
