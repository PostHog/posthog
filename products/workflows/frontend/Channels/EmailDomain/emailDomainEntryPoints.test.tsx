import '@testing-library/jest-dom'

import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { Provider } from 'kea'
import { router } from 'kea-router'
import posthog from 'posthog-js'

import { SetupTaskId } from 'lib/components/ProductSetup'
import { FEATURE_FLAGS } from 'lib/constants'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { WizardChannelStep } from '../../setupGuide/wizard/WizardChannelStep'
import { EmailSetupModal } from '../EmailSetup/EmailSetupModal'
import { MessageChannels } from '../MessageChannels'
import { FakeEmailDomainBackend } from './__mocks__/fakeEmailDomainBackend'

const DOMAIN = 'mail.acme.com'
const SENDER_ID = 42
const POLL_MS = 10_000
const LEGACY_MODAL_TITLE = 'Configure email sender'

const element = (attr: string): HTMLElement => {
    const found = document.querySelector<HTMLElement>(`[data-attr="${attr}"]`)
    if (!found) {
        throw new Error(`No element with data-attr ${attr} on the page`)
    }
    return found
}

const closedEvents = (capture: jest.SpyInstance): unknown[][] =>
    capture.mock.calls.filter(([event]) => event === 'email domain setup closed')

const startSetupFor = (domain: string): void => {
    fireEvent.change(document.getElementById('email-domain-another-domain') as HTMLInputElement, {
        target: { value: domain },
    })
    fireEvent.click(element('email-domain-use-custom-domain'))
    fireEvent.click(element('email-domain-continue'))
}

const flush = async (ms = 0): Promise<void> => {
    await act(async () => {
        await jest.advanceTimersByTimeAsync(ms)
    })
}

const renderInApp = async (ui: JSX.Element): Promise<void> => {
    render(<Provider>{ui}</Provider>)
    await flush()
}

type EntryExpectation = (pagePath: string) => void

const expectOldModal: EntryExpectation = () => {
    expect(screen.getByText(LEGACY_MODAL_TITLE)).toBeInTheDocument()
    expect(router.values.location.pathname).toMatch(/\/workflows\/channels$/)
}

const expectSendingDomainPage: EntryExpectation = (pagePath) => {
    expect(router.values.location.pathname).toMatch(new RegExp(`${pagePath}$`))
    expect(screen.queryByText(LEGACY_MODAL_TITLE)).not.toBeInTheDocument()
}

const expectWizardModalForSender: EntryExpectation = (pagePath) => {
    expect(screen.getByText('Verify your sending domain')).toBeInTheDocument()
    expect(router.values.location.pathname).toMatch(/\/workflows\/channels$/)
    expect(screen.getByText('Open full page').closest('a')).toHaveAttribute('href', expect.stringContaining(pagePath))
}

const expectOldModalInPlace = (): void => {
    expect(screen.getByText(LEGACY_MODAL_TITLE)).toBeInTheDocument()
}

const expectWizardModalAtDomainStep = (): void => {
    expect(screen.getByText('Set up a sending domain')).toBeInTheDocument()
    expect(screen.getByText('Which domain should your emails come from?')).toBeInTheDocument()
}

