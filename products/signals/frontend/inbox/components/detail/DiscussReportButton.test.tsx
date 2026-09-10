import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { initKeaTests } from '~/test/init'
import { SidePanelTab } from '~/types'

import { captureInboxReportAction } from '../../inboxAnalytics'
import { inboxTaskKickoffLogic, REPORT_AI_PANEL } from '../../inboxTaskKickoffLogic'
import { SignalReport, SignalReportStatus } from '../../types'
import { DiscussReportButton } from './DiscussReportButton'
import { ReportDiscussionComposer } from './ReportDiscussionComposer'

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

    async function openPanel(report: SignalReport): Promise<ReturnType<typeof userEvent.setup>> {
        const user = userEvent.setup()
        render(<DiscussReportButton report={report} reportUrl="https://app/report-1" />)
        await user.click(screen.getByText('Ask AI'))
        expect(sidePanelStateLogic.values.selectedTab).toBe(SidePanelTab.Max)
        expect(sidePanelStateLogic.values.selectedTabOptions).toBe(REPORT_AI_PANEL)
        expect(inboxTaskKickoffLogic.values.reportChatContext?.report.id).toBe(report.id)
        expect(discussReport).not.toHaveBeenCalled()
        render(<ReportDiscussionComposer report={report} reportUrl="https://app/report-1" />)
        return user
    }

    function questionSourceOf(call: number = 0): unknown {
        return jest.mocked(captureInboxReportAction).mock.calls[call][0].extra?.question_source
    }

    it('sends a suggestion with one click from the report sidebar', async () => {
        const user = await openPanel(makeReport([SUGGESTION]))

        await user.click(screen.getByText(SUGGESTION))

        expect(discussReport).toHaveBeenCalledTimes(1)
        expect(discussReport).toHaveBeenCalledWith(
            expect.objectContaining({ id: 'report-1' }),
            'https://app/report-1',
            SUGGESTION
        )
        expect(questionSourceOf()).toBe('suggested')
    })

    it.each([
        [
            'writing a question',
            'typed',
            async (user: ReturnType<typeof userEvent.setup>) => {
                await user.type(screen.getByRole('textbox'), 'Something else entirely?')
            },
        ],
        [
            'replacing a draft',
            'typed',
            async (user: ReturnType<typeof userEvent.setup>) => {
                await user.type(screen.getByRole('textbox'), 'A first draft')
                await user.keyboard('{Control>}a{/Control}Something else entirely?')
            },
        ],
    ])('reports question_source after %s', async (_name, expected, act) => {
        const user = await openPanel(makeReport([SUGGESTION]))

        await act(user)
        await user.click(screen.getByTestId('inbox-report-ask-ai-submit'))

        expect(questionSourceOf()).toBe(expected)
        expect(discussReport).toHaveBeenCalledTimes(1)
    })

    it('carries the suggestion count so a typed question can be read in context', async () => {
        // A `typed` question on a report that offered nothing is not evidence against suggestions, so
        // the count is what makes the source readable.
        const user = await openPanel(makeReport())

        await user.type(screen.getByRole('textbox'), 'Who is affected?')
        await user.click(screen.getByTestId('inbox-report-ask-ai-submit'))

        const { extra } = jest.mocked(captureInboxReportAction).mock.calls[0][0]
        expect(extra).toEqual({ question_source: 'typed', suggestion_count: 0 })
    })

    it.each([
        ['a report without any', makeReport()],
        // A stored suggestion can be an action request, and on an answer-only status the run would
        // merely answer it — offering the row would invite an action that won't happen.
        [
            'an answer-only report, whose stored suggestions are hidden',
            { ...makeReport([SUGGESTION]), status: SignalReportStatus.RESOLVED },
        ],
    ])('renders no suggestion rows for %s', async (_name, report) => {
        await openPanel(report)

        expect(screen.queryByTestId('inbox-report-ask-ai-suggestion')).not.toBeInTheDocument()
    })

    it('does not invite actions where the kickoff wrapper would only answer', async () => {
        // The kickoff prompt pins the agent to answering on a resolved report, so a placeholder
        // saying "tell AI what to do next" would promise an action the run won't carry out.
        await openPanel({ ...makeReport(), status: SignalReportStatus.RESOLVED })

        expect(screen.getByPlaceholderText('Ask a question about this report')).toBeInTheDocument()
    })
})
