import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { Provider } from 'kea'
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { broadcastPerformanceLogic } from './broadcastPerformanceLogic'
import { BroadcastSendErrorAction, BroadcastSendErrorBanner } from './BroadcastSendErrorBanner'
import type { BroadcastChannel } from './broadcastsLogic'

const BROKEN_TAG = '[Action:email] Errored: Error: invalid value expression: "person.properties.nme"'
const CUT_TAG = '[Action:email] Errored: Error: invalid value expression: "person.properties.first..."'
const NO_SENDER = '[Action:email] Errored: Error: Email integration not found'
const OUTAGE = '[Action:email] Errored: Error: Failed to send email via SES: service unavailable'
const UNKNOWN = '[Action:email] Errored: Error: Something odd happened'

interface Run {
    channel?: BroadcastChannel
    sent?: number
    failed: number
    errorLogs?: (string | null)[]
    content?: string
    fixDisabledReason?: string
}

describe('BroadcastSendErrorBanner', () => {
    let run: Run
    let errorLogs: (string | null)[]
    let runCount = 0
    let clicked: string[]
    let served: string[]

    beforeEach(() => {
        clicked = []
        served = []
        initKeaTests()
        useMocks({
            post: {
                '/api/environments/:team_id/query/:kind/': async ({ request }) => {
                    const query: string = ((await request.json()) as { query: { query: string } }).query.query
                    if (query.includes('FROM log_entries')) {
                        served.push('log')
                        const log = errorLogs.length > 1 ? errorLogs.shift() : errorLogs[0]
                        return log === null
                            ? [500, { detail: 'Query timed out' }]
                            : [200, { results: log ? [[log]] : [] }]
                    }
                    if (query.includes('email_link_clicked_by_link')) {
                        served.push('links')
                        return [200, { results: [] }]
                    }
                    served.push('totals')
                    const sentMetric = run.channel === 'push' ? 'push_sent' : 'email_sent'
                    return [
                        200,
                        {
                            results: [
                                [run.sent ?? 0, sentMetric, 'step_1'],
                                [run.failed, 'failed', 'step_1'],
                                [run.failed, 'failed', ''],
                            ],
                        },
                    ]
                },
            },
        })
    })

    afterEach(() => {
        cleanup()
    })

    function renderBanner(sendRun: Run): { bannerText: () => string | null; settled: () => Promise<void> } {
        run = sendRun
        errorLogs = [...(sendRun.errorLogs ?? [])]
        const props = { runId: `run-${++runCount}`, runStartedAt: '2026-10-19T22:28:56Z', channel: sendRun.channel }
        const action = (label: string, disabledReason?: string): BroadcastSendErrorAction => ({
            label,
            onClick: () => clicked.push(label),
            disabledReason,
        })
        const { container } = render(
            <Provider>
                <BroadcastSendErrorBanner
                    {...props}
                    fixAction={action('Fix it', sendRun.fixDisabledReason)}
                    resendAction={action('Resend it')}
                    content={sendRun.content}
                />
            </Provider>
        )
        return {
            bannerText: () => container.querySelector('[data-attr="broadcast-send-error"]')?.textContent ?? null,
            settled: async () => {
                await waitFor(() => expect(served).toEqual(expect.arrayContaining(['totals', 'links'])))
                await expectLogic(broadcastPerformanceLogic(props)).toFinishAllListeners()
            },
        }
    }

    it('shows nothing when everyone got the broadcast', async () => {
        const { bannerText, settled } = renderBanner({ sent: 40, failed: 0, errorLogs: [BROKEN_TAG] })

        await settled()

        expect(bannerText()).toBeNull()
    })

    it.each([
        {
            name: 'a broken merge tag, before anyone got it',
            run: { failed: 3, errorLogs: [BROKEN_TAG] },
            text: "3 people didn't get this email. A merge tag can't be read: {{ person.properties.nme }}. Check the tag in the email for typos.",
            action: 'Fix it',
        },
        {
            name: 'a broken merge tag, after one person got it',
            run: { sent: 1, failed: 1, errorLogs: [BROKEN_TAG] },
            text: "1 person didn't get this email. A merge tag can't be read: {{ person.properties.nme }}. Check the tag in the email for typos. Sending it again goes to the whole audience, including the 1 person who got this email.",
            action: 'Fix it',
        },
        {
            name: 'a merge tag the log cut off, found in the content',
            run: { failed: 2, errorLogs: [CUT_TAG], content: '<p>Hi {{ person.properties.first_name }}</p>' },
            text: "2 people didn't get this email. A merge tag can't be read: {{ person.properties.first_name }}. Check the tag in the email for typos.",
            action: 'Fix it',
        },
        {
            name: 'a merge tag the log cut off, with no content to look in',
            run: { failed: 2, errorLogs: [CUT_TAG] },
            text: "2 people didn't get this email. A merge tag can't be read: person.properties.first.... Check the tag in the email for typos.",
            action: 'Fix it',
        },
        {
            name: 'a sender that is not set up',
            run: { failed: 5, errorLogs: [NO_SENDER] },
            text: "5 people didn't get this email. The sender for this email isn't set up. Check the sender in the email step and that its domain is verified, then send it again.",
            action: 'Fix it',
        },
        {
            name: 'a problem on our side, before anyone got it',
            run: { failed: 5, errorLogs: [OUTAGE] },
            text: "5 people didn't get this email. A problem on our side stopped the send. Send it again to reach them.",
            action: 'Resend it',
        },
        {
            name: 'a problem on our side, after many got it',
            run: { sent: 1234, failed: 5, errorLogs: [OUTAGE] },
            text: "5 people didn't get this email. A problem on our side stopped the send. Sending it again goes to the whole audience, including the 1,234 people who got this email.",
            action: 'Resend it',
        },
        {
            name: 'an error it cannot place',
            run: { sent: 40, failed: 5, errorLogs: [UNKNOWN] },
            text: "5 people didn't get this email. Sending hit an error. Show details has the error from the send.",
            action: null,
        },
        {
            name: 'a push problem on our side',
            run: { channel: 'push' as const, sent: 1, failed: 2, errorLogs: [OUTAGE] },
            text: "2 people didn't get this notification. A problem on our side stopped the send. Sending it again goes to the whole audience, including the 1 person who got this notification.",
            action: 'Resend it',
        },
    ])('explains $name and offers the matching action', async ({ run, text, action }) => {
        const { bannerText } = renderBanner(run)

        await waitFor(() => expect(bannerText()).toBe(`${text}Show details`))
        const offered = ['Fix it', 'Resend it'].filter((label) => screen.queryAllByText(label).length > 0)
        expect(offered).toEqual(action ? [action] : [])
        offered.forEach((label) => fireEvent.click(screen.getAllByText(label)[0]))
        expect(clicked).toEqual(offered)
    })

    it('blocks the fix action when the caller gives a reason', async () => {
        renderBanner({ failed: 3, errorLogs: [BROKEN_TAG], fixDisabledReason: 'You cannot edit this broadcast' })

        fireEvent.click((await screen.findAllByText('Fix it'))[0])

        expect(clicked).toEqual([])
    })

    it('shows the raw error from the send on request and hides it again', async () => {
        renderBanner({ failed: 3, errorLogs: [UNKNOWN] })

        const showDetails = await screen.findByText('Show details')
        expect(screen.queryByText(UNKNOWN)).toBeNull()
        fireEvent.click(showDetails)
        expect(screen.getByText(UNKNOWN)).toBeTruthy()
        fireEvent.click(screen.getByText('Hide details'))
        expect(screen.queryByText(UNKNOWN)).toBeNull()
        expect(screen.getByText('Show details')).toBeTruthy()
    })

    it('lets the sender load the error again when its details failed to load', async () => {
        const { bannerText } = renderBanner({ failed: 3, errorLogs: [null, BROKEN_TAG] })

        await waitFor(() => expect(served).toContain('log'))
        await waitFor(() => expect(screen.queryAllByText('Try again')).toHaveLength(1))
        expect(bannerText()).toBe(
            "3 people didn't get this email. Sending it hit an error, and its details didn't load. Try again"
        )
        expect(screen.queryAllByText('Fix it')).toEqual([])

        await act(async () => {
            fireEvent.click(screen.getByText('Try again'))
        })

        await waitFor(() => expect(bannerText()).toContain("A merge tag can't be read: {{ person.properties.nme }}."))
        expect(screen.queryByText('Try again')).toBeNull()
    })
})
