import { MOCK_DEFAULT_ORGANIZATION } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { Provider, useValues } from 'kea'
import { router } from 'kea-router'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { organizationLogic } from 'scenes/organizationLogic'
import { urls } from 'scenes/urls'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { DataSuggestionApi } from '../../generated/api.schemas'
import { FakeEmailDomainBackend } from './__mocks__/fakeEmailDomainBackend'
import { EmailDomainScene } from './EmailDomainScene'

const DOMAIN = 'mail.acme.com'
const SUGGESTED_WORKFLOW: DataSuggestionApi = {
    id: 'suggestion-1',
    name: 'Welcome new teammates',
    description: 'Email a new teammate a getting started guide after they join a workspace.',
    reason: 'teammate_joined fires every day.',
    trigger_event: 'teammate_joined',
    weekly_count: 120,
    stage: 'onboarding',
    premade: false,
    step_outline: ['email', 'delay', 'email'],
}
const SENDER_ID = 42
const POLL_MS = 10_000

/** Renders the scene for whichever sender the URL names, the way the scene router does in the app. */
function RoutedScene(): JSX.Element {
    const { location } = useValues(router)
    const id = location.pathname.match(/\/workflows\/channels\/email\/([^/]+)/)?.[1] ?? 'new'
    return <EmailDomainScene id={id} />
}

const element = (attr: string): HTMLElement => {
    const found = document.querySelector<HTMLElement>(`[data-attr="${attr}"]`)
    if (!found) {
        throw new Error(`No element with data-attr ${attr} on the page`)
    }
    return found
}

const click = (attr: string): void => {
    fireEvent.click(element(attr))
}

const typeInto = (id: string, value: string): void => {
    fireEvent.change(document.getElementById(id) as HTMLInputElement, { target: { value } })
}

const flush = async (ms = 0): Promise<void> => {
    await act(async () => {
        await jest.advanceTimersByTimeAsync(ms)
    })
}

const expectStep = (title: string | RegExp): void => {
    expect(screen.getByText(title)).toBeInTheDocument()
}

const expectProgress = (text: string): void => {
    expect(screen.getAllByText(text).length).toBeGreaterThan(0)
}

