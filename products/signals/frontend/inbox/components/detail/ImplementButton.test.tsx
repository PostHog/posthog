import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { initKeaTests } from '~/test/init'

import { captureInboxReportAction } from '../../inboxAnalytics'
import { inboxTaskKickoffLogic } from '../../inboxTaskKickoffLogic'
import { SignalReport, SignalReportStatus } from '../../types'
import { ImplementButton } from './ImplementButton'

jest.mock('../../inboxAnalytics', () => ({
    ...jest.requireActual('../../inboxAnalytics'),
    captureInboxReportAction: jest.fn(),
}))

jest.mock('lib/utils/copyToClipboard', () => ({
    copyToClipboard: jest.fn().mockResolvedValue(true),
}))

function makeReport(): SignalReport {
    return {
        id: 'report-1',
        title: 'Exceptions spiked',
        summary: 'summary',
        status: SignalReportStatus.READY,
        total_weight: 0,
        signal_count: 1,
        artefact_count: 0,
        is_suggested_reviewer: false,
        implementation_pr_state: null,
        work_state: 'unclaimed',
        assignee: null,
        created_at: '2026-06-11T10:00:00Z',
        updated_at: '2026-06-11T10:00:00Z',
    } satisfies SignalReport
}

describe('ImplementButton', () => {
    let createPrFromReport: jest.Mock

    beforeEach(() => {
        initKeaTests()
        inboxTaskKickoffLogic.mount()
        createPrFromReport = jest.fn()
        jest.spyOn(inboxTaskKickoffLogic.actions, 'createPrFromReport').mockImplementation(createPrFromReport)
        jest.mocked(captureInboxReportAction).mockClear()
        jest.mocked(copyToClipboard).mockClear()
    })

    afterEach(() => {
        cleanup()
        jest.restoreAllMocks()
    })

    async function openMenu(): Promise<ReturnType<typeof userEvent.setup>> {
        const user = userEvent.setup()
        render(<ImplementButton report={makeReport()} />)
        await user.click(screen.getByTestId('inbox-report-create-pr-steer'))
        await waitFor(() => expect(screen.getByText('Use your agent')).toBeInTheDocument())
        return user
    }

    it('starts a PostHog agent from the main action', async () => {
        const user = userEvent.setup()
        render(<ImplementButton report={makeReport()} />)

        await user.click(screen.getByTestId('inbox-report-create-pr'))

        expect(createPrFromReport).toHaveBeenCalledWith(expect.objectContaining({ id: 'report-1' }), undefined)
        expect(jest.mocked(captureInboxReportAction).mock.calls[0][0].extra).toEqual({ has_feedback: false })
    })

    it('opens the external agent option without starting work', async () => {
        await openMenu()

        expect(screen.getByText('Use your agent')).toBeInTheDocument()
        expect(createPrFromReport).not.toHaveBeenCalled()
        expect(copyToClipboard).not.toHaveBeenCalled()
    })

    it('copies a prompt that claims the report and attaches the finished pull request', async () => {
        const user = await openMenu()

        await user.click(screen.getByTestId('inbox-report-copy-implementation-prompt'))

        const prompt = jest.mocked(copyToClipboard).mock.calls[0][0]
        expect(prompt).toContain('report ID: report-1')
        expect(prompt).toContain('inbox-report-artefacts-list')
        expect(prompt).toContain('claim the report with inbox-reports-claim')
        expect(prompt).toContain('pr_url to attach it')
        expect(prompt).toContain('release=true')
        expect(copyToClipboard).toHaveBeenCalledWith(prompt, 'implementation prompt')
        expect(captureInboxReportAction).toHaveBeenCalledWith(
            expect.objectContaining({ actionType: 'copy_implementation_prompt' })
        )
    })
})
