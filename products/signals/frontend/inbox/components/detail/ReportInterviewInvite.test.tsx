import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { act, cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { FEATURE_FLAGS } from 'lib/constants'
import * as featureFlagModule from 'lib/logic/featureFlagLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { userLogic } from 'scenes/userLogic'

import { initKeaTests } from '~/test/init'

import { captureInboxInterviewInvite } from '../../inboxAnalytics'
import { openDismissReportDialog } from '../shell/DismissReportDialog'
import { openResolveReportDialog } from '../shell/ResolveReportDialog'
import { ReportInterviewInvite } from './ReportInterviewInvite'

jest.mock('../../inboxAnalytics', () => ({
    ...jest.requireActual('../../inboxAnalytics'),
    captureInboxInterviewInvite: jest.fn(),
}))

describe('ReportInterviewInvite', () => {
    const user = userEvent.setup()
    const bookingText = 'Book a 30-minute chat about Inbox'

    beforeEach(() => {
        localStorage.clear()
        initKeaTests()
        featureFlagLogic.mount()
        userLogic.mount()
        userLogic.actions.loadUserSuccess(MOCK_DEFAULT_USER)
        jest.spyOn(featureFlagModule, 'getFeatureFlagPayload').mockReturnValue({
            booking_url: 'https://cal.com/example/interview',
        })
        jest.mocked(captureInboxInterviewInvite).mockClear()
    })

    afterEach(() => {
        cleanup()
        jest.restoreAllMocks()
    })

    it('shows a dismissible booking link only when the flag has a Cal.com URL', async () => {
        const { rerender } = render(<ReportInterviewInvite />)
        expect(screen.queryByText('Want some free PostHog merch?')).not.toBeInTheDocument()

        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.INBOX_INTERVIEW_INVITE], {
            [FEATURE_FLAGS.INBOX_INTERVIEW_INVITE]: true,
        })
        rerender(<ReportInterviewInvite />)

        expect(await screen.findByText('Want some free PostHog merch?')).toBeInTheDocument()
        const link = (await screen.findByText(bookingText)).closest('a')
        expect(link).toHaveAttribute('href', 'https://cal.com/example/interview')
        await waitFor(() => expect(captureInboxInterviewInvite).toHaveBeenCalledWith('shown'))

        await user.click(screen.getByLabelText('Dismiss interview invite'))
        expect(screen.queryByText(bookingText)).not.toBeInTheDocument()
        expect(captureInboxInterviewInvite).toHaveBeenCalledWith('dismissed')
    })

    it('rejects a non-HTTPS booking URL', () => {
        jest.mocked(featureFlagModule.getFeatureFlagPayload).mockReturnValue({ booking_url: 'javascript:alert(1)' })
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.INBOX_INTERVIEW_INVITE], {
            [FEATURE_FLAGS.INBOX_INTERVIEW_INVITE]: true,
        })

        render(<ReportInterviewInvite />)

        expect(screen.queryByText(bookingText)).not.toBeInTheDocument()
        expect(captureInboxInterviewInvite).not.toHaveBeenCalled()
    })

    it('shows the invite only once when it is ignored', async () => {
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.INBOX_INTERVIEW_INVITE], {
            [FEATURE_FLAGS.INBOX_INTERVIEW_INVITE]: true,
        })

        render(<ReportInterviewInvite />)
        expect(await screen.findByText(bookingText)).toBeInTheDocument()
        await waitFor(() => expect(captureInboxInterviewInvite).toHaveBeenCalledWith('shown'))
        cleanup()

        render(<ReportInterviewInvite />)
        expect(screen.queryByText(bookingText)).not.toBeInTheDocument()
        expect(captureInboxInterviewInvite).toHaveBeenCalledTimes(1)
    })

    it('records the booking click and hides the invite', async () => {
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.INBOX_INTERVIEW_INVITE], {
            [FEATURE_FLAGS.INBOX_INTERVIEW_INVITE]: true,
        })
        render(<ReportInterviewInvite />)

        await user.click(screen.getByText(bookingText))

        expect(captureInboxInterviewInvite).toHaveBeenCalledWith('clicked')
        expect(screen.queryByText(bookingText)).not.toBeInTheDocument()
    })

    it.each([
        ['resolve', () => openResolveReportDialog({ reportTitle: 'Example report', onConfirm: jest.fn() })],
        ['dismiss', () => openDismissReportDialog({ reportTitle: 'Example report', onConfirm: jest.fn() })],
    ])('shows the invite in a single-report %s dialog', async (_name, openDialog) => {
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.INBOX_INTERVIEW_INVITE], {
            [FEATURE_FLAGS.INBOX_INTERVIEW_INVITE]: true,
        })

        act(openDialog)

        expect(await screen.findByText(bookingText)).toBeInTheDocument()
        const dialog = screen.getByRole('dialog')
        await user.click(within(dialog).getByText('Cancel'))
        await waitFor(() => expect(dialog).not.toBeInTheDocument())
    })

    it.each([
        {
            name: 'resolve booking link',
            reason: 'Implemented manually',
            submitLabel: 'Resolve report',
            control: 'link',
            openDialog: (onConfirm: jest.Mock) => openResolveReportDialog({ reportTitle: 'Example report', onConfirm }),
        },
        {
            name: 'resolve invite dismissal',
            reason: 'Implemented manually',
            submitLabel: 'Resolve report',
            control: 'dismiss',
            openDialog: (onConfirm: jest.Mock) => openResolveReportDialog({ reportTitle: 'Example report', onConfirm }),
        },
        {
            name: 'dismiss booking link',
            reason: 'Already fixed',
            submitLabel: 'Dismiss & teach the agent',
            control: 'link',
            openDialog: (onConfirm: jest.Mock) => openDismissReportDialog({ reportTitle: 'Example report', onConfirm }),
        },
        {
            name: 'dismiss invite dismissal',
            reason: 'Already fixed',
            submitLabel: 'Dismiss & teach the agent',
            control: 'dismiss',
            openDialog: (onConfirm: jest.Mock) => openDismissReportDialog({ reportTitle: 'Example report', onConfirm }),
        },
    ])(
        'does not submit the report when Enter activates the $name',
        async ({ reason, submitLabel, control, openDialog }) => {
            featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.INBOX_INTERVIEW_INVITE], {
                [FEATURE_FLAGS.INBOX_INTERVIEW_INVITE]: true,
            })
            const onConfirm = jest.fn()
            act(() => openDialog(onConfirm))

            const dialog = screen.getByRole('dialog')
            await user.click(within(dialog).getByText(reason))
            await waitFor(() => expect(within(dialog).getByText(submitLabel).closest('button')).not.toBeDisabled())

            const inviteControl =
                control === 'link'
                    ? within(dialog).getByText(bookingText).closest('a')
                    : within(dialog).getByLabelText('Dismiss interview invite')
            inviteControl?.focus()
            await user.keyboard('{Enter}')

            expect(onConfirm).not.toHaveBeenCalled()
            expect(dialog).toBeInTheDocument()
            await user.click(within(dialog).getByText('Cancel'))
            await waitFor(() => expect(dialog).not.toBeInTheDocument())
        }
    )

    it.each([
        ['bulk resolve', () => openResolveReportDialog({ selectedCount: 2, onConfirm: jest.fn() })],
        [
            'hotkey dismiss',
            () => openDismissReportDialog({ reportTitle: 'Example report', hotkeys: true, onConfirm: jest.fn() }),
        ],
    ])('keeps the invite out of %s', async (_name, openDialog) => {
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.INBOX_INTERVIEW_INVITE], {
            [FEATURE_FLAGS.INBOX_INTERVIEW_INVITE]: true,
        })

        act(openDialog)

        expect(screen.queryByText(bookingText)).not.toBeInTheDocument()
        const dialog = screen.getByRole('dialog')
        await user.click(within(dialog).getByText('Cancel'))
        await waitFor(() => expect(dialog).not.toBeInTheDocument())
    })
})
