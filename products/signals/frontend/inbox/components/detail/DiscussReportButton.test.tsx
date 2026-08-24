import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { initKeaTests } from '~/test/init'

import { captureInboxReportAction } from '../../inboxAnalytics'
import { inboxTaskKickoffLogic } from '../../inboxTaskKickoffLogic'
import { SignalReport, SignalReportStatus } from '../../types'
import { DiscussReportButton } from './DiscussReportButton'

jest.mock('../../inboxAnalytics', () => ({
    ...jest.requireActual('../../inboxAnalytics'),
    captureInboxReportAction: jest.fn(),
}))

const SUGGESTION = 'Which teams are hitting this exception the most?'

function makeReport(suggestedPrompts?: string[]): SignalReport {
    return {
        id: 'report-1',
        title: 'Exceptions spiked',
        summary: 'summary',
        status: SignalReportStatus.READY,
        total_weight: 0,
        signal_count: 1,
        relevant_user_count: null,
        artefact_count: 0,
        is_suggested_reviewer: false,
        created_at: '2026-06-11T10:00:00Z',
        updated_at: '2026-06-11T10:00:00Z',
        suggested_prompts: suggestedPrompts,
    } satisfies SignalReport
}

describe('DiscussReportButton', () => {
    let discussReport: jest.Mock

    beforeEach(() => {
        initKeaTests()
        inboxTaskKickoffLogic.mount()
        discussReport = jest.fn()
        jest.spyOn(inboxTaskKickoffLogic.actions, 'discussReport').mockImplementation(discussReport)
        jest.mocked(captureInboxReportAction).mockClear()
    })

    afterEach(() => {
        cleanup()
        jest.restoreAllMocks()
    })

    async function openPopover(report: SignalReport): Promise<ReturnType<typeof userEvent.setup>> {
        const user = userEvent.setup()
        render(<DiscussReportButton report={report} reportUrl="https://app/report-1" />)
        await user.click(screen.getByText('Ask AI'))
        return user
    }

    function questionSourceOf(call: number = 0): unknown {
        return jest.mocked(captureInboxReportAction).mock.calls[call][0].extra?.question_source
    }

    it('fills the textarea from a suggestion without asking AI', async () => {
        // The whole point of the row: it is a starting draft, not a send button. Submitting on click
        // would spend a paid Opus run on a mis-click and take away the chance to edit the question.
        const user = await openPopover(makeReport([SUGGESTION]))

        await user.click(screen.getByText(SUGGESTION))

        expect(screen.getByRole('textbox')).toHaveValue(SUGGESTION)
        expect(discussReport).not.toHaveBeenCalled()
        expect(captureInboxReportAction).not.toHaveBeenCalled()
    })

    it.each([
        [
            'sending a suggestion as written',
            'suggested',
            async (user: ReturnType<typeof userEvent.setup>) => await user.click(screen.getByText(SUGGESTION)),
        ],
        [
            'narrowing a suggestion before sending',
            'edited_suggestion',
            async (user: ReturnType<typeof userEvent.setup>) => {
                await user.click(screen.getByText(SUGGESTION))
                await user.type(screen.getByRole('textbox'), ' Last 7 days only.')
            },
        ],
        [
            'emptying the box and writing another question',
            'typed',
            async (user: ReturnType<typeof userEvent.setup>) => {
                await user.click(screen.getByText(SUGGESTION))
                await user.clear(screen.getByRole('textbox'))
                await user.type(screen.getByRole('textbox'), 'Something else entirely?')
            },
        ],
        [
            'selecting the filled box and typing over it',
            'typed',
            async (user: ReturnType<typeof userEvent.setup>) => {
                // Select-all-and-replace never empties the box, so provenance can't be tracked from an
                // intermediate value: the question that arrives keeps nothing of the suggestion.
                await user.click(screen.getByText(SUGGESTION))
                await user.click(screen.getByRole('textbox'))
                await user.keyboard('{Control>}a{/Control}Something else entirely?')
            },
        ],
    ])('reports question_source after %s', async (_name, expected, act) => {
        // This property is the only way to tell whether the suggestions are worth offering. Collapsing
        // any of the three into another makes the readout lie about it: crediting an edited question as
        // `suggested` overstates them, and crediting a cleared box as `edited_suggestion` understates
        // the questions readers write for themselves.
        const user = await openPopover(makeReport([SUGGESTION]))

        await act(user)
        await user.click(screen.getByTestId('inbox-report-ask-ai-submit'))

        expect(questionSourceOf()).toBe(expected)
        expect(discussReport).toHaveBeenCalledTimes(1)
    })

    it('carries the suggestion count so a typed question can be read in context', async () => {
        // A `typed` question on a report that offered nothing is not evidence against suggestions, so
        // the count is what makes the source readable.
        const user = await openPopover(makeReport())

        await user.type(screen.getByRole('textbox'), 'Who is affected?')
        await user.click(screen.getByTestId('inbox-report-ask-ai-submit'))

        const { extra } = jest.mocked(captureInboxReportAction).mock.calls[0][0]
        expect(extra).toEqual({ question_source: 'typed', suggestion_count: 0 })
    })

    it('renders no suggestion rows for a report without any', async () => {
        // Reports authored before this existed, and every pipeline report, must look exactly as they
        // did — the section is not an empty state.
        await openPopover(makeReport())

        expect(screen.queryByText('Suggested questions')).not.toBeInTheDocument()
    })
})
