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
        expect(screen.queryByText('Share more feedback')).toBeNull()
        fireEvent.click(screen.getByLabelText(label))
        expect(onChange).toHaveBeenCalledWith(rating)
        expect(onMoreFeedback).not.toHaveBeenCalled()
        rerender(<SurveyFeedbackButtons {...props} value={rating} />)
        expect(screen.getByText('Share more feedback').closest('button')).toBe(document.activeElement)
        fireEvent.click(screen.getByLabelText(label))
        expect(onChange).toHaveBeenCalledTimes(1)
        fireEvent.click(screen.getByText('Share more feedback'))
        expect(onMoreFeedback).toHaveBeenCalledTimes(1)
        expect(onChange).toHaveBeenCalledTimes(1)
    })

    it('waits until saving finishes before focusing the follow-up action', () => {
        const props = { onChange: jest.fn(), onMoreFeedback: jest.fn() }
        const { rerender } = render(<SurveyFeedbackButtons {...props} />)
        const thumb = screen.getByLabelText('Helpful')
        thumb.focus()
        fireEvent.click(thumb)
        rerender(<SurveyFeedbackButtons {...props} value="1" loading />)
        const followUp = screen.getByRole('button', { name: 'Share more feedback' })
        expect(followUp).not.toBe(document.activeElement)
        rerender(<SurveyFeedbackButtons {...props} value="1" />)
        expect(screen.getByRole('button', { name: 'Share more feedback' })).toBe(document.activeElement)
        thumb.focus()
        rerender(<SurveyFeedbackButtons {...props} value="1" />)
        expect(thumb).toBe(document.activeElement)
    })

    it('does not steal focus for a preselected rating', () => {
        render(<SurveyFeedbackButtons value="1" onChange={jest.fn()} onMoreFeedback={jest.fn()} />)
        expect(screen.getByRole('button', { name: 'Share more feedback' })).not.toBe(document.activeElement)
    })

    it('blocks rating changes and opening the dialog while saving', () => {
        const onChange = jest.fn<void, [SurveyFeedbackRating]>()
        const onMoreFeedback = jest.fn()
        render(<SurveyFeedbackButtons onChange={onChange} onMoreFeedback={onMoreFeedback} value="1" loading />)
        fireEvent.click(screen.getByLabelText('Helpful'))
        fireEvent.click(screen.getByLabelText('Not helpful'))
        fireEvent.click(screen.getByText('Share more feedback'))
        expect(onChange).not.toHaveBeenCalled()
        expect(onMoreFeedback).not.toHaveBeenCalled()
    })
})