describe('email domain setup entry points', () => {
    let backend: FakeEmailDomainBackend

    const setWizardFlag = (enabled: boolean): void => {
        featureFlagLogic.actions.setFeatureFlags(enabled ? [FEATURE_FLAGS.WORKFLOWS_EMAIL_DOMAIN_WIZARD] : [], {
            [FEATURE_FLAGS.WORKFLOWS_EMAIL_DOMAIN_WIZARD]: enabled,
        })
    }

    beforeEach(() => {
        jest.useFakeTimers()
        backend = new FakeEmailDomainBackend()
        backend.hostDnsAt('acme.com', 'cloudflare')
        useMocks(backend.mocks())
        initKeaTests()
        featureFlagLogic.mount()
        router.actions.push(urls.workflows('channels'))
    })

    afterEach(() => {
        cleanup()
        jest.restoreAllMocks()
        jest.useRealTimers()
    })

    describe.each([
        ['off', false, expectOldModal, expectOldModal, expectOldModalInPlace],
        ['on', true, expectSendingDomainPage, expectWizardModalForSender, expectWizardModalAtDomainStep],
    ])('with the wizard flag %s', (_, wizardEnabled, expectEntry, expectConfigure, expectModalInPlace) => {
        beforeEach(() => setWizardFlag(wizardEnabled))

        it('starts from the email card in the channel catalog', async () => {
            await renderInApp(<MessageChannels />)
            expect(screen.queryByText(LEGACY_MODAL_TITLE)).not.toBeInTheDocument()
            fireEvent.click(element('workflows-channel-catalog-connect-email'))
            await flush()
            expectEntry(urls.workflowsEmailDomain('new'))
        })

        it('starts from configure on an unverified sender', async () => {
            backend.addSender({ email: `hello@${DOMAIN}` })
            await renderInApp(<MessageChannels />)
            fireEvent.click(screen.getByText(DOMAIN))
            expect(screen.getByText('Unverified')).toBeInTheDocument()
            fireEvent.click(screen.getByText('Configure'))
            await flush()
            expectConfigure(urls.workflowsEmailDomain(SENDER_ID))
        })

        it('keeps the sender settings for configure on a verified sender', async () => {
            backend.addSender({ email: `hello@${DOMAIN}`, verified: true })
            await renderInApp(<MessageChannels />)
            fireEvent.click(screen.getByText(DOMAIN))
            fireEvent.click(screen.getByText('Configure'))
            await flush()
            expectOldModal('')
        })

        it('starts from Connect email on the onboarding channel step', async () => {
            await renderInApp(<WizardChannelStep />)
            fireEvent.click(element('workflows-onboarding-wizard-connect-email'))
            await flush()
            expectModalInPlace()
            expect(router.values.location.pathname).toMatch(/\/workflows\/channels$/)
        })

        it('starts from the broadcast sender modal', async () => {
            const onComplete = jest.fn()
            await renderInApp(
                <EmailSetupModal entry="broadcast" surface="broadcast" onClose={jest.fn()} onComplete={onComplete} />
            )
            expectModalInPlace()
            expect(onComplete).not.toHaveBeenCalled()
        })
    })

    it('closes the setup modal when the person opens the full page from configure', async () => {
        setWizardFlag(true)
        const capture = jest.spyOn(posthog, 'capture')
        backend.addSender({ email: `hello@${DOMAIN}` })
        await renderInApp(<MessageChannels />)
        fireEvent.click(screen.getByText(DOMAIN))
        fireEvent.click(screen.getByText('Configure'))
        await flush()

        fireEvent.click(screen.getByText('Open full page'))
        await flush()

        expect(router.values.location.pathname).toMatch(new RegExp(`${urls.workflowsEmailDomain(SENDER_ID)}$`))
        expect(integrationsLogic.values.setupModalOpen).toBe(false)
        expect(closedEvents(capture)).toEqual([
            ['email domain setup closed', { furthest_step: 'settings', surface: 'channels', completed: false }],
        ])
    })

    it.each([
        ['broadcast' as const, '_blank'],
        [undefined, null],
    ])(
        'stays open for the settings after creating a sender, and reports it when closed (entry %s)',
        async (entry, fullPageTarget) => {
            setWizardFlag(true)
            const onComplete = jest.fn()
            const onClose = jest.fn()
            await renderInApp(
                <EmailSetupModal entry={entry} surface="channels" onClose={onClose} onComplete={onComplete} />
            )

            startSetupFor('acme.com')
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

    it.each([
        { furthestStep: 'domain', completed: false, advance: async (): Promise<void> => {} },
        {
            furthestStep: 'settings',
            completed: false,
            advance: async (): Promise<void> => {
                startSetupFor('acme.com')
                await flush()
            },
        },
        {
            furthestStep: 'verifying',
            completed: false,
            advance: async (): Promise<void> => {
                startSetupFor('acme.com')
                await flush()
                backend.publishRecords(DOMAIN)
                await flush(POLL_MS)
            },
        },
        {
            furthestStep: 'ready',
            completed: true,
            advance: async (): Promise<void> => {
                startSetupFor('acme.com')
                await flush()
                backend.publishRecords(DOMAIN)
                await flush(POLL_MS)
                backend.verifyDomain(DOMAIN)
                await flush(POLL_MS)
            },
        },
    ])(
        'reports the furthest step $furthestStep when the onboarding wizard modal closes',
        async ({ furthestStep, completed, advance }) => {
            setWizardFlag(true)
            const capture = jest.spyOn(posthog, 'capture')
            await renderInApp(<WizardChannelStep />)
            fireEvent.click(element('workflows-onboarding-wizard-connect-email'))
            await flush()
            await advance()

            fireEvent.click(screen.getByLabelText('close'))
            await flush()

            expect(closedEvents(capture)).toEqual([
                ['email domain setup closed', { furthest_step: furthestStep, surface: 'onboarding_wizard', completed }],
            ])
        }
    )

    it('completes the onboarding channel task once the wizard creates the sender, with the hand-off in reach', async () => {
        setWizardFlag(true)
        const capture = jest.spyOn(posthog, 'capture')
        await renderInApp(<WizardChannelStep />)
        fireEvent.click(element('workflows-onboarding-wizard-connect-email'))
        await flush()

        startSetupFor('acme.com')
        await flush()

        expect(capture).toHaveBeenCalledWith('product setup task completed', {
            task: SetupTaskId.SetUpFirstWorkflowChannel,
        })
        expect(screen.getByText('Send to whoever manages DNS')).toBeInTheDocument()

        fireEvent.click(screen.getByLabelText('close'))
        await flush()
        expect(screen.queryByText('Verify your sending domain')).not.toBeInTheDocument()
        expect(screen.getByText('Your email channel is connected. Continue to the next step.')).toBeInTheDocument()
    })
})
