import '@testing-library/jest-dom'

import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { Provider } from 'kea'
import { router } from 'kea-router'

import { FEATURE_FLAGS } from 'lib/constants'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { EmailSetupModal } from '../EmailSetup/EmailSetupModal'
import { MessageChannels } from '../MessageChannels'
import { FakeEmailDomainBackend } from './__mocks__/fakeEmailDomainBackend'
import { addEmailSenderLogic } from './addEmailSenderLogic'

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

const expectOldBroadcastModal = (): void => {
    expect(screen.getByText(LEGACY_MODAL_TITLE)).toBeInTheDocument()
}

const expectAddSenderModal: EntryExpectation = () => {
    expect(screen.getByText('Add a sender')).toBeInTheDocument()
    expect(router.values.location.pathname).toMatch(/\/workflows\/channels$/)
}

const expectWizardInBroadcastModal = (): void => {
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
        jest.useRealTimers()
    })

    describe.each([
        ['off', false, expectOldModal, expectOldModal, expectOldBroadcastModal, expectOldModal],
        [
            'on',
            true,
            expectSendingDomainPage,
            expectWizardModalForSender,
            expectWizardInBroadcastModal,
            expectAddSenderModal,
        ],
    ])(
        'with the wizard flag %s',
        (_, wizardEnabled, expectEntry, expectConfigure, expectBroadcastModal, expectAddAnother) => {
            beforeEach(() => setWizardFlag(wizardEnabled))

            it('starts from the email card in the channel catalog', async () => {
                await renderInApp(<MessageChannels />)
                expect(screen.queryByText(LEGACY_MODAL_TITLE)).not.toBeInTheDocument()
                fireEvent.click(element('workflows-channel-catalog-connect-email'))
                await flush()
                expectEntry(urls.workflowsEmailDomain('new'))
            })

            it('adds another sender from the email card once a domain exists', async () => {
                backend.addSender({ email: `hello@${DOMAIN}`, verified: true })
                await renderInApp(<MessageChannels />)
                expect(document.querySelector('[data-attr="email-domain-add-sender"]') !== null).toBe(wizardEnabled)
                fireEvent.click(element('workflows-channel-catalog-connect-email'))
                await flush()
                expectAddAnother('')
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

            it('starts from the broadcast sender modal', async () => {
                const onComplete = jest.fn()
                await renderInApp(<EmailSetupModal entry="broadcast" onClose={jest.fn()} onComplete={onComplete} />)
                expectBroadcastModal()
                expect(onComplete).not.toHaveBeenCalled()
            })
        }
    )

    it('closes the setup modal when the person opens the full page from configure', async () => {
        setWizardFlag(true)
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
            setWizardFlag(true)
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
    describe('adding a sender to an existing domain', () => {
        const OTHER_DOMAIN = 'news.example.com'

        beforeEach(() => {
            setWizardFlag(true)
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

            expect(backend.requestsTo('integration_create').map((request) => request.body)).toEqual([
                {
                    kind: 'email',
                    config: expect.objectContaining({
                        email: `billing@${OTHER_DOMAIN}`,
                        name: 'Acme news',
                        provider: 'ses',
                    }),
                },
            ])
            const created = backend.senderConfig(44)
            expect(created).toMatchObject({ email: `billing@${OTHER_DOMAIN}`, verified: true })
            expect(addEmailSenderLogic.values.isOpen).toBe(false)
            expect(screen.getByText('2 senders')).toBeInTheDocument()
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

            expect(router.values.location.pathname).toMatch(new RegExp(`${urls.workflowsEmailDomain('new')}$`))
            expect(addEmailSenderLogic.values.isOpen).toBe(false)
        })

        it('sends an unverified domain to finish its verification instead of adding a sender', async () => {
            const unverified = backend.addSender({ email: 'hi@pending.example.com' })
            await renderInApp(<MessageChannels />)
            fireEvent.click(addSenderButtonOf('pending.example.com'))
            await flush()

            expect(element('email-sender-add-submit')).toHaveAttribute('aria-disabled', 'true')
            fireEvent.click(element('email-sender-add-finish-verification'))
            await flush()

            expect(router.values.location.pathname).toMatch(new RegExp(`${urls.workflowsEmailDomain(unverified.id)}$`))
            expect(backend.requestsTo('integration_create')).toEqual([])
        })
    })
})
