import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { SurveyFeedbackButtons, SurveyFeedbackRating } from './SurveyFeedbackButtons'

describe('SurveyFeedbackButtons', () => {
    afterEach(cleanup)

    it.each([
        ['Helpful', '1'],
        ['Not helpful', '2'],
    ] as const)('sends %s separately from opening detailed feedback', (label, rating) => {
        const onChange = jest.fn()
        const onMoreFeedback = jest.fn()
        const props = { onChange, onMoreFeedback }
        const { rerender } = render(<SurveyFeedbackButtons {...props} />)
        fireEvent.click(screen.getByLabelText(label))
        expect(onChange).toHaveBeenCalledWith(rating)
        expect(onMoreFeedback).not.toHaveBeenCalled()
        rerender(<SurveyFeedbackButtons {...props} value={rating} />)
        fireEvent.click(screen.getByLabelText(label))
        expect(onChange).toHaveBeenCalledTimes(1)
        fireEvent.click(screen.getByText('Share more feedback'))
        expect(onMoreFeedback).toHaveBeenCalledTimes(1)
        expect(onChange).toHaveBeenCalledTimes(1)
    })

    it('blocks rating changes and opening the dialog while saving', () => {
        const onChange = jest.fn<void, [SurveyFeedbackRating]>()
        const onMoreFeedback = jest.fn()
        render(<SurveyFeedbackButtons onChange={onChange} onMoreFeedback={onMoreFeedback} loading />)
        fireEvent.click(screen.getByLabelText('Helpful'))
        fireEvent.click(screen.getByLabelText('Not helpful'))
        fireEvent.click(screen.getByText('Share more feedback'))
        expect(onChange).not.toHaveBeenCalled()
        expect(onMoreFeedback).not.toHaveBeenCalled()
    })
})
