import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { useActions, useValues } from 'kea'

import type { AgentQuestion } from '../policy/questionUtils'
import type { PermissionRequestRecord, ToolInvocation } from '../types/streamTypes'
import { QuestionInput } from './QuestionInput'

jest.mock('kea', () => ({
    ...jest.requireActual('kea'),
    useActions: jest.fn(),
    useValues: jest.fn(),
}))

jest.mock('../logics/runStreamLogic', () => ({
    runStreamLogic: jest.fn(() => ({ __mock: 'runStreamLogicInstance' })),
}))

const rawToolCall: ToolInvocation = {
    toolCallId: 'tc-1',
    rawServerName: 'claude',
    rawToolName: '',
    input: {},
    status: 'pending',
    contentBlocks: [],
    meta: { claudeCode: { toolName: 'AskUserQuestion' } },
}

function makeRequest(questions: AgentQuestion[]): PermissionRequestRecord {
    return {
        requestId: 'req-1',
        toolCallId: 'tc-1',
        toolName: 'AskUserQuestion',
        options: questions[0].options.map((o, idx) => ({
            optionId: `option_${idx}`,
            name: o.label,
            kind: 'allow_once',
        })),
        rawToolCall,
        questions,
    }
}

const goalQuestion: AgentQuestion = {
    question: 'Which goal matters most?',
    header: 'Goal',
    multiSelect: false,
    options: [{ label: 'Activation', description: 'aha moment' }, { label: 'Revenue' }],
}

describe('QuestionInput', () => {
    const respondToPermission = jest.fn()

    beforeEach(() => {
        jest.clearAllMocks()
        ;(useActions as jest.Mock).mockReturnValue({ respondToPermission })
        ;(useValues as jest.Mock).mockReturnValue({ respondingToPermission: false })
    })

    afterEach(() => {
        cleanup()
    })

    it('renders the header chip, question text, and options via QuestionField', () => {
        render(<QuestionInput streamKey="conv-1" request={makeRequest([goalQuestion])} />)

        expect(screen.getByText('Goal')).toBeInTheDocument()
        expect(screen.getByText('Which goal matters most?')).toBeInTheDocument()
        expect(screen.getByText('Activation')).toBeInTheDocument()
        expect(screen.getByText('Revenue')).toBeInTheDocument()
        expect(screen.getByText('aha moment')).toBeInTheDocument()
    })

    it('stages a single-select pick and only submits on explicit confirm', () => {
        render(<QuestionInput streamKey="conv-1" request={makeRequest([goalQuestion])} />)

        // Picking an option must not submit on its own — a stray click can't fire the answer.
        fireEvent.click(screen.getByText('Revenue'))
        expect(respondToPermission).not.toHaveBeenCalled()

        // Committing goes through the visible Submit button.
        fireEvent.click(screen.getByText('Submit'))
        expect(respondToPermission).toHaveBeenCalledWith({
            requestId: 'req-1',
            optionId: 'option_1',
            answers: { 'Which goal matters most?': 'Revenue' },
            customInput: undefined,
        })
    })

    it('joins multiple selections for a multi-select question', () => {
        const productsQuestion: AgentQuestion = {
            question: 'Which products?',
            header: 'Products',
            multiSelect: true,
            options: [{ label: 'Insights' }, { label: 'Replay' }, { label: 'Flags' }],
        }
        render(<QuestionInput streamKey="conv-1" request={makeRequest([productsQuestion])} />)

        fireEvent.click(screen.getByText('Insights'))
        fireEvent.click(screen.getByText('Flags'))
        fireEvent.click(screen.getByText('Submit'))

        expect(respondToPermission).toHaveBeenCalledWith({
            requestId: 'req-1',
            optionId: 'option_0',
            answers: { 'Which products?': 'Insights, Flags' },
            customInput: undefined,
        })
    })

    it('sends a free-typed answer through the custom path with option_0 fallback', () => {
        render(<QuestionInput streamKey="conv-1" request={makeRequest([goalQuestion])} />)

        // Open the custom "Type your answer" field, type, and submit.
        fireEvent.click(screen.getByText("Explain what you'd like instead."))
        fireEvent.change(screen.getByPlaceholderText('Type your answer...'), { target: { value: 'Cut churn' } })
        fireEvent.click(screen.getByText('Submit'))

        expect(respondToPermission).toHaveBeenCalledWith({
            requestId: 'req-1',
            optionId: 'option_0',
            answers: { 'Which goal matters most?': 'Cut churn' },
            customInput: 'Cut churn',
        })
    })

    it('does not submit a multi-select question with nothing selected', () => {
        const productsQuestion: AgentQuestion = {
            question: 'Which products?',
            header: 'Products',
            multiSelect: true,
            options: [{ label: 'Insights' }, { label: 'Replay' }],
        }
        render(<QuestionInput streamKey="conv-1" request={makeRequest([productsQuestion])} />)

        fireEvent.click(screen.getByText('Submit'))

        expect(screen.getByText('Select at least one option')).toBeInTheDocument()
        expect(respondToPermission).not.toHaveBeenCalled()
    })

    it('steps through multiple questions and submits all answers at once', () => {
        const second: AgentQuestion = {
            question: 'Which timeframe?',
            header: 'Timeframe',
            multiSelect: false,
            options: [{ label: 'Weekly' }, { label: 'Monthly' }],
        }
        render(<QuestionInput streamKey="conv-1" request={makeRequest([goalQuestion, second])} />)

        expect(screen.getByText('1/2')).toBeInTheDocument()
        // Pick then confirm with "Next" to advance to the next question.
        fireEvent.click(screen.getByText('Activation'))
        fireEvent.click(screen.getByText('Next'))
        expect(screen.getByText('2/2')).toBeInTheDocument()
        expect(respondToPermission).not.toHaveBeenCalled()

        // Confirming the last question with "Submit" sends all collected answers.
        fireEvent.click(screen.getByText('Monthly'))
        fireEvent.click(screen.getByText('Submit'))

        expect(respondToPermission).toHaveBeenCalledWith({
            requestId: 'req-1',
            optionId: 'option_0',
            answers: { 'Which goal matters most?': 'Activation', 'Which timeframe?': 'Monthly' },
            customInput: undefined,
        })
    })

    it('shows a sending state and blocks interaction while a reply is in flight', () => {
        ;(useValues as jest.Mock).mockReturnValue({ respondingToPermission: true })
        render(<QuestionInput streamKey="conv-1" request={makeRequest([goalQuestion])} />)

        expect(screen.getByText('Sending response…')).toBeInTheDocument()
        expect(screen.queryByText('Revenue')).not.toBeInTheDocument()
        expect(respondToPermission).not.toHaveBeenCalled()
    })
})
