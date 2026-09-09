import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import type { ToolCallMessage } from 'products/posthog_ai/frontend/types/toolTypes'

import { QuestionRenderer } from './QuestionRenderer'

function makeMessage(overrides: Partial<ToolCallMessage> = {}): ToolCallMessage {
    return {
        id: 'tc-1',
        resolvedKey: 'AskUserQuestion',
        rawServerName: '',
        rawToolName: 'AskUserQuestion',
        claudeToolName: 'AskUserQuestion',
        rawInput: {
            questions: [
                {
                    question: 'Which goal matters most?',
                    header: 'Goal',
                    multiSelect: false,
                    options: [{ label: 'Activation' }, { label: 'Revenue' }],
                },
            ],
        },
        content: [],
        status: 'completed',
        ...overrides,
    }
}

function renderCard(message: ToolCallMessage): void {
    render(<QuestionRenderer message={message} isLastInGroup displayName="Question" />)
}

describe('QuestionRenderer', () => {
    afterEach(() => {
        cleanup()
    })

    it('shows the full Q&A on expand', () => {
        renderCard(makeMessage({ rawOutput: { answers: { 'Which goal matters most?': 'Revenue' } } }))

        expect(screen.queryByText('Revenue')).not.toBeInTheDocument()
        // The full question + answer live in the collapsible body.
        expect(screen.queryByText('Which goal matters most?')).not.toBeInTheDocument()

        fireEvent.click(screen.getByRole('button'))
        expect(screen.getByText('Which goal matters most?')).toBeInTheDocument()
        expect(screen.getByText('Revenue')).toBeInTheDocument()
        // The header label ("Goal") is dropped from the recap.
        expect(screen.queryByText('Goal')).not.toBeInTheDocument()
    })

    it.each(['in_progress', 'failed', 'completed'] as const)(
        'lets the user read an unanswered question when the call is %s',
        (status) => {
            renderCard(makeMessage({ status, rawOutput: undefined }))

            expect(screen.queryByText('Which goal matters most?')).not.toBeInTheDocument()
            fireEvent.click(screen.getByRole('button'))
            expect(screen.getByText('Which goal matters most?')).toBeVisible()
            expect(screen.queryByText('Revenue')).not.toBeInTheDocument()
        }
    )

    it('retains unanswered questions alongside answers for a partially answered request', () => {
        renderCard(
            makeMessage({
                rawInput: {
                    questions: [
                        { question: 'Goal?', header: 'Goal', multiSelect: false, options: [{ label: 'Revenue' }] },
                        { question: 'When?', header: 'When', multiSelect: false, options: [{ label: 'Weekly' }] },
                    ],
                },
                rawOutput: { answers: { 'Goal?': 'Revenue' } },
            })
        )

        fireEvent.click(screen.getByRole('button'))
        expect(screen.getByText('Revenue')).toBeInTheDocument()
        expect(screen.getByText('When?')).toBeInTheDocument()
        expect(screen.queryByText('Weekly')).not.toBeInTheDocument()
    })

    it('falls back to a joined answer string when there is no per-question map', () => {
        renderCard(makeMessage({ rawOutput: { text: 'User picked Revenue' } }))

        fireEvent.click(screen.getByRole('button'))
        expect(screen.getByText('User picked Revenue')).toBeInTheDocument()
    })

    it('shows the error message when the call failed', () => {
        const title = 'Choose a goal for this analysis before continuing with the remaining steps.'
        renderCard(
            makeMessage({ title, status: 'failed', rawOutput: undefined, error: { message: 'Question timed out' } })
        )

        expect(screen.getByText('Question timed out')).toBeInTheDocument()
        fireEvent.click(screen.getByRole('button'))
        expect(screen.getByText(title)).toBeInTheDocument()
        expect(screen.getByText('Which goal matters most?')).toBeVisible()
    })

    it('falls back to the generic tool card when the input has no questions', () => {
        renderCard(makeMessage({ rawInput: {}, rawOutput: undefined }))

        // The generic card renders instead of the question recap.
        expect(screen.getByText('Question')).toBeInTheDocument()
        expect(screen.queryByText('Which goal matters most?')).not.toBeInTheDocument()
    })
})
