import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { initKeaTests } from '~/test/init'

import { visionObservationsLabelCreate } from '../generated/api'
import { observationLabelLogic } from './observationLabelLogic'

jest.mock('../generated/api', () => ({
    visionObservationsLabelCreate: jest.fn(),
    visionObservationsLabelDestroy: jest.fn(),
}))

const TEAM_ID = String(MOCK_DEFAULT_TEAM.id)

describe('observationLabelLogic feedback autosave', () => {
    let logic: ReturnType<typeof observationLabelLogic.build>
    let onChange: jest.Mock

    const mountLogic = (isCorrect: boolean): void => {
        logic = observationLabelLogic({
            observationId: 'obs-1',
            initialLabel: { is_correct: isCorrect, feedback: 'old feedback' },
            onChange,
        })
        logic.mount()
    }

    beforeEach(() => {
        jest.clearAllMocks()
        initKeaTests()
        ;(visionObservationsLabelCreate as jest.Mock).mockImplementation((_team, _id, body) =>
            Promise.resolve({ ...body })
        )
        onChange = jest.fn()
        jest.useFakeTimers()
    })

    afterEach(() => {
        jest.useRealTimers()
        logic?.unmount()
    })

    it.each([
        ['thumbs-down', false],
        ['thumbs-up', true],
    ])('autosaves edited feedback on a %s rating after the debounce and notifies onChange', async (_, isCorrect) => {
        mountLogic(isCorrect)
        logic.actions.setFeedbackDraft('scanner missed the refund step')
        await jest.advanceTimersByTimeAsync(900)

        expect(visionObservationsLabelCreate).toHaveBeenCalledTimes(1)
        expect(visionObservationsLabelCreate).toHaveBeenCalledWith(TEAM_ID, 'obs-1', {
            is_correct: isCorrect,
            feedback: 'scanner missed the refund step',
        })
        expect(onChange).toHaveBeenCalledWith({ is_correct: isCorrect, feedback: 'scanner missed the refund step' })
    })

    it('a rating click during the debounce wins over the pending autosave', async () => {
        mountLogic(false)
        logic.actions.setFeedbackDraft('scanner missed the refund step')
        logic.actions.rate(true, '')
        await jest.advanceTimersByTimeAsync(900)

        expect(visionObservationsLabelCreate).toHaveBeenCalledTimes(1)
        expect(visionObservationsLabelCreate).toHaveBeenCalledWith(TEAM_ID, 'obs-1', {
            is_correct: true,
            feedback: '',
        })
    })
})
