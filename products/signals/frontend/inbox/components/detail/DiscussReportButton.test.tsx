import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { SidePanelTab } from '~/types'

import { attachedContextLogic } from 'products/posthog_ai/frontend/api/logics'

import { captureInboxReportAction } from '../../inboxAnalytics'
import {
    FIX_CI_REQUEST,
    inboxTaskKickoffLogic,
    MERGE_PR_REQUEST,
    REPORT_AI_PANEL,
    REPORT_DISCUSSION_QUESTION_MAX_LENGTH,
} from '../../inboxTaskKickoffLogic'
import { inboxReportDetailLogic } from '../../logics/inboxReportDetailLogic'
import { SignalReport, SignalReportStatus } from '../../types'
import { DiscussReportButton } from './DiscussReportButton'
import { ReportDiscussionComposer } from './ReportDiscussionComposer'

jest.mock('../../inboxAnalytics', () => ({
    ...jest.requireActual('../../inboxAnalytics'),
    captureInboxReportAction: jest.fn(),
}))

const SUGGESTION = 'Which teams are hitting this exception the most?'

function withPullRequest(
    report: SignalReport,
    state: 'open' | 'merged',
    reviewDecision: 'approved' | 'review_required'
): SignalReport {
    return {
        ...report,
        status: SignalReportStatus.IN_PROGRESS,
        pull_requests: [
            {
                id: 'pr-1',
                url: 'https://github.com/org/repo/pull/1',
                state,
                merged: state === 'merged',
                review_decision: reviewDecision,
                merged_at: null,
                claim_id: null,
                attached_at: null,
                attached_by: null,
            },
        ],
    }
}

function makeReport(suggestedPrompts?: string[]): SignalReport {
    return {
        id: 'report-1',
        title: 'Exceptions spiked',
        summary: 'summary',
        status: SignalReportStatus.READY,
        total_weight: 0,
        signal_count: 1,
        artefact_count: 0,
        is_suggested_reviewer: false,
        created_at: '2026-06-11T10:00:00Z',
        updated_at: '2026-06-11T10:00:00Z',
        suggested_prompts: suggestedPrompts,
    } satisfies SignalReport
}