describe('EmailDomainScene', () => {
    let backend: FakeEmailDomainBackend

    const open = async (path: string): Promise<void> => {
        router.actions.push(path)
        render(
            <Provider>
                <RoutedScene />
            </Provider>
        )
        await flush()
    }

    const turnOnSuggestions = (on: boolean): void => {
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.WORKFLOWS_EMAIL_DOMAIN_WIZARD]: true })
        organizationLogic.actions.loadCurrentOrganizationSuccess({
            ...MOCK_DEFAULT_ORGANIZATION,
            is_ai_data_processing_approved: on,
        })
    }

    const seedSender = (): void => {
        backend.addSender({ email: `hello@${DOMAIN}` })
    }

    beforeEach(() => {
        jest.useFakeTimers()
        backend = new FakeEmailDomainBackend()
        backend.hostDnsAt('acme.com', 'cloudflare')
        useMocks(backend.mocks())
        initKeaTests()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.WORKFLOWS_EMAIL_DOMAIN_WIZARD], {
            [FEATURE_FLAGS.WORKFLOWS_EMAIL_DOMAIN_WIZARD]: true,
        })
    })

    afterEach(() => {
        cleanup()
        jest.useRealTimers()
        jest.restoreAllMocks()
    })

    it('takes a typed domain through the manual path to a verified first sender', async () => {
        await open(urls.workflowsEmailDomain('new'))
        expectStep('Which domain should your emails come from?')

        typeInto('email-domain-another-domain', 'acme.com')
        click('email-domain-use-custom-domain')
        expect(screen.getByText('hello@mail.acme.com')).toBeInTheDocument()
        typeInto('email-domain-sender-name-input', 'Support team')
        typeInto('email-domain-local-part', 'support')
        expect(screen.getByText('support@mail.acme.com')).toBeInTheDocument()

        // Tests run as a local stack, which starts on Maildev.
        click('email-domain-local-provider-ses')
        click('email-domain-continue')
        await flush()
        expect(backend.requestsTo('integration_create')[0].body).toEqual({
            kind: 'email',
            config: {
                email: 'support@mail.acme.com',
                name: 'Support team',
                provider: 'ses',
                mail_from_subdomain: 'feedback',
            },
        })
        expect(router.values.location.pathname).toMatch(new RegExp(`${urls.workflowsEmailDomain(SENDER_ID)}$`))
        expectStep('Add 8 settings at Cloudflare')

        click('email-domain-reveal-records')
        await flush()
        expect(screen.getByText('Proves you own the domain')).toBeInTheDocument()
        expect(backend.requestsTo('email_update').map((request) => request.body)).toEqual([
            { config: expect.objectContaining({ setup_method: 'manual' }) },
        ])
        expect(backend.senderConfig(SENDER_ID)?.setup_method).toBe('manual')

        backend.publishRecords(DOMAIN)
        await flush(POLL_MS)
        expectStep('Checking your settings…')
        expectProgress('8 of 8 found')

        backend.verifyDomain(DOMAIN)
        await flush(POLL_MS)
        expectStep(/You can send from/)
        expect(screen.getByText('Your first sender')).toBeInTheDocument()
        expect(screen.getByText(`Send your first email from ${DOMAIN}`)).toBeInTheDocument()

        typeInto('email-domain-sender-name', 'Acme Team')
        click('email-domain-save-sender-name')
        await flush()
        expect(backend.senderConfig(SENDER_ID)?.name).toBe('Acme Team')
        expect(document.querySelector('[data-attr="email-domain-save-sender-name"]')).toBeNull()

        click('email-domain-send-test-email')
        await flush()
        const invocation = backend.requestsTo('test_email')[0].body as any
        const emailInput = invocation.configuration.actions[1].config.inputs.email.value
        expect(emailInput.from).toEqual({ integrationId: SENDER_ID })
        expect(emailInput.to.email).toBe(invocation.globals.person.properties.email)
        expect(screen.getByText('Send another test')).toBeInTheDocument()
    })

    it('sends the person to Cloudflare and verifies after they return', async () => {
        seedSender()
        const tab = { location: { href: '' }, opener: {}, close: jest.fn() }
        jest.spyOn(window, 'open').mockReturnValue(tab as unknown as Window)
        await open(urls.workflowsEmailDomain(SENDER_ID))
        expectStep('Add 8 settings at Cloudflare')

        click('email-domain-auto-configure')
        await flush()
        const returnUrl = `http://localhost/project/997${urls.workflowsEmailDomain(SENDER_ID)}?domain_connect=email`
        expect(backend.requestsTo('domain_connect_apply_url')[0].body).toEqual({
            context: 'email',
            integration_id: SENDER_ID,
            redirect_uri: returnUrl,
        })
        expect(tab.location.href).toContain(`redirect_uri=${encodeURIComponent(returnUrl)}`)
        expect(backend.senderConfig(SENDER_ID)?.setup_method).toBe('auto')

        backend.approveDomainConnect(DOMAIN)
        cleanup()
        await open(`${urls.workflowsEmailDomain(SENDER_ID)}?domain_connect=email`)
        expect(router.values.location.search).toBe('')
        expect(backend.requestsTo('email_status').at(-1)?.url).toContain('refresh=true')
        expectStep('Checking your settings…')
        expectProgress('8 of 8 found')

        backend.verifyDomain(DOMAIN)
        await flush(POLL_MS)
        expectStep(/You can send from/)
    })

    it('stays on the settings when the return from Cloudflare brought no records, and still finds them later', async () => {
        seedSender()
        await open(`${urls.workflowsEmailDomain(SENDER_ID)}?domain_connect=email`)
        expectStep('Checking your settings…')
        expectProgress('0 of 8 found')
        expect(backend.senderConfig(SENDER_ID)?.verified).toBe(false)

        backend.publishRecords(DOMAIN)
        await flush(POLL_MS)
        expectProgress('8 of 8 found')
        backend.verifyDomain(DOMAIN)
        await flush(POLL_MS)
        expectStep(/You can send from/)
    })

    it('replaces the template with workflows suggested from the data, loaded while DNS was checked', async () => {
        const capture = jest.spyOn(posthog, 'capture')
        const shownEvents = (): unknown[][] =>
            capture.mock.calls.filter(([event]) => event === 'workflows data suggestions shown')
        turnOnSuggestions(true)
        seedSender()
        backend.publishRecords(DOMAIN)
        backend.suggestWorkflows([
            SUGGESTED_WORKFLOW,
            { ...SUGGESTED_WORKFLOW, id: 'suggestion-2', name: 'Nudge trials before they end', stage: 'trial' },
        ])
        await open(urls.workflowsEmailDomain(SENDER_ID))
        expectStep('Checking your settings…')
        expect(screen.queryByText('Welcome new teammates')).not.toBeInTheDocument()
        expect(shownEvents()).toHaveLength(0)

        backend.verifyDomain(DOMAIN)
        await flush(POLL_MS)
        expectStep(/You can send from/)
        expect(screen.getByText('Welcome new teammates')).toBeInTheDocument()
        expect(element('workflows-data-suggestion-ai')).toHaveTextContent('Create workflow')
        expect(document.querySelector('[data-attr="email-domain-create-welcome-workflow"]')).toBeNull()
        expect(document.querySelector('[data-attr="email-domain-create-blank-workflow"]')).toBeNull()
        expect(backend.requestsTo('data_suggestions_generate')).toHaveLength(1)
        expect(shownEvents()).toEqual([
            [
                'workflows data suggestions shown',
                expect.objectContaining({ surface: 'email_domain_wizard', stages: ['onboarding'] }),
            ],
        ])

        expect(screen.queryByText('Nudge trials before they end')).not.toBeInTheDocument()
        click('email-domain-show-more-suggestions')
        await flush()
        expect(screen.getByText('Nudge trials before they end')).toBeInTheDocument()
        expect(shownEvents().at(-1)?.[1]).toMatchObject({ stages: ['onboarding', 'trial'] })

        click('email-domain-skip-suggestions')
        expect(screen.queryByText('Welcome new teammates')).not.toBeInTheDocument()
        expect(element('email-domain-create-welcome-workflow')).toBeInTheDocument()
        click('email-domain-create-blank-workflow')
        expect(router.values.location.pathname).toContain(urls.workflowNew())
        expect(router.values.searchParams).not.toHaveProperty('templateId')
    })

    it.each<[string, boolean, (backend: FakeEmailDomainBackend) => void]>([
        ['suggestions are off', false, (fake) => fake.suggestWorkflows([SUGGESTED_WORKFLOW])],
        ['no suggestion could be made', true, () => {}],
        ['the suggestions fail to load', true, (fake) => fake.fail('data_suggestions_generate', { status: 500 })],
        ['the suggestions request is still pending', true, (fake) => void fake.hold('data_suggestions_generate')],
        [
            'the suggestions are still being written',
            true,
            (fake) => (fake.dataSuggestions = { status: 'generating', suggestions: [] }),
        ],
    ])(
        'keeps the welcome template and a blank workflow on the last step when %s',
        async (_, suggestionsOn, prepare) => {
            turnOnSuggestions(suggestionsOn)
            seedSender()
            backend.verifyDomain(DOMAIN)
            prepare(backend)
            await open(urls.workflowsEmailDomain(SENDER_ID))
            expectStep(/You can send from/)
            expect(document.querySelector('[data-attr="workflows-data-suggestion-ai"]')).toBeNull()
            expect(element('email-domain-create-welcome-workflow')).toHaveClass('LemonButton--primary')
            expect(element('email-domain-create-blank-workflow')).toHaveTextContent('Blank workflow')
            click('email-domain-create-welcome-workflow')
            expect(router.values.location.pathname).toContain(urls.workflowNew())
            expect(router.values.searchParams).toHaveProperty('templateId')
        }
    )

    it('refuses a second submit while creating, shows the error, and lets the person try again', async () => {
        const release = backend.hold('integration_create')
        backend.failOnce('integration_create', {
            status: 400,
            body: { detail: 'This domain is already used by another organization' },
        })
        await open(urls.workflowsEmailDomain('new'))
        typeInto('email-domain-another-domain', 'acme.com')
        click('email-domain-use-custom-domain')

        click('email-domain-continue')
        click('email-domain-continue')
        await flush()
        expect(backend.requestsTo('integration_create')).toHaveLength(1)

        silenceKeaLoadersErrors()
        release()
        await flush()
        resumeKeaLoadersErrors()
        expect(screen.getByText('This domain is already used by another organization')).toBeInTheDocument()
        expect(router.values.location.pathname).toMatch(/\/new$/)

        click('email-domain-continue')
        await flush()
        expect(backend.requestsTo('integration_create')).toHaveLength(2)
        expectStep('Add 8 settings at Cloudflare')
    })

    it('drops "first" from the ready step when the project already sends from another domain', async () => {
        seedSender()
        backend.verifyDomain(DOMAIN)
        backend.addSender({ email: 'hello@mail.acme.org' })
        backend.verifyDomain('mail.acme.org')
        await open(urls.workflowsEmailDomain(SENDER_ID))
        expectStep(/You can send from/)

        expect(screen.getByText('Your sender')).toBeInTheDocument()
        expect(screen.getByText(`Send email from ${DOMAIN}`)).toBeInTheDocument()
        expect(screen.queryByText(/first/i)).toBeNull()
    })

    it('keeps the edited sender name on screen when the save fails, and saves it on the next try', async () => {
        seedSender()
        backend.verifyDomain(DOMAIN)
        backend.failOnce('email_update', { status: 500, body: { detail: 'Could not reach the email provider' } })
        await open(urls.workflowsEmailDomain(SENDER_ID))
        expectStep(/You can send from/)

        typeInto('email-domain-sender-name', 'Acme Team')
        click('email-domain-save-sender-name')
        await flush()
        expect(document.getElementById('email-domain-sender-name')).toHaveValue('Acme Team')
        expect(backend.senderConfig(SENDER_ID)?.name).toBe('Acme')

        click('email-domain-save-sender-name')
        await flush()
        expect(backend.senderConfig(SENDER_ID)?.name).toBe('Acme Team')
        expect(document.querySelector('[data-attr="email-domain-save-sender-name"]')).toBeNull()
    })

    it('offers try again when the sender does not load, then shows the settings', async () => {
        seedSender()
        backend.failOnce('integration_get', { status: 500, body: { detail: 'Could not reach the email provider' } })
        silenceKeaLoadersErrors()
        await open(urls.workflowsEmailDomain(SENDER_ID))
        resumeKeaLoadersErrors()
        expectStep('We could not load your sending domain')

        click('email-domain-retry')
        await flush()
        expectStep('Add 8 settings at Cloudflare')
        expect(backend.requestsTo('integration_get')).toHaveLength(2)
    })

    it('keeps the progress on screen when a status check fails after the records were found', async () => {
        seedSender()
        backend.publishRecords(DOMAIN)
        await open(urls.workflowsEmailDomain(SENDER_ID))
        expectProgress('8 of 8 found')

        backend.fail('email_status', { status: 503, body: { code: 'ses_unavailable', detail: 'SES is down' } })
        await flush(POLL_MS)
        expectStep('Checking your settings…')
        expectProgress('8 of 8 found')
        expect(document.querySelector('[data-attr="email-domain-retry"]')).toBeNull()

        backend.recover('email_status')
        backend.verifyDomain(DOMAIN)
        await flush(POLL_MS)
        expectStep(/You can send from/)
    })

    it.each([
        ['still confirming', false, 'Your records are in place'],
        ['reporting a temporary failure', true, "The email provider can't confirm your records yet"],
    ])(
        'describes found records when automatic checks stop while the provider is %s',
        async (_, temporaryFailure, heading) => {
            seedSender()
            backend.publishRecords(DOMAIN)
            if (temporaryFailure) {
                backend.sesReports(DOMAIN, 'temporary_failure')
            }
            await open(urls.workflowsEmailDomain(SENDER_ID))

            await flush(31 * 60_000)
            expectStep(heading)
            expect(screen.queryByText(/still missing/)).not.toBeInTheDocument()
            expect(screen.queryByText(/could not find these settings/)).not.toBeInTheDocument()
        }
    )

    it('falls back to the generic manual setup when host detection fails', async () => {
        seedSender()
        backend.fail('domain_connect_check', { status: 500, body: { detail: 'DNS lookup timed out' } })
        await open(urls.workflowsEmailDomain(SENDER_ID))
        expectStep('Add 8 settings at your DNS host')
        expect(document.querySelector('[data-attr="email-domain-auto-configure"]')).toBeNull()
        expect(element('email-domain-records-added')).toBeInTheDocument()
    })

    it('lets the person restart a stopped verification again after the first restart fails', async () => {
        seedSender()
        backend.sesReports(DOMAIN, 'failed')
        backend.failOnce('email_verify', { status: 500, body: { detail: 'SES is down' } })
        await open(urls.workflowsEmailDomain(SENDER_ID))
        expectStep('Verification stopped')

        click('email-domain-restart-verification')
        await flush()
        expectStep('Verification stopped')
        expect(element('email-domain-restart-verification')).not.toHaveAttribute('aria-disabled', 'true')

        click('email-domain-restart-verification')
        await flush()
        expect(backend.requestsTo('email_verify')).toHaveLength(2)
        expectStep('Add 8 settings at Cloudflare')
    })
    it.each([
        ['skipped', { status: 'skipped', reason: 'The recipient has no reachable mail servers.' }],
        ['unknown', undefined],
        ['failed', { status: 'failed', reason: 'The provider refused the message.' }],
    ])('does not claim a test email was sent when the send result is %s', async (_, emailSendResult) => {
        seedSender()
        backend.verifyDomain(DOMAIN)
        const mocks = backend.mocks()
        useMocks({
            ...mocks,
            post: {
                ...mocks.post,
                '/api/environments/:team_id/hog_flows/:id/invocations/': () => ({
                    status: 'success',
                    nextActionId: 'exit_node',
                    logs: [],
                    emailSendResult,
                }),
            },
        })
        await open(urls.workflowsEmailDomain(SENDER_ID))
        click('email-domain-send-test-email')
        await flush()
        expect(screen.queryByText('Send another test')).not.toBeInTheDocument()
        expect(screen.getByText('Send me a test email')).toBeInTheDocument()
    })

    it('offers another test only after the email provider accepted the message', async () => {
        seedSender()
        backend.verifyDomain(DOMAIN)
        const mocks = backend.mocks()
        useMocks({
            ...mocks,
            post: {
                ...mocks.post,
                '/api/environments/:team_id/hog_flows/:id/invocations/': () => ({
                    status: 'success',
                    nextActionId: 'exit_node',
                    emailSendResult: { status: 'accepted' },
                }),
            },
        })
        await open(urls.workflowsEmailDomain(SENDER_ID))
        click('email-domain-send-test-email')
        await flush()
        expect(screen.getByText('Send another test')).toBeInTheDocument()
    })
})
