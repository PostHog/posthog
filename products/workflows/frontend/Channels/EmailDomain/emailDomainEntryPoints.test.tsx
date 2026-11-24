import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { BindLogic, Provider } from 'kea'
import { router } from 'kea-router'

import { OrganizationMembershipLevel } from 'lib/constants'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { EmailSenderRow } from 'scenes/hog-functions/email-templater/EmailSenderRow'
import { emailTemplaterLogic } from 'scenes/hog-functions/email-templater/emailTemplaterLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { MessagingTabActions } from '../../MessagingTabActions'
import { SendingDomainRow } from '../../Transactional/sendFromCode/SendingDomainRow'
import { SenderStep } from '../../Transactional/wizard/steps/SenderStep'
import { transactionalEmailWizardLogic } from '../../Transactional/wizard/transactionalEmailWizardLogic'
import { workflowLogic } from '../../Workflows/workflowLogic'
import { WorkflowSandboxSenderBanner } from '../../Workflows/WorkflowSandboxSenderBanner'
import { EmailSetupModal } from '../EmailSetup/EmailSetupModal'
import { MessageChannels } from '../MessageChannels'
import { FakeEmailDomainBackend } from './__mocks__/fakeEmailDomainBackend'
import { POLL_FAST_MS } from './emailDomainStatusLogic'

const { ToastContainer, toast } = jest.requireActual('react-toastify')

const DOMAIN = 'mail.acme.com'
const SENDER_ID = 42
const LEGACY_MODAL_TITLE = 'Configure email sender'

const element = (attr: string): HTMLElement => {
    const found = document.querySelector<HTMLElement>(`[data-attr="${attr}"]`)
    if (!found) {
        throw new Error(`No element with data-attr ${attr} on the page`)
    }
    return found
}

const flush = async (): Promise<void> => {
    await act(async () => {
        await jest.advanceTimersByTimeAsync(0)
    })
}

const waitForModalToClose = async (): Promise<void> => {
    await act(async () => {
        await jest.advanceTimersByTimeAsync(300)
    })
}

const LIVE_ON_TEST_SENDER = {
    id: 'flow-1',
    name: 'Welcome',
    status: 'active',
    trigger: { type: 'event', filters: { events: [{ id: '$pageview', type: 'events' }] } },
    actions: [
        {
            id: 'trigger_node',
            type: 'trigger',
            name: 'Trigger',
            config: { type: 'event', filters: { events: [{ id: '$pageview', type: 'events' }] } },
        },
        { id: 'email', type: 'email_sandbox', name: 'Email', config: { inputs: {} } },
    ],
    edges: [{ from: 'trigger_node', to: 'email', type: 'continue' }],
}
const liveWorkflowBanner = (
    <BindLogic logic={workflowLogic} props={{ id: LIVE_ON_TEST_SENDER.id }}>
        <WorkflowSandboxSenderBanner id={LIVE_ON_TEST_SENDER.id} />
    </BindLogic>
)

const renderInApp = async (ui: JSX.Element): Promise<void> => {
    render(<Provider>{ui}</Provider>)
    await flush()
}

