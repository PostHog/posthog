import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { BindLogic, Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel, AccessControlResourceType, AppContext } from '~/types'

import { HogflowTestResult } from '../Workflows/hogflows/steps/types'
import { BroadcastEmailPreview } from './BroadcastEmailPreview'
import { broadcastPreviewLogic } from './broadcastPreviewLogic'
import { BroadcastPushPreview } from './BroadcastPushPreview'
import { broadcastTestSendLogic } from './broadcastTestSendLogic'
import { BroadcastEmailValue, DEFAULT_BROADCAST_EMAIL, broadcastWizardLogic } from './broadcastWizardLogic'
import { BroadcastReviewTestEmail } from './steps/BroadcastReviewTestEmail'

const NO_EMAIL = ['person-anon', { display_name: 'anon-7' }, '{}']
const ADA = ['person-ada', { display_name: 'Ada' }, JSON.stringify({ email: 'ada@example.com', name: 'Ada' })]
const GRACE = ['person-grace', null, JSON.stringify({ email: 'grace@example.com', name: 'Grace' })]
const READY_EMAIL: BroadcastEmailValue = {
    ...DEFAULT_BROADCAST_EMAIL,
    from: { integrationId: 1, email: 'team@example.com' },
    subject: 'Hi {{ person.properties.name }}',
    html: '<p>Hello {{ person.properties.name }}</p>',
}
const log = (message: string, level = 'info'): any => ({ level, timestamp: '2026-01-01T00:00:00Z', message })

