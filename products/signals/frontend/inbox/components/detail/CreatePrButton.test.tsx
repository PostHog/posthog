import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
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

    async function openNoteBox(): Promise<ReturnType<typeof userEvent.setup>> {
        const user = userEvent.setup()
        render(<CreatePrButton report={makeReport()} />)
        await user.click(screen.getByTestId('inbox-report-create-pr-steer'))
        await waitFor(() => expect(screen.getByRole('textbox')).toHaveFocus())
        return user
    }

    it('starts an unsteered run from the main half, with no note box in the way', async () => {
        // The point of the split: the common case is one press. A regression that routes the main
        // half back into the popover shows up here as a missing call.
        const user = userEvent.setup()
        render(<CreatePrButton report={makeReport()} />)

        await user.click(screen.getByTestId('inbox-report-create-pr'))

        expect(createPrFromReport).toHaveBeenCalledWith(expect.objectContaining({ id: 'report-1' }), undefined)
        expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
        expect(jest.mocked(captureInboxReportAction).mock.calls[0][0].extra).toEqual({ has_feedback: false })
    })

    it('passes a typed note to the agent and marks the action as steered', async () => {
        // The whole feature: a note in the box has to reach the prompt, or steering does nothing. The
        // `has_feedback` flag is how we compare steered runs against unsteered ones.
        const user = await openNoteBox()

        await user.type(screen.getByRole('textbox'), '  Put the fix behind a flag.  ')
        await user.click(screen.getByTestId('inbox-report-create-pr-submit'))

        expect(createPrFromReport).toHaveBeenCalledWith(
            expect.objectContaining({ id: 'report-1' }),
            'Put the fix behind a flag.'
        )
        expect(jest.mocked(captureInboxReportAction).mock.calls[0][0].extra).toEqual({ has_feedback: true })
    })

    it('submits the note on Enter without moving focus first', async () => {
        // Guards the two halves of the shortcut at once: the box takes focus when it opens, and plain
        // Enter submits. `onPressCmdEnter` would leave both typing and Enter with nothing to act on.
        const user = await openNoteBox()

        await user.keyboard('Backend only.{Enter}')

        expect(createPrFromReport).toHaveBeenCalledWith(expect.objectContaining({ id: 'report-1' }), 'Backend only.')
    })
})
