import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { exampleFeedbackRating } from './apiSurvey.fixtures'
import { SurveyFeedbackButtons } from './SurveyFeedbackButtons'

describe('SurveyFeedbackButtons', () => {
    afterEach(cleanup)
    const submissionId = '00000000-0000-4000-8000-000000000123'

    it.each([
        ['Helpful', '1'],
        ['Not helpful', '2'],
    ] as const)('sends %s separately from opening detailed feedback', (label, rating) => {
        const onChange = jest.fn()
        const onMoreFeedback = jest.fn()
        const props = { question: exampleFeedbackRating, submissionId, onChange, onMoreFeedback }
        const { rerender } = render(<SurveyFeedbackButtons {...props} />)
        expect(screen.queryByText('Share more feedback')).toBeNull()
        fireEvent.click(screen.getByLabelText(label))
        expect(onChange).toHaveBeenCalledWith(rating, submissionId)
        expect(onMoreFeedback).not.toHaveBeenCalled()
        rerender(<SurveyFeedbackButtons {...props} value={rating} />)
        expect(screen.getByText('Share more feedback').closest('button')).toBe(document.activeElement)
        expect(screen.queryByLabelText('Helpful')).toBeNull()
        expect(screen.queryByLabelText('Not helpful')).toBeNull()
        expect(onChange).toHaveBeenCalledTimes(1)
        fireEvent.click(screen.getByText('Share more feedback'))
        expect(onMoreFeedback).toHaveBeenCalledWith(submissionId)
        expect(onChange).toHaveBeenCalledTimes(1)
    })

    it('waits until saving finishes before focusing the follow-up action', () => {
        const props = { question: exampleFeedbackRating, submissionId, onChange: jest.fn(), onMoreFeedback: jest.fn() }
        const { rerender } = render(<SurveyFeedbackButtons {...props} />)
        const thumb = screen.getByLabelText('Helpful')
        thumb.focus()
        fireEvent.click(thumb)
        rerender(<SurveyFeedbackButtons {...props} value="1" loading />)
        const followUp = screen.getByRole('button', { name: 'Share more feedback' })
        expect(followUp).not.toBe(document.activeElement)
        rerender(<SurveyFeedbackButtons {...props} value="1" />)
        expect(screen.getByRole('button', { name: 'Share more feedback' })).toBe(document.activeElement)
        screen.getByRole('button', { name: 'Share more feedback' }).blur()
        rerender(<SurveyFeedbackButtons {...props} value="1" />)
        expect(document.activeElement).toBe(document.body)
    })

    it.each([3, 5, 7, 10] as const)('renders the configured numeric scale %s', (scale) => {
        const onChange = jest.fn()
        render(
            <SurveyFeedbackButtons
                question={{
                    ...exampleFeedbackRating,
                    display: 'number',
                    scale,
                    question: 'How useful?',
                    lowerBoundLabel: 'Low',
                    upperBoundLabel: 'High',
                }}
                submissionId={submissionId}
                onChange={onChange}
                onMoreFeedback={jest.fn()}
            />
        )
        const start = scale === 10 ? 0 : 1
        expect(screen.getAllByRole('button').map((button) => button.textContent)).toEqual(
            Array.from({ length: scale - start + 1 }, (_, index) => String(start + index))
        )
        fireEvent.click(screen.getByRole('button', { name: String(start) }))
        expect(onChange).toHaveBeenCalledWith(String(start), submissionId)
        expect(screen.getByText('How useful?')).toBeTruthy()
    })

    it('does not steal focus for a preselected rating', () => {
        render(
            <SurveyFeedbackButtons
                question={exampleFeedbackRating}
                submissionId={submissionId}
                value="1"
                onChange={jest.fn()}
                onMoreFeedback={jest.fn()}
            />
        )
        expect(screen.getByRole('button', { name: 'Share more feedback' })).not.toBe(document.activeElement)
    })

    it.each([undefined, '1'] as const)('blocks actions while saving with rating %s', (value) => {
        const onChange = jest.fn()
        const onMoreFeedback = jest.fn()
        render(
            <SurveyFeedbackButtons
                question={exampleFeedbackRating}
                submissionId={submissionId}
                onChange={onChange}
                onMoreFeedback={onMoreFeedback}
                value={value}
                loading
            />
        )
        screen.getAllByRole('button').forEach((button) => fireEvent.click(button))
        expect(onChange).not.toHaveBeenCalled()
        expect(onMoreFeedback).not.toHaveBeenCalled()
    })
})