describe('broadcast previews', () => {
    const priorAppContext = window.POSTHOG_APP_CONTEXT
    let people: unknown[][] | 'pending' | 'failed'
    let sendResult: Partial<HogflowTestResult>
    let sent: any[]
    let sendGate: Promise<void>
    let mounted: { unmount: () => void }[]

    beforeEach(() => {
        people = []
        sendResult = { status: 'success' }
        sent = []
        sendGate = Promise.resolve()
        mounted = []
        useMocks({
            get: { '/api/projects/:team_id/integrations/': { results: [], count: 0 } },
            post: {
                '/api/projects/:team_id/query/:kind/': () =>
                    people === 'pending'
                        ? new Promise(() => {})
                        : people === 'failed'
                          ? [500, { detail: 'Query failed' }]
                          : [200, { results: people }],
                '/api/projects/:team_id/hog_flows/user_blast_radius/': () => [200, { affected: 0, total: 0 }],
                '/api/projects/:team_id/hog_flows/new/invocations/': async ({ request }) => {
                    sent.push(await request.json())
                    await sendGate
                    return [200, { nextActionId: null, ...sendResult }]
                },
            },
        })
    })

    afterEach(() => {
        cleanup()
        mounted.forEach((logic) => logic.unmount())
        window.POSTHOG_APP_CONTEXT = priorAppContext
    })

    function renderReview(
        content: { email?: BroadcastEmailValue; push?: boolean },
        preview: JSX.Element = <BroadcastEmailPreview showTestButton={false} />
    ): void {
        window.POSTHOG_APP_CONTEXT = {
            ...priorAppContext,
            resource_access_control: { [AccessControlResourceType.Workflow]: AccessControlLevel.Editor },
        } as AppContext
        initKeaTests()
        const wizard = broadcastWizardLogic({ id: 'new' })
        wizard.mount()
        mounted.push(wizard)
        if (content.push) {
            wizard.actions.setChannel('push')
            wizard.actions.setPush({ channels: [7], title: 'New release', body: 'Open the app' })
        } else {
            wizard.actions.setEmail(content.email ?? READY_EMAIL)
        }
        render(
            <Provider>
                <BindLogic logic={broadcastWizardLogic} props={{ id: 'new' }}>
                    <BindLogic logic={broadcastPreviewLogic} props={{ id: 'new' }}>
                        <BindLogic logic={broadcastTestSendLogic} props={{ id: 'new' }}>
                            <BroadcastReviewTestEmail />
                            {preview}
                        </BindLogic>
                    </BindLogic>
                </BindLogic>
            </Provider>
        )
    }

    const click = (dataAttr: string): void => {
        act(() => {
            fireEvent.click(document.querySelector(`[data-attr="${dataAttr}"]`) as HTMLElement)
        })
    }
    const type = (dataAttr: string, value: string): void => {
        act(() => {
            fireEvent.change(document.querySelector(`[data-attr="${dataAttr}"]`) as HTMLElement, {
                target: { value },
            })
        })
    }
    const reviewCard = (selector: string): Element | null =>
        document.querySelector(`[data-attr="broadcast-review-test-email"] ${selector}`)
    const iframeHtml = (): string | null | undefined =>
        document.querySelector('iframe[title="Email preview"]')?.getAttribute('srcdoc')

    it.each([
        [AccessControlLevel.Viewer, 'email', 'true'],
        [AccessControlLevel.Editor, 'email', 'false'],
        [AccessControlLevel.Viewer, 'push', 'true'],
        [AccessControlLevel.Editor, 'push', 'false'],
    ])('gives a workflows %s a %s test send button with aria-disabled=%s', (workflowAccess, channel, expected) => {
        window.POSTHOG_APP_CONTEXT = {
            ...priorAppContext,
            resource_access_control: {
                ...priorAppContext?.resource_access_control,
                [AccessControlResourceType.Workflow]: workflowAccess,
            },
        } as AppContext
        initKeaTests()

        render(
            <Provider>
                <BindLogic logic={broadcastWizardLogic} props={{ id: 'new' }}>
                    <BindLogic logic={broadcastPreviewLogic} props={{ id: 'new' }}>
                        <BindLogic logic={broadcastTestSendLogic} props={{ id: 'new' }}>
                            {channel === 'email' ? <BroadcastEmailPreview /> : <BroadcastPushPreview />}
                        </BindLogic>
                    </BindLogic>
                </BindLogic>
            </Provider>
        )

        expect(
            document.querySelector(`[data-attr="broadcast-open-test-${channel === 'email' ? 'email' : 'push'}"]`)
        ).toHaveAttribute('aria-disabled', expected)
    })

    it('shows the modify content button as busy while a new broadcast saves its draft', async () => {
        useMocks({
            post: {
                '/api/projects/:team_id/hog_flows/': () => new Promise(() => {}),
            },
        })
        initKeaTests()
        const wizard = broadcastWizardLogic({ id: 'new' })
        wizard.mount()
        wizard.actions.setEmail({ ...DEFAULT_BROADCAST_EMAIL, html: '<p>Hi</p>' })

        render(
            <Provider>
                <BindLogic logic={broadcastWizardLogic} props={{ id: 'new' }}>
                    <BindLogic logic={broadcastPreviewLogic} props={{ id: 'new' }}>
                        <BindLogic logic={broadcastTestSendLogic} props={{ id: 'new' }}>
                            <BroadcastEmailPreview
                                showTestButton={false}
                                onModifyContent={wizard.actions.editEmailContent}
                            />
                        </BindLogic>
                    </BindLogic>
                </BindLogic>
            </Provider>
        )
        const button = document.querySelector('[data-attr="broadcast-review-modify-content"]') as HTMLElement
        expect(button).toHaveAttribute('aria-disabled', 'false')

        act(() => {
            fireEvent.click(button)
        })

        expect(button).toHaveAttribute('aria-disabled', 'true')
        wizard.unmount()
    })

    it('previews the email as the first audience member with an email address, then as the person picked', async () => {
        people = [NO_EMAIL, ADA, GRACE]
        renderReview({})

        await screen.findByText(/^Values come from Ada\./)
        expect(screen.getByText('Hi Ada')).toBeInTheDocument()
        expect(screen.getByText('ada@example.com')).toBeInTheDocument()
        expect(iframeHtml()).toBe('<p>Hello Ada</p>')
        expect(document.querySelector('[data-attr="broadcast-review-modify-content"]')).toBeNull()

        click('broadcast-preview-person')
        act(() => {
            fireEvent.click(screen.getByText('grace@example.com'))
        })

        expect(await screen.findByText('Hi Grace')).toBeInTheDocument()
        expect(iframeHtml()).toBe('<p>Hello Grace</p>')
        expect(screen.getByText(/^Values come from grace@example\.com\./)).toBeInTheDocument()
        expect(screen.getAllByText('grace@example.com')).toHaveLength(2)
    })

    it.each([
        ['pending', () => document.querySelector('.Spinner')],
        ['failed', () => screen.queryByText(/^Couldn't load anyone to preview against, so variables stay unfilled/)],
        [[], () => screen.queryByText('No one matches this audience yet, so variables stay unfilled below.')],
    ] as const)(
        'shows the recipient row and leaves variables unfilled when the audience lookup is %j',
        async (lookup, recipientRow) => {
            people = lookup as typeof people
            renderReview({})

            await waitFor(() => expect(recipientRow()).not.toBeNull())
            expect(screen.getByText('Hi {{ person.properties.name }}')).toBeInTheDocument()
            expect(screen.queryByText(/^Values come from/)).toBeNull()
        }
    )

    it.each([
        ['no subject or content', { subject: '', html: '', text: '' }, ['No subject', 'No content yet']],
        ['plain text only', { html: '', text: 'Plain text for {{ person.properties.name }}' }, ['Plain text for Ada']],
    ])('previews an email with %s, and opens the test modal from its own button', async (_, change, shown) => {
        people = [ADA]
        renderReview({ email: { ...READY_EMAIL, ...change } }, <BroadcastEmailPreview />)

        for (const text of shown) {
            expect(await screen.findByText(text)).toBeInTheDocument()
        }
        expect(iframeHtml()).toBeUndefined()
        expect(document.querySelector('[data-attr="broadcast-preview-person"]')).toHaveTextContent('Ada')
        expect(screen.getByText('Preview and test before this reaches the audience.')).toBeInTheDocument()

        click('broadcast-open-test-email')

        expect(await screen.findByText("Variables use Ada's values, matching the preview.")).toBeInTheDocument()

        act(() => {
            fireEvent.click(document.querySelector('[aria-label="close"]') as HTMLElement)
        })

        await waitFor(() => expect(document.querySelector('[data-attr="broadcast-send-test-email"]')).toBeNull())
    })

    it('sends a test email to a valid address only, then vouches for it on the review step', async () => {
        people = [ADA]
        renderReview({})
        await screen.findByText(/^Values come from Ada\./)
        expect(screen.getByText('Send yourself a test first')).toBeInTheDocument()
        expect(reviewCard('.text-success')).toBeNull()
        expect(reviewCard('[data-attr="broadcast-review-send-test"]')).toHaveClass('LemonButton--primary')
        expect(document.querySelector('[data-attr="broadcast-open-test-email"]')).toBeNull()
        expect(screen.getByText(/^Read the email in a real inbox/)).toBeInTheDocument()

        click('broadcast-review-send-test')

        expect(screen.getByText('Send a test email')).toBeInTheDocument()
        expect(screen.getByText('Goes to this address only. Nobody in the audience receives it.')).toBeInTheDocument()
        expect(document.querySelector('[data-attr="broadcast-test-email-recipient"]')).toHaveValue(
            MOCK_DEFAULT_USER.email
        )
        type('broadcast-test-email-recipient', 'not-an-email')
        expect(document.querySelector('[data-attr="broadcast-send-test-email"]')).toHaveAttribute(
            'aria-disabled',
            'true'
        )
        type('broadcast-test-email-recipient', 'reviewer@example.com')
        let release = (): void => {}
        sendGate = new Promise((resolve) => (release = resolve))
        click('broadcast-send-test-email')
        await waitFor(() => expect(sent).toHaveLength(1))
        expect(document.querySelector('[data-attr="broadcast-send-test-email"]')).toHaveAttribute(
            'aria-disabled',
            'true'
        )
        release()

        expect(await screen.findByText('Test sent to reviewer@example.com')).toBeInTheDocument()
        expect(screen.getByText('Check it in your inbox, on desktop and mobile, before you send.')).toBeInTheDocument()
        expect(screen.getByText('Send another test')).toBeInTheDocument()
        expect(reviewCard('.text-success')).not.toBeNull()
        expect(reviewCard('[data-attr="broadcast-review-send-test"]')).toHaveClass('LemonButton--secondary')
        await waitFor(() => expect(screen.queryByText('Send a test email')).toBeNull())
        expect(sent).toHaveLength(1)
        const action = sent[0].configuration.actions.find((a: any) => a.id === sent[0].current_action_id)
        expect(action.config.inputs.email.value.to).toEqual({ email: 'reviewer@example.com', name: '' })
        expect(sent[0].globals.person).toMatchObject({ id: 'person-ada', name: 'Ada' })
    })

    it('sends a test push to a distinct ID, then vouches for it on the review step', async () => {
        sendResult = { status: 'success', logs: [log('Push accepted by FCM')] }
        renderReview({ push: true }, <BroadcastPushPreview showTestButton={false} />)
        expect(screen.getByText(/^See the notification on a real phone/)).toBeInTheDocument()

        act(() => {
            fireEvent.click(screen.getByText('Send test notification'))
        })

        expect(screen.getByText('Send a test notification')).toBeInTheDocument()
        expect(screen.getByText(/^Goes to this person's devices only\./)).toBeInTheDocument()
        expect(
            screen.getByText('No one matches this audience yet, so variables send as blank text.')
        ).toBeInTheDocument()
        expect(document.querySelector('[data-attr="broadcast-test-push-recipient"]')).toHaveValue(
            MOCK_DEFAULT_USER.distinct_id
        )
        type('broadcast-test-push-recipient', 'user-1')
        click('broadcast-send-test-email')

        expect(await screen.findByText("Test sent to user-1's devices")).toBeInTheDocument()
        expect(screen.getByText('Check it on your phone and tap it before you send.')).toBeInTheDocument()
        await waitFor(() => expect(screen.queryByText('Send a test notification')).toBeNull())
        expect(sent[0].current_action_id).toBe('send_test_push')
    })

    it.each([
        ['email', { emailSendResult: { status: 'skipped', reason: 'Unsubscribed' } }, 'Unsubscribed'],
        ['email', { status: 'skipped', logs: [log('No address.'), log('Step skipped.')] }, 'No address. Step skipped.'],
        ['email', { status: 'skipped' }, 'The email step was skipped, so nothing was sent.'],
        ['email', { status: 'error', errors: ['Bad sender', 'Bad tag'] }, 'Bad sender, Bad tag'],
        ['email', { status: 'error' }, 'Could not send the test email.'],
        ['push', { logs: [log('No token for this app', 'warn')] }, 'No token for this app'],
        [
            'push',
            { logs: [log('Push accepted by FCM'), log('APNs: bad token')] },
            'Some apps took the notification, but at least one failed: APNs: bad token',
        ],
        ['push', { status: 'skipped' }, 'The push step was skipped, so nothing was sent.'],
        ['push', { status: 'error' }, 'Could not send the test notification.'],
    ] as const)('keeps the %s test modal open with why %j sent nothing', async (channel, result, banner) => {
        sendResult = { status: 'success', ...result } as Partial<HogflowTestResult>
        renderReview({ push: channel === 'push' })
        click('broadcast-review-send-test')
        click('broadcast-send-test-email')

        expect(await screen.findByText(banner)).toBeInTheDocument()

        act(() => {
            fireEvent.click(screen.getByText('Cancel'))
        })

        await waitFor(() => expect(document.querySelector('[data-attr="broadcast-send-test-email"]')).toBeNull())
    })
})
