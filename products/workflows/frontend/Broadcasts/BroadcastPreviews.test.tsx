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
    from: { integrationId: 1 },
    cc: 'team@example.com',
    bcc: 'archive@example.com',
    subject: 'Hi {{ person.properties.name }}',
    html: '<p>Hello {{ person.properties.name }}</p>',
}
type LogEntry = NonNullable<HogflowTestResult['logs']>[number]
const log = (message: string, level: 'info' | 'warn' = 'info'): LogEntry =>
    ({ message, level, timestamp: '2026-01-01T00:00:00Z' }) as unknown as LogEntry
type Lookup = unknown[][] | 'pending' | 'failed'
type SentInvocation = {
    configuration: { actions: { id: string; config: { inputs: Record<string, { value: unknown }> } }[] }
    current_action_id: string
    globals: { person: Record<string, unknown> }
}

describe('broadcast previews', () => {
    const priorAppContext = window.POSTHOG_APP_CONTEXT
    let people: Lookup
    let sendResult: Partial<HogflowTestResult>
    let sent: SentInvocation[]
    let sendGate: Promise<void>
    let mountedWizard: ReturnType<typeof broadcastWizardLogic.build> | undefined

    beforeEach(() => {
        people = []
        sendResult = { status: 'success' }
        sent = []
        sendGate = Promise.resolve()
        mountedWizard = undefined
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
                    sent.push((await request.json()) as SentInvocation)
                    await sendGate
                    return [200, { nextActionId: null, ...sendResult }]
                },
            },
        })
    })

    afterEach(() => {
        cleanup()
        mountedWizard?.unmount()
        window.POSTHOG_APP_CONTEXT = priorAppContext
    })

    function renderTree(children: JSX.Element): void {
        render(
            <Provider>
                <BindLogic logic={broadcastWizardLogic} props={{ id: 'new' }}>
                    <BindLogic logic={broadcastPreviewLogic} props={{ id: 'new' }}>
                        <BindLogic logic={broadcastTestSendLogic} props={{ id: 'new' }}>
                            {children}
                        </BindLogic>
                    </BindLogic>
                </BindLogic>
            </Provider>
        )
    }

    function mountWizard(channel: 'email' | 'push', email: BroadcastEmailValue = READY_EMAIL): void {
        window.POSTHOG_APP_CONTEXT = {
            ...priorAppContext,
            resource_access_control: { [AccessControlResourceType.Workflow]: AccessControlLevel.Editor },
        } as AppContext
        initKeaTests()
        mountedWizard = broadcastWizardLogic({ id: 'new' })
        mountedWizard.mount()
        mountedWizard.actions.setEmail(email)
        if (channel === 'push') {
            mountedWizard.actions.setChannel('push')
            mountedWizard.actions.setPush({ channels: [7], title: 'New release', body: 'Open the app' })
        }
    }

    function renderReview(channel: 'email' | 'push', email?: BroadcastEmailValue): void {
        mountWizard(channel, email)
        renderTree(
            <>
                <BroadcastReviewTestEmail />
                {channel === 'push' ? (
                    <BroadcastPushPreview showTestButton={false} />
                ) : (
                    <BroadcastEmailPreview showTestButton={false} />
                )}
            </>
        )
    }

    const el = (dataAttr: string): HTMLElement | null => document.querySelector(`[data-attr="${dataAttr}"]`)
    const fire = (dataAttr: string, event: (target: HTMLElement) => void): void => {
        const target = el(dataAttr)
        if (!target) {
            throw new Error(`Nothing on the page has data-attr="${dataAttr}"`)
        }
        act(() => event(target))
    }
    const click = (dataAttr: string): void => fire(dataAttr, (target) => fireEvent.click(target))
    const type = (dataAttr: string, value: string): void =>
        fire(dataAttr, (target) => fireEvent.change(target, { target: { value } }))
    const reviewCard = (selector: string): Element | null =>
        document.querySelector(`[data-attr="broadcast-review-test-email"] ${selector}`)
    const toRow = (): HTMLElement | null => screen.getByText('To').parentElement
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
        renderReview('email')

        await screen.findByText(/^Values come from Ada\./)
        expect(screen.getByText('Hi Ada')).toBeInTheDocument()
        expect(toRow()).toHaveTextContent(/^ToAdaada@example\.com$/)
        expect(iframeHtml()).toBe('<p>Hello Ada</p>')
        expect(el('broadcast-review-modify-content')).toBeNull()

        click('broadcast-preview-person')
        act(() => {
            fireEvent.click(screen.getByText('grace@example.com'))
        })

        expect(await screen.findByText('Hi Grace')).toBeInTheDocument()
        expect(iframeHtml()).toBe('<p>Hello Grace</p>')
        expect(screen.getByText(/^Values come from grace@example\.com\./)).toBeInTheDocument()
        expect(toRow()).toHaveTextContent(/^Tograce@example\.com$/)
    })

    it.each<[Lookup, () => Element | null]>([
        ['pending', () => document.querySelector('.Spinner')],
        ['failed', () => screen.queryByText(/^Couldn't load anyone to preview against, so variables stay unfilled/)],
        [[], () => screen.queryByText('No one matches this audience yet, so variables stay unfilled below.')],
    ])(
        'shows the recipient row and leaves variables unfilled when the audience lookup is %j',
        async (lookup, recipientRow) => {
            people = lookup
            renderReview('email')

            await waitFor(() => expect(recipientRow()).not.toBeNull())
            expect(screen.getByText('Hi {{ person.properties.name }}')).toBeInTheDocument()
            expect(screen.queryByText(/^Values come from/)).toBeNull()
        }
    )

    it.each([
        ['no subject or content', { subject: '', html: '', text: '' }, ['No subject', 'No content yet']],
        ['plain text only', { html: '', text: 'Plain text for {{ person.properties.name }}' }, ['Plain text for Ada']],
    ])('previews an email with %s', async (_, change, shown) => {
        people = [ADA]
        renderReview('email', { ...READY_EMAIL, ...change })

        for (const text of shown) {
            expect(await screen.findByText(text)).toBeInTheDocument()
        }
        expect(iframeHtml()).toBeUndefined()
        expect(el('broadcast-preview-person')).toHaveTextContent('Ada')
        expect(screen.getByText('Preview and test before this reaches the audience.')).toBeInTheDocument()
    })

    it('opens the test modal from the preview on its own and closes it', async () => {
        people = [ADA]
        mountWizard('email')
        renderTree(<BroadcastEmailPreview />)
        await screen.findByText(/^Values come from Ada\./)

        click('broadcast-open-test-email')

        expect(await screen.findByText("Variables use Ada's values, matching the preview.")).toBeInTheDocument()

        act(() => {
            fireEvent.click(document.querySelector('[aria-label="close"]') as HTMLElement)
        })

        await waitFor(() => expect(el('broadcast-send-test-email')).toBeNull())
    })

    it('sends a test email to a valid address only, then vouches for it on the review step', async () => {
        people = [ADA]
        renderReview('email')
        await screen.findByText(/^Values come from Ada\./)
        expect(screen.getByText('Send yourself a test first')).toBeInTheDocument()
        expect(reviewCard('.text-success')).toBeNull()
        expect(reviewCard('[data-attr="broadcast-review-send-test"]')).toHaveClass('LemonButton--primary')
        expect(el('broadcast-open-test-email')).toBeNull()
        expect(screen.getByText(/^Read the email in a real inbox/)).toBeInTheDocument()

        click('broadcast-review-send-test')

        expect(screen.getByText('Send a test email')).toBeInTheDocument()
        expect(screen.getByText('Goes to this address only. Nobody in the audience receives it.')).toBeInTheDocument()
        expect(el('broadcast-test-email-recipient')).toHaveValue(MOCK_DEFAULT_USER.email)
        type('broadcast-test-email-recipient', 'not-an-email')
        expect(el('broadcast-send-test-email')).toHaveAttribute('aria-disabled', 'true')
        type('broadcast-test-email-recipient', 'reviewer@example.com')
        let release = (): void => {}
        sendGate = new Promise((resolve) => (release = resolve))
        click('broadcast-send-test-email')
        await waitFor(() => expect(sent).toHaveLength(1))
        expect(el('broadcast-send-test-email')).toHaveAttribute('aria-disabled', 'true')
        release()

        expect(await screen.findByText('Test sent to reviewer@example.com')).toBeInTheDocument()
        expect(screen.getByText('Check it in your inbox, on desktop and mobile, before you send.')).toBeInTheDocument()
        expect(screen.getByText('Send another test')).toBeInTheDocument()
        expect(reviewCard('.text-success')).not.toBeNull()
        expect(reviewCard('[data-attr="broadcast-review-send-test"]')).toHaveClass('LemonButton--secondary')
        await waitFor(() => expect(screen.queryByText('Send a test email')).toBeNull())
        expect(sent).toHaveLength(1)
        const action = sent[0].configuration.actions.find((a) => a.id === sent[0].current_action_id)
        expect(action?.config.inputs.email.value).toMatchObject({
            to: { email: 'reviewer@example.com', name: '' },
            cc: '',
            bcc: '',
        })
        expect(sent[0].globals.person).toMatchObject({ id: 'person-ada', name: 'Ada' })
    })

    it('sends a test push to a distinct ID, then vouches for it on the review step', async () => {
        sendResult = { status: 'success', logs: [log('Push accepted by FCM')] }
        renderReview('push')
        expect(screen.getByText(/^See the notification on a real phone/)).toBeInTheDocument()

        act(() => {
            fireEvent.click(screen.getByText('Send test notification'))
        })

        expect(screen.getByText('Send a test notification')).toBeInTheDocument()
        expect(screen.getByText(/^Goes to this person's devices only\./)).toBeInTheDocument()
        expect(
            screen.getByText('No one matches this audience yet, so variables send as blank text.')
        ).toBeInTheDocument()
        expect(el('broadcast-test-push-recipient')).toHaveValue(MOCK_DEFAULT_USER.distinct_id)
        type('broadcast-test-push-recipient', 'user-1')
        click('broadcast-send-test-email')

        expect(await screen.findByText("Test sent to user-1's devices")).toBeInTheDocument()
        expect(screen.getByText('Check it on your phone and tap it before you send.')).toBeInTheDocument()
        await waitFor(() => expect(screen.queryByText('Send a test notification')).toBeNull())
        const action = sent[0].configuration.actions.find((a) => a.id === sent[0].current_action_id)
        expect(action?.id).toBe('send_test_push')
        expect(action?.config.inputs.distinctId.value).toBe('{% raw %}user-1{% endraw %}')
    })

    it.each<['email' | 'push', string, Partial<HogflowTestResult>, string?]>([
        ['email', 'Unsubscribed', { emailSendResult: { status: 'skipped', reason: 'Unsubscribed' } }],
        ['email', 'No address. Step skipped.', { status: 'skipped', logs: [log('No address.'), log('Step skipped.')] }],
        ['email', 'The email step was skipped, so nothing was sent.', { status: 'skipped' }],
        ['email', 'Bad sender, Bad tag', { status: 'error', errors: ['Bad sender', 'Bad tag'] }],
        ['email', 'Could not send the test email.', { status: 'error' }],
        ['push', 'No token for this app', { logs: [log('No token for this app', 'warn')] }],
        [
            'push',
            'Some apps took the notification, but at least one failed: APNs: bad token',
            { logs: [log('Push accepted by FCM'), log('APNs: bad token')] },
            `Test sent to ${MOCK_DEFAULT_USER.distinct_id}'s devices`,
        ],
        ['push', 'The push step was skipped, so nothing was sent.', { status: 'skipped' }],
        ['push', 'Could not send the test notification.', { status: 'error' }],
    ])(
        'keeps the %s test modal open and says "%s"',
        async (channel, banner, result, card = 'Send yourself a test first') => {
            sendResult = { status: 'success', ...result }
            renderReview(channel)
            click('broadcast-review-send-test')
            click('broadcast-send-test-email')

            expect(await screen.findByText(banner)).toBeInTheDocument()
            expect(screen.getByText(card)).toBeInTheDocument()

            act(() => {
                fireEvent.click(screen.getByText('Cancel'))
            })

            await waitFor(() => expect(el('broadcast-send-test-email')).toBeNull())
        }
    )
})
