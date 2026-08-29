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
})
