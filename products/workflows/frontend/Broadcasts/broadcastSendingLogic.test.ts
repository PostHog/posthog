import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { expectLogic } from 'kea-test-utils'
import { createElement } from 'react'

import { projectLogic } from 'scenes/projectLogic'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { broadcastSendingLogic } from './broadcastSendingLogic'

const { ToastContainer, toast } = jest.requireActual('react-toastify')

const NOT_PAUSED = {
    email_sending_paused_at: null,
    email_sending_paused_reason: '',
    email_sending_paused_by: '',
    email_sending_pause_requires_support: false,
}
const AUTO_PAUSED = {
    email_sending_paused_at: '2026-11-01T09:00:00Z',
    email_sending_paused_reason: 'Too many spam complaints',
    email_sending_paused_by: 'system',
    email_sending_pause_requires_support: false,
}
const STAFF_PAUSED = {
    ...AUTO_PAUSED,
    email_sending_paused_reason: 'Paused by PostHog',
    email_sending_paused_by: 'staff',
    email_sending_pause_requires_support: true,
}

describe('broadcastSendingLogic', () => {
    let server: {
        pause: typeof NOT_PAUSED | typeof AUTO_PAUSED
        queued: number | null | 'down'
        inFlightReads: string[]
        resumes: number
        resumeHeld: Promise<void>
    }

    beforeEach(() => {
        server = { pause: NOT_PAUSED, queued: 3, inFlightReads: [], resumes: 0, resumeHeld: Promise.resolve() }
        useMocks({
            get: {
                '/api/projects/:team_id/hog_flows/:id/': ({ params }) => [
                    200,
                    { id: params.id, name: 'Spring sale', status: 'active', ...server.pause },
                ],
                '/api/projects/:team_id/hog_flows/:id/in_flight/': ({ params }) => {
                    server.inFlightReads.push(String(params.id))
                    return server.queued === 'down'
                        ? [500, { detail: 'boom' }]
                        : [200, { count: server.queued, by_action: null, position_unknown: null }]
                },
            },
            post: {
                '/api/projects/:team_id/hog_flows/:id/resume_email_sending/': async () => {
                    server.resumes += 1
                    await server.resumeHeld
                    if (!server.pause.email_sending_paused_at) {
                        return [400, { detail: 'Email sending is not paused for this workflow.' }]
                    }
                    server.pause = NOT_PAUSED
                    return [200, { email_sending_paused: false }]
                },
            },
        })
        initKeaTests()
    })

    afterEach(() => {
        resumeKeaLoadersErrors()
        cleanup()
        toast.dismiss()
    })

    const mountSending = async (id = 'flow-1'): Promise<ReturnType<typeof broadcastSendingLogic.build>> => {
        const logic = broadcastSendingLogic({ id })
        logic.mount()
        await waitFor(() => expect(logic.values.inFlightLoading).toBe(false))
        return logic
    }

    it.each([
        { case: 'people still queued', queued: 12, expected: { stillToSend: 12, inFlightFailed: false } },
        { case: 'an empty queue', queued: 0, expected: { stillToSend: 0, inFlightFailed: false } },
        { case: 'an unreachable counter', queued: null, expected: { stillToSend: null, inFlightFailed: false } },
        { case: 'a failed request', queued: 'down' as const, expected: { stillToSend: null, inFlightFailed: true } },
    ])('reads what is still to send for this broadcast on mount, given $case', async ({ queued, expected }) => {
        silenceKeaLoadersErrors()
        server.queued = queued

        const logic = await mountSending()

        expect({
            stillToSend: logic.values.stillToSend,
            inFlightFailed: logic.values.inFlightFailed,
            reads: server.inFlightReads,
        }).toEqual({ ...expected, reads: ['flow-1'] })
    })

    it('shows the new count after a retry of a failed read', async () => {
        silenceKeaLoadersErrors()
        server.queued = 'down'
        const logic = await mountSending()
        expect(logic.values.inFlightFailed).toBe(true)

        server.queued = 7
        logic.actions.loadInFlight()
        await waitFor(() => expect(logic.values.stillToSend).toBe(7))

        expect(logic.values.inFlightFailed).toBe(false)
    })

    it.each([
        { case: 'an unsaved broadcast', id: 'new', noProject: false },
        { case: 'no current project', id: 'flow-1', noProject: true },
    ])('asks nothing of the server for $case', async ({ id, noProject }) => {
        if (noProject) {
            projectLogic.mount()
            projectLogic.actions.loadCurrentProjectSuccess(null)
        }

        const logic = await mountSending(id)
        await expectLogic(logic).toFinishAllListeners()

        expect(server.inFlightReads).toEqual([])
        expect(logic.values).toMatchObject({ stillToSend: null, inFlightFailed: false })
    })

    it.each([
        {
            case: 'not paused',
            pause: NOT_PAUSED,
            expected: { paused: false, reason: '', pausedByStaff: false, requiresSupport: false },
        },
        {
            case: 'paused for complaints',
            pause: AUTO_PAUSED,
            expected: {
                paused: true,
                reason: 'Too many spam complaints',
                pausedByStaff: false,
                requiresSupport: false,
            },
        },
        {
            case: 'paused by staff',
            pause: STAFF_PAUSED,
            expected: { paused: true, reason: 'Paused by PostHog', pausedByStaff: true, requiresSupport: true },
        },
    ])('reads the email pause off the saved broadcast when $case', async ({ pause, expected }) => {
        server.pause = pause

        const logic = await mountSending()
        await waitFor(() => expect(logic.values.broadcast).not.toBeNull())

        expect(logic.values.emailSendingPause).toEqual(expected)
    })

    it.each([
        { case: 'resumes it', resumedElsewhere: false, message: 'Email sending resumed' },
        {
            case: 'finds it already resumed',
            resumedElsewhere: true,
            message: 'Could not resume email sending. Please try again.',
        },
    ])('resumes a paused send once, after the dialog, and clears the pause when the server $case', async (row) => {
        toast.dismiss()
        render(createElement(ToastContainer))
        server.pause = AUTO_PAUSED
        let release = (): void => {}
        server.resumeHeld = new Promise((resolve) => (release = resolve))
        const logic = await mountSending()
        await waitFor(() => expect(logic.values.emailSendingPause.paused).toBe(true))

        logic.actions.resumeEmailSending()
        const confirm = await screen.findByText('Resume sending')
        expect(server.resumes).toBe(0)
        if (row.resumedElsewhere) {
            server.pause = NOT_PAUSED
        }
        fireEvent.click(confirm)
        fireEvent.click(confirm)
        await waitFor(() => expect(logic.values.resumingEmailSending).toBe(true))
        await waitFor(() => expect(screen.queryByText('Resume email sending?')).toBeNull())
        logic.actions.resumeEmailSending()
        expect(screen.queryByText('Resume email sending?')).toBeNull()

        release()
        await screen.findByText(row.message)
        await waitFor(() => expect(logic.values.emailSendingPause.paused).toBe(false))
        expect(logic.values.resumingEmailSending).toBe(false)
        expect(server.resumes).toBe(1)
    })

    it('re-reads the queue and the pause every 30 seconds until nothing is left, and stops on unmount', async () => {
        jest.useFakeTimers()
        try {
            server.queued = 5
            server.pause = AUTO_PAUSED
            const logic = broadcastSendingLogic({ id: 'flow-1' })
            logic.mount()
            await jest.advanceTimersByTimeAsync(0)
            expect(logic.values).toMatchObject({ stillToSend: 5, emailSendingPause: { paused: true } })

            server.queued = 2
            server.pause = NOT_PAUSED
            await jest.advanceTimersByTimeAsync(30_000)
            expect(logic.values).toMatchObject({ stillToSend: 2, emailSendingPause: { paused: false } })

            server.queued = 0
            await jest.advanceTimersByTimeAsync(30_000)
            server.queued = 4
            await jest.advanceTimersByTimeAsync(60_000)
            expect(logic.values.stillToSend).toBe(0)
            expect(server.inFlightReads).toHaveLength(3)

            logic.actions.loadInFlight()
            await jest.advanceTimersByTimeAsync(0)
            logic.unmount()
            await jest.advanceTimersByTimeAsync(60_000)
            expect(server.inFlightReads).toHaveLength(4)
        } finally {
            jest.useRealTimers()
        }
    })
})
