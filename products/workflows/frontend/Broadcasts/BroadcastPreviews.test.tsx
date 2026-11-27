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
type SentInvocation = {
    configuration: { actions: { id: string; config: { inputs: Record<string, { value: unknown }> } }[] }
    current_action_id: string
    globals: { person: Record<string, unknown> }
}

describe('broadcast previews', () => {
    const priorAppContext = window.POSTHOG_APP_CONTEXT
    let people: unknown[][] | 'pending' | 'failed'
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
        if (channel === 'push') {
            mountedWizard.actions.setChannel('push')
            mountedWizard.actions.setPush({ channels: [7], title: 'New release', body: 'Open the app' })
        }
        mountedWizard.actions.setEmail(email)
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

    const el = (dataAttr: string): HTMLElement | null => screen.queryByTestId(dataAttr)
    const click = (dataAttr: string): void => {
        fireEvent.click(screen.getByTestId(dataAttr))
    }
    const type = (dataAttr: string, value: string): void => {
        fireEvent.change(screen.getByTestId(dataAttr), { target: { value } })
    }
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
        fireEvent.click(screen.getByText('grace@example.com'))

        expect(await screen.findByText('Hi Grace')).toBeInTheDocument()
        expect(iframeHtml()).toBe('<p>Hello Grace</p>')
        expect(screen.getByText(/^Values come from grace@example\.com\./)).toBeInTheDocument()
        expect(toRow()).toHaveTextContent(/^Tograce@example\.com$/)
    })

    it.each<[typeof people, RegExp, boolean]>([
        ['pending', /^To$/, true],
        ['failed', /^ToCouldn't load anyone to preview against, so variables stay unfilled/, false],
        [[], /^ToNo one matches this audience yet, so variables stay unfilled below\.$/, false],
    ])(
        'shows the recipient row and leaves variables unfilled when the audience lookup is %j',
        async (lookup, recipientRow, loading) => {
            people = lookup
            renderReview('email')

            await waitFor(() => expect(toRow()).toHaveTextContent(recipientRow))
            expect(!!toRow()?.querySelector('svg')).toBe(loading)
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

    it('hides the email preview test button when showTestButton is false', () => {
        mountWizard('email')
        renderTree(<BroadcastEmailPreview showTestButton={false} />)
        expect(el('broadcast-open-test-email')).toBeNull()
    })

    it('opens the test modal from the preview on its own and closes it', async () => {
        people = [ADA]
        mountWizard('email')
        renderTree(<BroadcastEmailPreview />)
        await screen.findByText(/^Values come from Ada\./)

        click('broadcast-open-test-email')

        expect(await screen.findByText("Variables use Ada's values, matching the preview.")).toBeInTheDocument()

        fireEvent.click(document.querySelector('[aria-label="close"]') as HTMLElement)

        await waitFor(() => expect(el('broadcast-send-test-email')).toBeNull())
    })

    async function openEmailTest(): Promise<void> {
        people = [ADA]
        renderReview('email')
        await screen.findByText(/^Values come from Ada\./)
        click('broadcast-review-send-test')
    }

    it('asks for a valid address before it sends a test email', async () => {
        await openEmailTest()

        expect(screen.getByText('Send a test email')).toBeInTheDocument()
        expect(screen.getByText('Goes to this address only. Nobody in the audience receives it.')).toBeInTheDocument()
        expect(el('broadcast-test-email-recipient')).toHaveValue(MOCK_DEFAULT_USER.email)
        type('broadcast-test-email-recipient', 'not-an-email')
        expect(el('broadcast-send-test-email')).toHaveAttribute('aria-disabled', 'true')
    })

    it('keeps the send button busy while the test email is on its way', async () => {
        let release = (): void => {}
        sendGate = new Promise((resolve) => (release = resolve))
        await openEmailTest()
        click('broadcast-send-test-email')

        await waitFor(() => expect(sent).toHaveLength(1))
        expect(el('broadcast-send-test-email')).toHaveAttribute('aria-disabled', 'true')
        release()
        await waitFor(() => expect(el('broadcast-send-test-email')).toBeNull())
    })

    it('sends the test email to the typed address only, rendered for the preview person', async () => {
        await openEmailTest()
        type('broadcast-test-email-recipient', 'reviewer@example.com')
        click('broadcast-send-test-email')

        await waitFor(() => expect(sent).toHaveLength(1))
        const action = sent[0].configuration.actions.find((a) => a.id === sent[0].current_action_id)
        const email = action?.config.inputs.email.value
        expect(email).toMatchObject({ to: { email: 'reviewer@example.com', name: '' }, cc: '', bcc: '' })
        expect(sent[0].globals.person).toMatchObject({ id: 'person-ada', name: 'Ada' })
    })

    it('asks for a distinct ID before it sends a test push', async () => {
        renderReview('push')
        fireEvent.click(screen.getByText('Send test notification'))

        expect(screen.getByText('Send a test notification')).toBeInTheDocument()
        expect(screen.getByText(/^Goes to this person's devices only\./)).toBeInTheDocument()
        expect(screen.getByText(/^No one matches this audience yet, so variables send as blank/)).toBeInTheDocument()
        expect(el('broadcast-test-push-recipient')).toHaveValue(MOCK_DEFAULT_USER.distinct_id)
    })

    it('sends the test push to the typed distinct ID only', async () => {
        renderReview('push')
        click('broadcast-review-send-test')
        type('broadcast-test-push-recipient', 'user-1')
        click('broadcast-send-test-email')

        await waitFor(() => expect(sent).toHaveLength(1))
        const action = sent[0].configuration.actions.find((a) => a.id === sent[0].current_action_id)
        expect(action?.id).toBe('send_test_push')
        expect(action?.config.inputs.distinctId.value).toBe('{% raw %}user-1{% endraw %}')
    })

    it.each<['email' | 'push', string, string, RegExp, RegExp, LogEntry[]]>([
        ['email', 'reviewer@example.com', 'reviewer@example.com', /Read the email/, /Check it in your inbox/, []],
        ['push', 'user-1', "user-1's devices", /See the notification/, /on your phone/, [log('Push accepted by FCM')]],
    ])('vouches for a sent %s test on the review step', async (channel, to, sentTo, before, followUp, logs) => {
        sendResult = { status: 'success', logs }
        renderReview(channel)
        expect(screen.getByText(before)).toBeInTheDocument()
        click('broadcast-review-send-test')
        type(`broadcast-test-${channel}-recipient`, to)
        click('broadcast-send-test-email')

        expect(await screen.findByText(`Test sent to ${sentTo}`)).toBeInTheDocument()
        expect(screen.getByText(followUp)).toBeInTheDocument()
        expect(screen.getByText('Send another test')).toBeInTheDocument()
        await waitFor(() => expect(el('broadcast-send-test-email')).toBeNull())
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

            fireEvent.click(screen.getByText('Cancel'))

            await waitFor(() => expect(el('broadcast-send-test-email')).toBeNull())
        }
    )
})
