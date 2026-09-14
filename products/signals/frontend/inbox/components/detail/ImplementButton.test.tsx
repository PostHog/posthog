import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { makeReport } from '../../__mocks__/inboxMocks'
import { captureInboxReportAction } from '../../inboxAnalytics'
import { inboxTaskKickoffLogic } from '../../inboxTaskKickoffLogic'
import { ImplementButton } from './ImplementButton'

jest.mock('../../inboxAnalytics', () => ({
    ...jest.requireActual('../../inboxAnalytics'),
    captureInboxReportAction: jest.fn(),
}))

jest.mock('lib/utils/copyToClipboard', () => ({
    copyToClipboard: jest.fn().mockResolvedValue(true),
}))

// The shared factory mints a fresh report id per call, and the assertions read it back.
const report = (overrides: Parameters<typeof makeReport>[0] = {}): ReturnType<typeof makeReport> =>
    makeReport({ id: 'report-1', title: 'Exceptions spiked', summary: 'summary', ...overrides })

describe('ImplementButton', () => {
    let createPrFromReport: jest.Mock
    // Holds the report's artefact log — and so its task list — unresolved, which is the pane's cold load.
    let releaseArtefacts: () => void

    beforeEach(() => {
        releaseArtefacts = () => {}
        const artefacts = new Promise<void>((resolve) => {
            releaseArtefacts = resolve
        })
        useMocks({
            get: {
                '/api/projects/:team_id/signals/reports/:id/artefacts/': async () => {
                    await artefacts
                    return { results: [] }
                },
                '/api/projects/:team_id/signals/reports/:id/signals/': { signals: [] },
                '/api/projects/:team_id/signals/reports/available_reviewers/': [],
            },
        })
        initKeaTests()
        inboxTaskKickoffLogic.mount()
        createPrFromReport = jest.fn()
        jest.spyOn(inboxTaskKickoffLogic.actions, 'createPrFromReport').mockImplementation(createPrFromReport)
        jest.mocked(captureInboxReportAction).mockClear()
        jest.mocked(copyToClipboard).mockClear()
    })

    afterEach(() => {
        releaseArtefacts()
        cleanup()
        jest.restoreAllMocks()
    })

    async function openMenu(): Promise<ReturnType<typeof userEvent.setup>> {
        const user = userEvent.setup()
        render(<ImplementButton report={report()} />)
        await user.click(screen.getByTestId('inbox-report-create-pr-steer'))
        await waitFor(() => expect(screen.getByText('Implement with PostHog')).toBeInTheDocument())
        return user
    }

    it('starts a PostHog agent from the main action', async () => {
        const user = userEvent.setup()
        render(<ImplementButton report={report()} />)

        await user.click(screen.getByTestId('inbox-report-create-pr'))

        expect(createPrFromReport).toHaveBeenCalledWith(expect.objectContaining({ id: 'report-1' }), undefined)
        expect(jest.mocked(captureInboxReportAction).mock.calls[0][0].extra).toEqual({ has_feedback: false })
    })

    it('opens both implementation options without starting work', async () => {
        await openMenu()

        expect(screen.getByText('Implement with PostHog')).toBeInTheDocument()
        expect(screen.getByText('Copy prompt for your agent')).toBeInTheDocument()
        expect(createPrFromReport).not.toHaveBeenCalled()
        expect(copyToClipboard).not.toHaveBeenCalled()
    })

    it.each([
        [
            'the PostHog button',
            (user: ReturnType<typeof userEvent.setup>) =>
                user.click(screen.getByTestId('inbox-report-create-pr-submit')),
        ],
        ['Enter', (user: ReturnType<typeof userEvent.setup>) => user.keyboard('{Enter}')],
    ])('passes steering instructions with %s', async (_method, submit) => {
        const user = await openMenu()

        await user.type(
            screen.getByPlaceholderText('Add instructions for the PostHog agent (optional)'),
            '  Keep the existing API  '
        )
        await submit(user)

        expect(createPrFromReport).toHaveBeenCalledWith(
            expect.objectContaining({ id: 'report-1' }),
            'Keep the existing API'
        )
        expect(jest.mocked(captureInboxReportAction).mock.calls[0][0].extra).toEqual({ has_feedback: true })
    })

    // The run the server refuses for is usually already running when the pane opens, and the task
    // list takes several requests to arrive. An enabled button in that window is the press that
    // comes back as an error toast.
    it('stays disabled on a cold load of a report a run already holds', async () => {
        const user = userEvent.setup()
        render(
            <ImplementButton
                report={report({
                    assignee: {
                        kind: 'task',
                        task_id: 'task-1',
                        claim_id: null,
                        user: null,
                        agent: null,
                        claimed_at: null,
                    },
                })}
            />
        )

        const button = screen.getByTestId('inbox-report-create-pr')
        expect(button).toHaveAttribute('aria-disabled', 'true')
        await user.click(button)
        expect(createPrFromReport).not.toHaveBeenCalled()

        // The loaded task list is the better answer and takes the gate back: this one holds no run,
        // so the report's own claim stops standing in for it.
        releaseArtefacts()
        await waitFor(() => expect(button).toHaveAttribute('aria-disabled', 'false'))
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
