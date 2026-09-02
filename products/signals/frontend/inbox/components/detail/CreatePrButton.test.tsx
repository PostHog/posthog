import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { initKeaTests } from '~/test/init'

import { captureInboxReportAction } from '../../inboxAnalytics'
import { inboxTaskKickoffLogic } from '../../inboxTaskKickoffLogic'
import { SignalReport, SignalReportStatus } from '../../types'
import { CreatePrButton } from './CreatePrButton'

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

describe('CreatePrButton', () => {
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

    async function openPopover(): Promise<ReturnType<typeof userEvent.setup>> {
        const user = userEvent.setup()
        render(<CreatePrButton report={makeReport()} />)
        await user.click(screen.getByText('Create PR'))
        return user
    }

    it('passes a typed note to the agent and marks the action as steered', async () => {
        // The whole feature: a note in the box has to reach the prompt, or steering does nothing. The
        // `has_feedback` flag is how we compare steered runs against unsteered ones.
        const user = await openPopover()

        await user.type(screen.getByRole('textbox'), '  Put the fix behind a flag.  ')
        await user.click(screen.getByTestId('inbox-report-create-pr-submit'))

        expect(createPrFromReport).toHaveBeenCalledWith(
            expect.objectContaining({ id: 'report-1' }),
            'Put the fix behind a flag.'
        )
        expect(jest.mocked(captureInboxReportAction).mock.calls[0][0].extra).toEqual({ has_feedback: true })
    })

    it('fires with no note when the box is empty, exactly as the old button did', async () => {
        // Empty is the common case and must stay a one-press action, with no feedback appended.
        const user = await openPopover()

        await user.click(screen.getByTestId('inbox-report-create-pr-submit'))

        expect(createPrFromReport).toHaveBeenCalledWith(expect.objectContaining({ id: 'report-1' }), undefined)
        expect(jest.mocked(captureInboxReportAction).mock.calls[0][0].extra).toEqual({ has_feedback: false })
    })
})