describe('DiscussReportButton', () => {
    let checksConclusion: 'failure' | 'success' | null = null
    let discussReport: jest.Mock

    beforeEach(() => {
        checksConclusion = null
        useMocks({
            get: {
                '/api/projects/:team_id/signals/reports/:id/signals/': { signals: [] },
                '/api/projects/:team_id/signals/reports/:id/pr_checks/': () => [
                    200,
                    {
                        checks: checksConclusion
                            ? [{ name: 'backend', status: 'completed', conclusion: checksConclusion, url: null }]
                            : [],
                    },
                ],
                '/api/projects/:team_id/signals/reports/:id/pr_comments/': { comments: [] },
                '/api/projects/:team_id/signals/reports/available_reviewers/': [],
            },
        })
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

    it('shows multiple report suggestions in the current suggestions menu', async () => {
        const secondSuggestion = 'Which release introduced the exception?'
        const user = await openPanel(makeReport([SUGGESTION, secondSuggestion]))

        await user.click(screen.getByText('Report suggestions'))

        expect(screen.getAllByTestId('inbox-report-ask-ai-suggestion')).toHaveLength(2)
        await user.click(screen.getByText(secondSuggestion))
        expect(discussReport).toHaveBeenCalledWith(
            expect.objectContaining({ id: 'report-1' }),
            'https://app/report-1',
            secondSuggestion
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

    it('sends a typed question with Enter from the standard sidebar input', async () => {
        const user = await openPanel(makeReport())

        await user.type(screen.getByTestId('max-chat-input'), 'Who is affected?')
        await user.keyboard('{Enter}')

        expect(discussReport).toHaveBeenCalledTimes(1)
        expect(discussReport).toHaveBeenCalledWith(
            expect.objectContaining({ id: 'report-1' }),
            'https://app/report-1',
            'Who is affected?'
        )
    })

    it('keeps the report context attached', async () => {
        attachedContextLogic.actions.registerContext('report', [
            {
                type: 'signal_report',
                key: 'report-1',
                label: 'Report: Exceptions spiked',
                dismissible: false,
            },
        ])
        const user = await openPanel(makeReport())

        await user.click(screen.getByText('Report: Exceptions spiked'))

        expect(attachedContextLogic.values.contextItems).toEqual([
            expect.objectContaining({ type: 'signal_report', key: 'report-1' }),
        ])
    })

    it('blocks another submission while the report task is starting', async () => {
        jest.spyOn(inboxTaskKickoffLogic.selectors, 'isCreatingPr').mockReturnValue(true)
        const user = userEvent.setup()
        render(<ReportDiscussionComposer report={makeReport([SUGGESTION])} reportUrl="https://app/report-1" />)
        fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Who is affected?' } })

        expect(screen.getByTestId('inbox-report-ask-ai-submit')).toHaveAttribute('aria-disabled', 'true')
        fireEvent.keyDown(screen.getByRole('textbox'), { key: 'Enter', code: 'Enter' })
        await user.click(screen.getByText(SUGGESTION))

        expect(discussReport).not.toHaveBeenCalled()
    })

    it('sends a slash command as plain text instead of treating it as a command', async () => {
        const user = await openPanel(makeReport())

        await user.type(screen.getByTestId('max-chat-input'), '/usage')
        await user.keyboard('{Enter}')

        expect(discussReport).toHaveBeenCalledWith(
            expect.objectContaining({ id: 'report-1' }),
            'https://app/report-1',
            '/usage'
        )
    })

    it('does not offer slash commands it cannot run', async () => {
        await openPanel(makeReport())

        expect(screen.queryByText(/for commands/)).not.toBeInTheDocument()
    })

    it('blocks a question longer than the task API accepts', async () => {
        // The question field is capped server-side, so sending an over-long one only ever comes back
        // as a bare 400 with no task started.
        render(<ReportDiscussionComposer report={makeReport()} reportUrl="https://app/report-1" />)
        fireEvent.change(screen.getByRole('textbox'), {
            target: { value: 'x'.repeat(REPORT_DISCUSSION_QUESTION_MAX_LENGTH + 1) },
        })

        await waitFor(() =>
            expect(screen.getByTestId('inbox-report-ask-ai-submit')).toHaveAttribute('aria-disabled', 'true')
        )
        expect(screen.getByText('4,001 / 4,000')).toBeInTheDocument()
        fireEvent.keyDown(screen.getByRole('textbox'), { key: 'Enter', code: 'Enter' })

        expect(discussReport).not.toHaveBeenCalled()
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

    it('sends Get it merged with the merge intent in one click from the Ask AI menu', async () => {
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.INBOX_GET_IT_MERGED], {
            [FEATURE_FLAGS.INBOX_GET_IT_MERGED]: true,
        })
        const user = userEvent.setup()
        render(
            <DiscussReportButton
                report={withPullRequest(makeReport(), 'open', 'approved')}
                reportUrl="https://app/report-1"
            />
        )

        await user.click(screen.getByTestId('inbox-report-ask-ai-actions'))
        await user.click(screen.getByText('Get it merged'))

        expect(discussReport).toHaveBeenCalledWith(
            expect.objectContaining({ id: 'report-1' }),
            'https://app/report-1',
            MERGE_PR_REQUEST,
            undefined,
            'merge_pr',
            undefined
        )
        expect(jest.mocked(captureInboxReportAction).mock.calls[0][0].extra).toEqual({
            question_source: 'suggested',
            suggestion_count: 1,
            question_intent: 'merge_pr',
        })
    })

    it.each([
        ['the PR needs review', true, withPullRequest(makeReport(), 'open', 'review_required')],
        ['the PR is already merged', true, withPullRequest(makeReport(), 'merged', 'approved')],
        ['the flag is off', false, withPullRequest(makeReport(), 'open', 'approved')],
    ])('does not offer Get it merged when %s', async (_name, flagEnabled, report) => {
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.INBOX_GET_IT_MERGED], {
            [FEATURE_FLAGS.INBOX_GET_IT_MERGED]: flagEnabled,
        })
        const user = userEvent.setup()
        render(<DiscussReportButton report={report} reportUrl="https://app/report-1" />)

        await user.click(screen.getByTestId('inbox-report-ask-ai-actions'))
        expect(screen.getByTestId('inbox-report-ask-ai-quick-submit')).toBeInTheDocument()
        expect(screen.queryByText('Get it merged')).not.toBeInTheDocument()
    })

    async function setChecks(report: SignalReport, conclusion: 'failure' | 'success'): Promise<void> {
        checksConclusion = conclusion
        const logic = inboxReportDetailLogic({ reportId: report.id, report })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    }

    it('sends Make it green with the fix CI intent when CI fails on an unapproved PR', async () => {
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.INBOX_GET_IT_MERGED], {
            [FEATURE_FLAGS.INBOX_GET_IT_MERGED]: true,
        })
        const report = withPullRequest(makeReport(), 'open', 'review_required')
        await setChecks(report, 'failure')
        const user = userEvent.setup()
        render(<DiscussReportButton report={report} reportUrl="https://app/report-1" />)

        await user.click(screen.getByTestId('inbox-report-ask-ai-actions'))
        expect(screen.queryByText('Get it merged')).not.toBeInTheDocument()
        await user.click(screen.getByText('Make it green'))

        expect(discussReport).toHaveBeenCalledWith(
            expect.objectContaining({ id: 'report-1' }),
            'https://app/report-1',
            FIX_CI_REQUEST,
            undefined,
            'fix_ci',
            'https://github.com/org/repo/pull/1'
        )
        expect(jest.mocked(captureInboxReportAction).mock.calls[0][0].extra).toEqual({
            question_source: 'suggested',
            suggestion_count: 1,
            question_intent: 'fix_ci',
        })
    })

    it.each([
        ['CI passes', 'success', 'open'],
        ['the PR is already merged', 'failure', 'merged'],
    ] as const)('does not offer Make it green when %s', async (_name, conclusion, state) => {
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.INBOX_GET_IT_MERGED], {
            [FEATURE_FLAGS.INBOX_GET_IT_MERGED]: true,
        })
        const report = withPullRequest(makeReport(), state, 'review_required')
        await setChecks(report, conclusion)
        const user = userEvent.setup()
        render(<DiscussReportButton report={report} reportUrl="https://app/report-1" />)

        await user.click(screen.getByTestId('inbox-report-ask-ai-actions'))
        expect(screen.queryByText('Make it green')).not.toBeInTheDocument()
    })

    it('fills the quick ask from a suggestion and sends it in the background on Enter', async () => {
        const user = userEvent.setup()
        render(<DiscussReportButton report={makeReport([SUGGESTION])} reportUrl="https://app/report-1" />)

        await user.click(screen.getByTestId('inbox-report-ask-ai-actions'))
        await user.click(screen.getByText(SUGGESTION))
        expect(discussReport).not.toHaveBeenCalled()
        await user.keyboard('{Enter}')
        await user.keyboard('{Enter}')

        expect(discussReport).toHaveBeenCalledTimes(1)
        expect(discussReport).toHaveBeenCalledWith(
            expect.objectContaining({ id: 'report-1' }),
            'https://app/report-1',
            SUGGESTION,
            undefined,
            undefined,
            undefined,
            true
        )
        expect(jest.mocked(captureInboxReportAction).mock.calls[0][0].extra).toEqual({
            question_source: 'suggested',
            suggestion_count: 1,
            launch_mode: 'background',
        })
        expect(sidePanelStateLogic.values.sidePanelOpen).toBe(false)
    })

    it('does not invite actions where the kickoff wrapper would only answer', async () => {
        // The kickoff prompt pins the agent to answering on a resolved report, so a placeholder
        // saying "tell AI what to do next" would promise an action the run won't carry out.
        await openPanel({ ...makeReport(), status: SignalReportStatus.RESOLVED })

        expect(screen.getByText(/Ask a question/)).toBeInTheDocument()
    })
})
