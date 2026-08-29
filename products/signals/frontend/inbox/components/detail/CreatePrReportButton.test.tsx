import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { IconPullRequest } from '@posthog/icons'

import { initKeaTests } from '~/test/init'

import { captureInboxReportAction } from '../../inboxAnalytics'
import { inboxTaskKickoffLogic } from '../../inboxTaskKickoffLogic'
import { SignalReport, SignalReportStatus } from '../../types'
import { CreatePrReportButton } from './CreatePrReportButton'
import { ReportDetailAction } from './ReportDetailActions'

jest.mock('../../inboxAnalytics', () => ({
    ...jest.requireActual('../../inboxAnalytics'),
    captureInboxReportAction: jest.fn(),
}))

function makeReport(): SignalReport {
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
    } satisfies SignalReport
}

const ACTION: ReportDetailAction = {
    key: 'create-pr',
    label: 'Create PR',
    icon: <IconPullRequest />,
    onClick: jest.fn(),
}

describe('CreatePrReportButton', () => {
    let createPrFromReport: jest.Mock

    beforeEach(() => {
        initKeaTests()
        inboxTaskKickoffLogic.mount()
        createPrFromReport = jest.fn()
        jest.spyOn(inboxTaskKickoffLogic.actions, 'createPrFromReport').mockImplementation(createPrFromReport)
        jest.mocked(captureInboxReportAction).mockClear()
    })

    afterEach(() => {
        cleanup()
        jest.restoreAllMocks()
    })

    it.each([
        // An empty submit must fire the task exactly as a plain click did before the note existed:
        // undefined feedback, and no steering note recorded.
        ['no note', undefined, undefined, false],
        // A note is trimmed and threaded through to the run, so the agent gets the steering text.
        ['a note', '  put this behind a flag  ', 'put this behind a flag', true],
    ])('creates the PR with %s', async (_name, typed, expectedFeedback, expectedHasFeedback) => {
        const report = makeReport()
        const user = userEvent.setup()
        render(<CreatePrReportButton report={report} action={ACTION} />)

        await user.click(screen.getByText('Create PR'))
        if (typed) {
            await user.type(screen.getByRole('textbox'), typed)
        }
        await user.click(screen.getByTestId('inbox-report-create-pr-submit'))

        expect(createPrFromReport).toHaveBeenCalledTimes(1)
        expect(createPrFromReport).toHaveBeenCalledWith(report, expectedFeedback)
        const { actionType, extra } = jest.mocked(captureInboxReportAction).mock.calls[0][0]
        expect(actionType).toBe('create_pr')
        expect(extra).toEqual({ has_feedback: expectedHasFeedback })
    })

    it('re-checks the live-task gate on submit, even via Cmd/Ctrl+Enter', async () => {
        const report = makeReport()
        const user = userEvent.setup()
        const { rerender } = render(<CreatePrReportButton report={report} action={ACTION} />)

        await user.click(screen.getByText('Create PR'))
        // With the action enabled, Cmd/Ctrl+Enter submits — this also proves the key path is wired,
        // so the assertion below can't pass just because the combo never fired.
        await user.type(screen.getByRole('textbox'), 'put this behind a flag{Control>}{Enter}{/Control}')
        expect(createPrFromReport).toHaveBeenCalledTimes(1)

        // Polling then picks up a PR task created elsewhere (autostart, another tab, another user)
        // and disables the action while the popover is still open. Cmd/Ctrl+Enter bypasses the now
        // disabled button, so the handler must refuse the second request the server would reject.
        const disabledAction: ReportDetailAction = {
            ...ACTION,
            disabledReason: 'A PR task already exists for this report. Open it in the task log to continue.',
        }
        rerender(<CreatePrReportButton report={report} action={disabledAction} />)
        await user.type(screen.getByRole('textbox'), '{Control>}{Enter}{/Control}')

        expect(createPrFromReport).toHaveBeenCalledTimes(1)
    })
})