describe('email domain setup entry points', () => {
    let backend: FakeEmailDomainBackend

    beforeEach(() => {
        jest.useFakeTimers()
        backend = new FakeEmailDomainBackend()
        backend.hostDnsAt('acme.com', 'cloudflare')
        useMocks(backend.mocks())
        useMocks({ get: { '/api/projects/:team_id/hog_flows/:id/': LIVE_ON_TEST_SENDER } })
        initKeaTests()
        featureFlagLogic.mount()
        router.actions.push(urls.workflows('channels'))
    })

    afterEach(() => {
        cleanup()
        toast.dismiss()
        jest.useRealTimers()
        jest.restoreAllMocks()
    })

    it.each([
        [
            'the email card in the channel catalog',
            <MessageChannels key="catalog" />,
            ['workflows-channel-catalog-connect-email'],
        ],
        [
            'the new channel menu in the header',
            <MessagingTabActions key="header" tab="channels" channelsUrl={urls.workflows('channels')} />,
            ['new-channel-button', 'Email'],
        ],
        ['the transactional sending domain row', <SendingDomainRow key="row" />, ['send-from-code-set-up-domain']],
        [
            'the banner on a live workflow on the test sender',
            liveWorkflowBanner,
            ['workflow-sandbox-sender-set-up-domain'],
        ],
    ])('starts a new domain from %s', async (_from, ui, clicks) => {
        await renderInApp(ui)
        for (const target of clicks) {
            fireEvent.click(document.querySelector(`[data-attr="${target}"]`) ?? screen.getByText(target))
            await flush()
        }
        expect(router.values.location.pathname).toMatch(new RegExp(`${urls.workflowsEmailDomain('new')}$`))
        expect(screen.queryByText(LEGACY_MODAL_TITLE)).not.toBeInTheDocument()
    })

    it('sends a domain still waiting for its DNS records from the transactional row to its setup page', async () => {
        const pending = backend.addSender({ email: `hello@${DOMAIN}` })
        await renderInApp(<SendingDomainRow />)
        fireEvent.click(element('send-from-code-check-dns-records'))
        await flush()
        expect(router.values.location.pathname).toMatch(new RegExp(`${urls.workflowsEmailDomain(pending.id)}$`))
    })

    it('adds another sender from the email card once a domain exists', async () => {
        backend.addSender({ email: `hello@${DOMAIN}`, verified: true })
        await renderInApp(<MessageChannels />)
        expect(element('email-domain-add-sender')).toBeInTheDocument()
        fireEvent.click(element('workflows-channel-catalog-connect-email'))
        await flush()
        expect(screen.getByText('Add a sender')).toBeInTheDocument()
        expect(router.values.location.pathname).toMatch(/\/workflows\/channels$/)
    })

    it('starts from configure on an unverified sender', async () => {
        backend.addSender({ email: `hello@${DOMAIN}` })
        await renderInApp(<MessageChannels />)
        fireEvent.click(screen.getByText(DOMAIN))
        expect(screen.getByText('Unverified')).toBeInTheDocument()
        fireEvent.click(screen.getByText('Configure'))
        await flush()
        expect(screen.getByText('Verify your sending domain')).toBeInTheDocument()
        expect(router.values.location.pathname).toMatch(/\/workflows\/channels$/)
        expect(screen.getByText('Open full page').closest('a')).toHaveAttribute(
            'href',
            expect.stringContaining(urls.workflowsEmailDomain(SENDER_ID))
        )
    })

    it('keeps the sender settings for configure on a verified sender', async () => {
        backend.addSender({ email: `hello@${DOMAIN}`, verified: true })
        await renderInApp(<MessageChannels />)
        fireEvent.click(screen.getByText(DOMAIN))
        fireEvent.click(screen.getByText('Configure'))
        await flush()
        expect(screen.getByText(LEGACY_MODAL_TITLE)).toBeInTheDocument()
        expect(router.values.location.pathname).toMatch(/\/workflows\/channels$/)
    })

    it('points the live workflow banner to the verified sender instead of a new domain', async () => {
        backend.addSender({ email: `hello@${DOMAIN}`, verified: true })
        await renderInApp(liveWorkflowBanner)

        expect(await screen.findByText(/switch those steps to your verified sender/)).toBeInTheDocument()
        expect(document.querySelector('[data-attr="workflow-sandbox-sender-set-up-domain"]')).toBeNull()
    })

    it("opens the stopped sender's domain page from the live workflow banner when no verified sender can send", async () => {
        backend.addSender({ email: 'hello@pending.example.com' })
        const stopped = backend.addSender({ email: `hello@${DOMAIN}`, verified: true })
        stopped.config = { ...(stopped.config as Record<string, unknown>), ses_sending_status: 'failed' }
        await renderInApp(liveWorkflowBanner)

        expect(await screen.findByText(/fix your sending domain and switch those steps to it/)).toBeInTheDocument()
        fireEvent.click(element('workflow-sandbox-sender-fix-domain'))
        await flush()

        expect(router.values.location.pathname).toMatch(new RegExp(`${urls.workflowsEmailDomain(stopped.id)}$`))
    })

    it("offers no setup from the live workflow banner while the senders can't be read", async () => {
        backend.addSender({ email: `hello@${DOMAIN}`, verified: true })
        useMocks({ get: { '/api/environments/:team_id/integrations/': () => [500, { detail: 'Server error' }] } })
        await renderInApp(liveWorkflowBanner)

        expect(await screen.findByText(/everyone else is skipped/)).toBeInTheDocument()
        expect(document.querySelector('[data-attr="workflow-sandbox-sender-set-up-domain"]')).toBeNull()
    })

    it('starts from the broadcast sender modal', async () => {
        const onComplete = jest.fn()
        await renderInApp(<EmailSetupModal entry="broadcast" onClose={jest.fn()} onComplete={onComplete} />)
        expect(screen.getByText('Set up a sending domain')).toBeInTheDocument()
        expect(screen.getByText('Which domain should your emails come from?')).toBeInTheDocument()
        expect(onComplete).not.toHaveBeenCalled()
    })

    it('closes the setup modal when the person opens the full page from configure', async () => {
        backend.addSender({ email: `hello@${DOMAIN}` })
        await renderInApp(<MessageChannels />)
        fireEvent.click(screen.getByText(DOMAIN))
        fireEvent.click(screen.getByText('Configure'))
        await flush()

        fireEvent.click(screen.getByText('Open full page'))
        await flush()

        expect(router.values.location.pathname).toMatch(new RegExp(`${urls.workflowsEmailDomain(SENDER_ID)}$`))
        expect(integrationsLogic.values.setupModalOpen).toBe(false)
    })

    it.each([
        ['broadcast' as const, '_blank'],
        [undefined, null],
    ])(
        'stays open for the settings after creating a sender, and reports it when closed (entry %s)',
        async (entry, fullPageTarget) => {
            const onComplete = jest.fn()
            const onClose = jest.fn()
            await renderInApp(<EmailSetupModal entry={entry} onClose={onClose} onComplete={onComplete} />)

            fireEvent.change(document.getElementById('email-domain-another-domain') as HTMLInputElement, {
                target: { value: 'acme.com' },
            })
            fireEvent.click(element('email-domain-use-custom-domain'))
            fireEvent.click(element('email-domain-continue'))
            await flush()

            expect(onComplete).not.toHaveBeenCalled()
            expect(screen.getByText('Verify your sending domain')).toBeInTheDocument()
            expect(screen.getByText('Add 8 settings at Cloudflare')).toBeInTheDocument()
            expect(screen.getByText('Open full page').closest('a')?.getAttribute('target') ?? null).toBe(fullPageTarget)

            fireEvent.click(screen.getByLabelText('close'))
            await flush()
            expect(onComplete).toHaveBeenCalledWith(SENDER_ID)
            expect(onClose).not.toHaveBeenCalled()
        }
    )

    it('sets up a sender in place from an email step with none, and fills the step with it', async () => {
        useMocks({
            get: {
                '/api/environments/:team_id/messaging_templates/': { results: [] },
                '/api/projects/:team_id/property_definitions/': { results: [] },
            },
        })
        const templaterProps = {
            value: { design: null, html: '', text: '', subject: '', from: {}, to: '' },
            onChange: jest.fn(),
            type: 'native_email' as const,
        }
        await renderInApp(
            <BindLogic logic={emailTemplaterLogic} props={templaterProps}>
                <EmailSenderRow />
            </BindLogic>
        )

        fireEvent.click(element('workflow-email-sender-connect'))
        await flush()
        fireEvent.change(document.getElementById('email-domain-another-domain') as HTMLInputElement, {
            target: { value: 'acme.com' },
        })
        fireEvent.click(element('email-domain-use-custom-domain'))
        fireEvent.click(element('email-domain-continue'))
        await flush()

        fireEvent.click(screen.getByLabelText('close'))
        await flush()
        expect(templaterProps.onChange).toHaveBeenLastCalledWith(
            expect.objectContaining({ from: expect.objectContaining({ integrationId: SENDER_ID }) })
        )
    })

    it('keeps the transactional setup open when its domain verifies, and hands the sender to the email', async () => {
        await renderInApp(<SenderStep />)

        fireEvent.click(element('transactional-email-wizard-setup-sender'))
        await flush()
        fireEvent.change(document.getElementById('email-domain-another-domain') as HTMLInputElement, {
            target: { value: 'acme.com' },
        })
        fireEvent.click(element('email-domain-use-custom-domain'))
        fireEvent.click(element('email-domain-continue'))
        await flush()

        backend.verifyDomain(DOMAIN)
        await act(async () => {
            await jest.advanceTimersByTimeAsync(POLL_FAST_MS)
        })
        integrationsLogic.actions.loadIntegrations()
        await flush()
        expect(element('transactional-email-sender-select')).toBeInTheDocument()

        fireEvent.click(element('email-domain-use-sender'))
        await flush()
        expect(transactionalEmailWizardLogic.values.draft.email.from).toMatchObject({ integrationId: SENDER_ID })
    })

    it('opens the existing sender when the new address already has one', async () => {
        const existing = backend.addSender({ email: `hello@${DOMAIN}` })
        await renderInApp(<EmailSetupModal onClose={jest.fn()} onComplete={jest.fn()} />)

        fireEvent.change(document.getElementById('email-domain-another-domain') as HTMLInputElement, {
            target: { value: 'acme.com' },
        })
        fireEvent.click(element('email-domain-use-custom-domain'))
        await flush()
        fireEvent.click(screen.getByText('Open it'))
        await flush()

        expect(router.values.location.pathname).toMatch(new RegExp(`${urls.workflowsEmailDomain(existing.id)}$`))
    })

    it('opens the existing sender next to an email being written', async () => {
        backend.addSender({ email: `hello@${DOMAIN}` })
        await renderInApp(<EmailSetupModal entry="transactional" onClose={jest.fn()} onComplete={jest.fn()} />)

        fireEvent.change(document.getElementById('email-domain-another-domain') as HTMLInputElement, {
            target: { value: 'acme.com' },
        })
        fireEvent.click(element('email-domain-use-custom-domain'))
        await flush()

        expect(screen.getByText('Open it').closest('a')).toHaveAttribute('target', '_blank')
    })

    describe('adding a sender to an existing domain', () => {
        const OTHER_DOMAIN = 'news.example.com'

        beforeEach(() => {
            backend.addSender({ email: `hello@${DOMAIN}`, name: 'Acme', verified: true })
            backend.verifyDomain(DOMAIN)
            backend.addSender({ email: `team@${OTHER_DOMAIN}`, name: 'Acme news', verified: true })
            backend.verifyDomain(OTHER_DOMAIN)
        })

        const addSenderButtonOf = (domain: string): HTMLElement => {
            const row = screen.getByText(domain).closest('.rounded') as HTMLElement
            return within(row).getByText('Add sender')
        }

        it('creates a verified sender on the domain picked from the email card', async () => {
            await renderInApp(<MessageChannels />)
            fireEvent.click(element('workflows-channel-catalog-connect-email'))
            await flush()

            fireEvent.click(element('email-sender-add-domain'))
            fireEvent.click(within(document.querySelector('.Popover') as HTMLElement).getByText(OTHER_DOMAIN))
            fireEvent.change(element('email-sender-add-local-part'), {
                target: { value: 'billing' },
            })
            fireEvent.click(element('email-sender-add-submit'))
            await flush()

            await waitForModalToClose()

            expect(backend.senderConfig(44)).toMatchObject({
                email: `billing@${OTHER_DOMAIN}`,
                name: 'Acme news',
                provider: 'ses',
                domain: OTHER_DOMAIN,
                verified: true,
            })
            expect(screen.queryByText('Add a sender')).not.toBeInTheDocument()
            expect(screen.getByText('2 senders')).toBeInTheDocument()
        })

        it('creates and announces one sender when the address changes and Enter is pressed again while saving', async () => {
            await renderInApp(
                <>
                    <ToastContainer />
                    <MessageChannels />
                </>
            )
            fireEvent.click(addSenderButtonOf(OTHER_DOMAIN))
            await flush()
            const address = element('email-sender-add-local-part')
            fireEvent.change(address, { target: { value: 'billing' } })
            fireEvent.keyDown(address, { key: 'Enter' })
            fireEvent.change(address, { target: { value: 'support' } })
            fireEvent.keyDown(address, { key: 'Enter' })
            await flush()

            expect(backend.senderConfig(44)).toMatchObject({ email: `billing@${OTHER_DOMAIN}` })
            expect(backend.senderConfig(45)).toBeUndefined()
            expect(screen.getAllByText(`Added billing@${OTHER_DOMAIN} as a sender`)).toHaveLength(1)
            expect(screen.queryByText(`Added support@${OTHER_DOMAIN} as a sender`)).not.toBeInTheDocument()
        })

        it('keeps the add sender button disabled for project members below admin', async () => {
            teamLogic.actions.loadCurrentTeamSuccess({
                ...MOCK_DEFAULT_TEAM,
                effective_membership_level: OrganizationMembershipLevel.Member,
            })
            await renderInApp(<MessageChannels />)
            fireEvent.click(addSenderButtonOf(OTHER_DOMAIN))
            await flush()

            expect(addSenderButtonOf(OTHER_DOMAIN).closest('button')).toHaveAttribute('aria-disabled', 'true')
            expect(screen.queryByText('Add a sender')).not.toBeInTheDocument()
        })

        it('picks the domain of the row whose add sender button was clicked', async () => {
            await renderInApp(<MessageChannels />)
            fireEvent.click(addSenderButtonOf(OTHER_DOMAIN))
            await flush()

            expect(screen.getByText('Add a sender')).toBeInTheDocument()
            expect(screen.getByText(`@${OTHER_DOMAIN}`)).toBeInTheDocument()
        })

        it('opens the domain setup page for a new domain', async () => {
            await renderInApp(<MessageChannels />)
            fireEvent.click(element('workflows-channel-catalog-connect-email'))
            await flush()
            fireEvent.click(element('email-sender-add-new-domain'))
            await flush()
            await waitForModalToClose()

            expect(router.values.location.pathname).toMatch(new RegExp(`${urls.workflowsEmailDomain('new')}$`))
            expect(screen.queryByText('Add a sender')).not.toBeInTheDocument()
        })

        it('sends an unverified domain to finish its verification instead of adding a sender', async () => {
            const unverified = backend.addSender({ email: 'hi@pending.example.com' })
            await renderInApp(<MessageChannels />)
            fireEvent.click(addSenderButtonOf('pending.example.com'))
            await flush()

            expect(element('email-sender-add-submit')).toHaveAttribute('aria-disabled', 'true')
            fireEvent.click(element('email-sender-add-finish-verification'))
            await flush()
            await waitForModalToClose()

            expect(router.values.location.pathname).toMatch(new RegExp(`${urls.workflowsEmailDomain(unverified.id)}$`))
            expect(
                within(screen.getByText('pending.example.com').closest('.rounded') as HTMLElement).getByText('1 sender')
            ).toBeInTheDocument()
        })
    })

    it('stays on the submitted domain and offers to finish verification when a new sender from the email card does not verify', async () => {
        backend.addSender({ email: 'hi@stale.example.com', name: 'Stale', verified: true })
        backend.addSender({ email: 'team@news.example.com', name: 'News', verified: true })
        backend.verifyDomain('news.example.com')
        await renderInApp(<MessageChannels />)
        fireEvent.click(element('workflows-channel-catalog-connect-email'))
        await flush()
        fireEvent.change(element('email-sender-add-local-part'), { target: { value: 'billing' } })
        const releaseCreate = backend.hold('integration_create')
        fireEvent.click(element('email-sender-add-submit'))
        await flush()
        fireEvent.click(element('email-sender-add-domain'))
        fireEvent.click(within(document.querySelector('.Popover') as HTMLElement).getByText('news.example.com'))
        releaseCreate()
        await flush()
        await waitForModalToClose()

        expect(screen.getByText('stale.example.com is not verified yet.', { exact: false })).toBeInTheDocument()
        fireEvent.click(element('email-sender-add-finish-verification'))
        await flush()

        expect(backend.senderConfig(44)).toMatchObject({ email: 'billing@stale.example.com', verified: false })
        expect(router.values.location.pathname).toMatch(new RegExp(`${urls.workflowsEmailDomain(44)}$`))
    })
})
