import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import type { MultiQuestionFormQuestion } from '~/queries/schema/schema-assistant-messages'

import { MultiFieldQuestion, QuestionField } from './QuestionField'

describe('QuestionField', () => {
    afterEach(() => {
        cleanup()
    })

    const baseQuestion: MultiQuestionFormQuestion = {
        id: 'test',
        title: 'Test',
        question: 'Test question?',
    }

    const selectQuestion: MultiQuestionFormQuestion = {
        ...baseQuestion,
        type: 'select',
        options: [
            { value: 'Option A', description: 'First option' },
            { value: 'Option B', description: 'Second option' },
        ],
    }

    it('renders select field by default', () => {
        const onAnswer = jest.fn()
        render(
            <QuestionField
                question={selectQuestion}
                value={undefined}
                onAnswer={onAnswer}
                onChange={jest.fn()}
                onSubmit={jest.fn()}
            />
        )
        expect(screen.getByText('Option A')).toBeInTheDocument()
        expect(screen.getByText('Option B')).toBeInTheDocument()
    })

    it('renders multi_select with checkboxes', () => {
        const onAnswer = jest.fn()
        const question: MultiQuestionFormQuestion = {
            ...baseQuestion,
            type: 'multi_select',
            options: [{ value: 'Alpha' }, { value: 'Beta' }],
        }
        render(
            <QuestionField
                question={question}
                value={undefined}
                onAnswer={onAnswer}
                onChange={jest.fn()}
                onSubmit={jest.fn()}
            />
        )
        expect(screen.getAllByRole('checkbox')).toHaveLength(2)
    })

    it('multi_select shows error message when submitting with no selection', () => {
        const onAnswer = jest.fn()
        const onSubmit = jest.fn()
        const question: MultiQuestionFormQuestion = {
            ...baseQuestion,
            type: 'multi_select',
            options: [{ value: 'Alpha' }, { value: 'Beta' }, { value: 'Gamma' }],
        }
        render(
            <QuestionField
                question={question}
                value={undefined}
                onAnswer={onAnswer}
                onChange={jest.fn()}
                onSubmit={onSubmit}
            />
        )

        const buttons = screen.getAllByRole('button')
        const submitButton = buttons.find((b) => b.textContent?.includes('Next'))
        expect(submitButton).toBeInTheDocument()
        fireEvent.click(submitButton!)
        expect(screen.getByText('Select at least one option')).toBeInTheDocument()
        expect(onAnswer).not.toHaveBeenCalled()
        expect(onSubmit).not.toHaveBeenCalled()
    })

    it('multi_select renders custom entry input by default', () => {
        const onAnswer = jest.fn()
        const question: MultiQuestionFormQuestion = {
            ...baseQuestion,
            type: 'multi_select',
            options: [{ value: 'Alpha' }, { value: 'Beta' }],
        }
        render(
            <QuestionField
                question={question}
                value={undefined}
                onAnswer={onAnswer}
                onChange={jest.fn()}
                onSubmit={jest.fn()}
            />
        )
        expect(screen.getByPlaceholderText('Add your own option...')).toBeInTheDocument()
        expect(screen.getByRole('button', { name: /Add/ })).toBeInTheDocument()
    })

    it('multi_select hides custom entry input when allow_custom_answer is false', () => {
        const onAnswer = jest.fn()
        const question: MultiQuestionFormQuestion = {
            ...baseQuestion,
            type: 'multi_select',
            options: [{ value: 'Alpha' }, { value: 'Beta' }],
            allow_custom_answer: false,
        }
        render(
            <QuestionField
                question={question}
                value={undefined}
                onAnswer={onAnswer}
                onChange={jest.fn()}
                onSubmit={jest.fn()}
            />
        )
        expect(screen.queryByPlaceholderText('Add your own option...')).not.toBeInTheDocument()
    })

    it('multi_select adds custom value and includes it in submission', () => {
        const onChange = jest.fn()
        const onSubmit = jest.fn()
        const question: MultiQuestionFormQuestion = {
            ...baseQuestion,
            type: 'multi_select',
            options: [{ value: 'Alpha' }, { value: 'Beta' }],
        }
        const { rerender } = render(
            <QuestionField
                question={question}
                value={undefined}
                onAnswer={jest.fn()}
                onChange={onChange}
                onSubmit={onSubmit}
            />
        )

        const input = screen.getByPlaceholderText('Add your own option...')
        fireEvent.change(input, { target: { value: 'Custom value' } })
        fireEvent.click(screen.getByRole('button', { name: /Add/ }))

        // onChange should be called with the new selection
        expect(onChange).toHaveBeenCalledWith(['Custom value'])

        // Simulate parent updating the controlled value
        rerender(
            <QuestionField
                question={question}
                value={['Custom value']}
                onAnswer={jest.fn()}
                onChange={onChange}
                onSubmit={onSubmit}
            />
        )

        // Custom value should appear as a checked checkbox
        expect(screen.getByText('Custom value')).toBeInTheDocument()
        expect(screen.getAllByRole('checkbox')).toHaveLength(3)

        // Submit with only the custom value selected
        const submitButton = screen.getAllByRole('button').find((b) => b.textContent?.includes('Next'))
        fireEvent.click(submitButton!)
        expect(onSubmit).toHaveBeenCalled()
    })

    it('multi_select does not add empty or whitespace-only custom values', () => {
        const onAnswer = jest.fn()
        const question: MultiQuestionFormQuestion = {
            ...baseQuestion,
            type: 'multi_select',
            options: [{ value: 'Alpha' }, { value: 'Beta' }],
        }
        render(
            <QuestionField
                question={question}
                value={undefined}
                onAnswer={onAnswer}
                onChange={jest.fn()}
                onSubmit={jest.fn()}
            />
        )

        const input = screen.getByPlaceholderText('Add your own option...')
        fireEvent.change(input, { target: { value: '   ' } })
        fireEvent.click(screen.getByRole('button', { name: /Add/ }))

        // Should still only have the 2 predefined checkboxes
        expect(screen.getAllByRole('checkbox')).toHaveLength(2)
    })

    it('multi_select auto-checks predefined option when duplicate custom value is entered', () => {
        const onChange = jest.fn()
        const question: MultiQuestionFormQuestion = {
            ...baseQuestion,
            type: 'multi_select',
            options: [{ value: 'Alpha' }, { value: 'Beta' }],
        }
        render(
            <QuestionField
                question={question}
                value={undefined}
                onAnswer={jest.fn()}
                onChange={onChange}
                onSubmit={jest.fn()}
            />
        )

        const input = screen.getByPlaceholderText('Add your own option...')
        fireEvent.change(input, { target: { value: 'alpha' } })
        fireEvent.click(screen.getByRole('button', { name: /Add/ }))

        // Should call onChange with the matched predefined option
        expect(onChange).toHaveBeenCalledWith(['Alpha'])
        // Should still only have 2 checkboxes (no duplicate added)
        expect(screen.getAllByRole('checkbox')).toHaveLength(2)
        // Input should be cleared
        expect(input).toHaveValue('')
    })

    it('multi_select restores custom values from previous answer', () => {
        const onAnswer = jest.fn()
        const question: MultiQuestionFormQuestion = {
            ...baseQuestion,
            type: 'multi_select',
            options: [{ value: 'Alpha' }, { value: 'Beta' }],
        }
        render(
            <QuestionField
                question={question}
                value={['Alpha', 'My custom entry']}
                onAnswer={onAnswer}
                onChange={jest.fn()}
                onSubmit={jest.fn()}
            />
        )

        // Should have 3 checkboxes: 2 predefined + 1 custom
        expect(screen.getAllByRole('checkbox')).toHaveLength(3)
        expect(screen.getByText('My custom entry')).toBeInTheDocument()
    })

    it('calls onAnswer with null when clicking an already-selected option to deselect', () => {
        const onAnswer = jest.fn()
        render(
            <QuestionField
                question={selectQuestion}
                value="Option A"
                onAnswer={onAnswer}
                onChange={jest.fn()}
                onSubmit={jest.fn()}
            />
        )

        // Option A is already selected via value prop — clicking it again should deselect
        fireEvent.click(screen.getByText('Option A'))
        expect(onAnswer).toHaveBeenCalledWith(null)
    })

    it('calls onAnswer with the value when clicking a different option', () => {
        const onAnswer = jest.fn()
        render(
            <QuestionField
                question={selectQuestion}
                value="Option A"
                onAnswer={onAnswer}
                onChange={jest.fn()}
                onSubmit={jest.fn()}
            />
        )

        fireEvent.click(screen.getByText('Option B'))
        expect(onAnswer).toHaveBeenCalledWith('Option B')
    })

    it('renders a skip button when onSkip is provided for select questions', () => {
        const onSkip = jest.fn()
        render(
            <QuestionField
                question={selectQuestion}
                value={undefined}
                onAnswer={jest.fn()}
                onChange={jest.fn()}
                onSubmit={jest.fn()}
                onSkip={onSkip}
            />
        )

        fireEvent.click(screen.getByRole('button', { name: 'Skip question' }))

        expect(onSkip).toHaveBeenCalledTimes(1)
    })

    describe('MultiFieldQuestion', () => {
        const multiFieldQuestion: MultiQuestionFormQuestion = {
            id: 'config',
            title: 'Config',
            question: 'Configure your experiment',
            fields: [
                { id: 'sample', type: 'number', label: 'Sample size', min: 100, max: 10000, placeholder: 'e.g. 1000' },
                { id: 'confidence', type: 'slider', label: 'Confidence level', min: 80, max: 99 },
                { id: 'notify', type: 'toggle', label: 'Notify on complete' },
            ],
        }

        it('renders all field labels', () => {
            render(
                <MultiFieldQuestion
                    question={multiFieldQuestion}
                    answers={{ confidence: '80', notify: 'false' }}
                    onFieldChange={jest.fn()}
                    onSubmit={jest.fn()}
                />
            )
            expect(screen.getByText('Sample size')).toBeInTheDocument()
            expect(screen.getByText('Confidence level')).toBeInTheDocument()
            expect(screen.getByText('Notify on complete')).toBeInTheDocument()
        })

        it('shows validation errors when submitting with empty required fields', () => {
            const onSubmit = jest.fn()
            const { container } = render(
                <MultiFieldQuestion
                    question={multiFieldQuestion}
                    answers={{ confidence: '80', notify: 'false' }}
                    onFieldChange={jest.fn()}
                    onSubmit={onSubmit}
                />
            )
            const submitButton = container.querySelector('.LemonButton--primary')
            expect(submitButton).not.toBeNull()
            fireEvent.click(submitButton!)
            expect(container.querySelector('.text-danger')).not.toBeNull()
            expect(container.querySelector('.text-danger')?.textContent).toBe('This field is required')
            expect(onSubmit).not.toHaveBeenCalled()
        })

        it('calls onSubmit when all fields are valid and button is clicked', () => {
            const onSubmit = jest.fn()
            const { container } = render(
                <MultiFieldQuestion
                    question={multiFieldQuestion}
                    answers={{ sample: '500', confidence: '95', notify: 'true' }}
                    onFieldChange={jest.fn()}
                    onSubmit={onSubmit}
                />
            )
            const submitButton = container.querySelector('.LemonButton--primary')
            expect(submitButton).not.toBeNull()
            expect(submitButton).not.toHaveAttribute('aria-disabled', 'true')
            fireEvent.click(submitButton!)
            expect(onSubmit).toHaveBeenCalled()
        })

        it('calls onSkip when the skip button is clicked', () => {
            const onSkip = jest.fn()
            render(
                <MultiFieldQuestion
                    question={multiFieldQuestion}
                    answers={{ confidence: '95', notify: 'true' }}
                    onFieldChange={jest.fn()}
                    onSubmit={jest.fn()}
                    onSkip={onSkip}
                />
            )

            fireEvent.click(screen.getAllByRole('button', { name: 'Skip question' }).at(-1)!)

            expect(onSkip).toHaveBeenCalledTimes(1)
        })
    })
})
