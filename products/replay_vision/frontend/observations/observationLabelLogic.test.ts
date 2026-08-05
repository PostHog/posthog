import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { initKeaTests } from '~/test/init'

import { visionObservationsLabelCreate, visionObservationsLabelDestroy } from '../generated/api'
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

    it('adopts a remote label change from props but keeps the draft on a same-label re-render', async () => {
        mountLogic(false)
        logic.actions.setFeedbackDraft('half-typed local edit')

        // Parent re-renders with the unchanged label: the local draft must survive.
        observationLabelLogic({
            observationId: 'obs-1',
            initialLabel: { is_correct: false, feedback: 'old feedback' },
            onChange,
        })
        expect(logic.values.feedbackDraft).toEqual('half-typed local edit')

        // Observation reloads with a teammate's newer label: adopt it and drop the pending autosave.
        observationLabelLogic({
            observationId: 'obs-1',
            initialLabel: { is_correct: true, feedback: 'teammate feedback' },
            onChange,
        })
        await jest.advanceTimersByTimeAsync(900)

        expect(visionObservationsLabelCreate).not.toHaveBeenCalled()
        expect(logic.values.label).toEqual({ is_correct: true, feedback: 'teammate feedback' })
        expect(logic.values.feedbackDraft).toEqual('teammate feedback')
    })

    it('scopes the in-flight state to the thumb being rated, not both buttons', async () => {
        // Regression: the two thumb buttons used to share one boolean `saving` flag, so rating
        // one thumb visually disabled the other too. `savingThumb` must track which thumb (if
        // any) is actually in flight.
        let resolveCreate: (value: unknown) => void = () => {}
        ;(visionObservationsLabelCreate as jest.Mock).mockReturnValue(
            new Promise((resolve) => {
                resolveCreate = resolve
            })
        )
        mountLogic(false)

        logic.actions.rate(true, '')
        expect(logic.values.savingThumb).toEqual('up')

        resolveCreate({ is_correct: true, feedback: '' })
        await jest.advanceTimersByTimeAsync(0)

        expect(logic.values.savingThumb).toBeNull()
    })

    it('scopes clearing a rating to the thumb that was clicked', async () => {
        let resolveDestroy: (value: unknown) => void = () => {}
        ;(visionObservationsLabelDestroy as jest.Mock).mockReturnValue(
            new Promise((resolve) => {
                resolveDestroy = resolve
            })
        )
        mountLogic(false)

        logic.actions.clearRating('down')
        expect(logic.values.savingThumb).toEqual('down')

        resolveDestroy(undefined)
        await jest.advanceTimersByTimeAsync(0)

        expect(logic.values.savingThumb).toBeNull()
    })
})
