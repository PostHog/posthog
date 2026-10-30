import { MOCK_DEFAULT_ORGANIZATION } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { preflightLogic } from 'lib/logic/preflightLogic'
import { organizationLogic } from 'scenes/organizationLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { PreflightStatus } from '~/types'

import { FakeEmailDomainBackend } from './__mocks__/fakeEmailDomainBackend'
import { emailDomainWizardLogic } from './emailDomainWizardLogic'

describe('emailDomainWizardLogic', () => {
    let backend: FakeEmailDomainBackend

    beforeEach(() => {
        backend = new FakeEmailDomainBackend()
        useMocks(backend.mocks())
        initKeaTests()
    })

    const mountWizard = (): ReturnType<typeof emailDomainWizardLogic.build> => {
        const logic = emailDomainWizardLogic({ logicKey: 'test', onCreated: () => {} })
        logic.mount()
        return logic
    }

    it.each([
        ['acme.com', 'acme.com', 'hello'],
        ['  ACME.com ', 'acme.com', 'hello'],
        ['https://www.acme.com/pricing?x=1', 'acme.com', 'hello'],
        ['app.acme.com', 'app.acme.com', 'hello'],
        ['jane@acme.com', 'acme.com', 'jane'],
        ['Support@WWW.Acme.com', 'acme.com', 'support'],
    ])('turns the input %s into the domain %s and the address %s@', (input, domain, localPart) => {
        const logic = mountWizard()

        logic.actions.setCustomDomainInput(input)
        logic.actions.useCustomDomain()

        expect(logic.values.selectedDomain).toBe(domain)
        expect(logic.values.localPart).toBe(localPart)
        expect(logic.values.fromAddress).toBe(`${localPart}@mail.${domain}`)
    })

    it.each([
        ['jane@gmail.com', 'free_mailbox'],
        ['gmx.de', 'free_mailbox'],
        ['not a domain', 'invalid'],
        ['acme', 'invalid'],
        ['127.0.0.1', 'invalid'],
        ['http://10.0.0.5:3000', 'invalid'],
        ['acme.123', 'invalid'],
    ])('refuses %s as %s and keeps the domain unselected', (input, problem) => {
        const logic = mountWizard()

        logic.actions.setCustomDomainInput(input)
        logic.actions.useCustomDomain()

        expect(logic.values.customDomain.problem).toBe(problem)
        expect(logic.values.selectedDomain).toBeNull()
    })

    it.each([
        ['mail', 'news!', 'news'],
        ['send', 'Send', 'send'],
        ['', 'My Sub', 'mysub'],
    ])('keeps the sending subdomain to dns label characters: %s then %s becomes %s', (first, typed, expected) => {
        const logic = mountWizard()
        logic.actions.selectDomain('acme.com')

        logic.actions.setSendPrefix(first)
        logic.actions.setSendPrefix(typed)

        expect(logic.values.sendPrefix).toBe(expected)
        expect(logic.values.sendingDomain).toBe(`${expected}.acme.com`)
    })

    it.each([
        ['Hedgebox Inc.', 'hedgebox.example.com', 'Hedgebox Inc.'],
        ['  Acme Labs ', 'acme.com', 'Acme Labs'],
        ['', 'acme.com', 'Acme'],
        ["Jane's Organization", 'shop.acme.co.uk', 'Acme'],
        ['Default', 'acme.com.au', 'Acme'],
        ['', 'acme.io', 'Acme'],
        ['Müller GmbH', 'mueller.de', 'Mueller'],
        ['Acme "Labs"', 'acme.com', 'Acme'],
    ])('names the sender for the organization %p on %s as %s', async (organizationName, domain, senderName) => {
        organizationLogic.actions.loadCurrentOrganizationSuccess({
            ...MOCK_DEFAULT_ORGANIZATION,
            name: organizationName,
        })
        const logic = mountWizard()
        logic.actions.selectDomain(domain)

        await expectLogic(logic, () => logic.actions.createSender()).toFinishAllListeners()

        expect(backend.requestsTo('integration_create')[0].body).toMatchObject({ config: { name: senderName } })
    })

    const mountWithExistingSender = async (): Promise<ReturnType<typeof emailDomainWizardLogic.build>> => {
        backend.addSender({ email: 'hello@mail.acme.com', mail_from_subdomain: 'bounce' })
        const logic = mountWizard()
        await expectLogic(integrationsLogic).toDispatchActions(['loadIntegrationsSuccess'])
        return logic
    }

    it.each([
        ['billing@acme.com', 'billing@mail.acme.com'],
        ['billing@mail.acme.com', 'billing@mail.acme.com'],
    ])('adds %s to a domain that already sends as %s, keeping its bounce subdomain', async (input, address) => {
        const logic = await mountWithExistingSender()

        logic.actions.setCustomDomainInput(input)
        logic.actions.useCustomDomain()
        expect(logic.values.existingSender).toBeNull()
        await expectLogic(logic, () => logic.actions.createSender()).toFinishAllListeners()

        expect(backend.requestsTo('integration_create').at(-1)?.body).toMatchObject({
            config: { email: address, mail_from_subdomain: 'bounce' },
        })
    })

    it.each([
        ['a local stack by default', true, null, 'maildev'],
        ['a local stack set to SES', true, 'ses' as const, 'ses'],
        ['a hosted stack, whatever was picked', false, 'maildev' as const, 'ses'],
    ])('creates the sender through the right provider on %s', async (_name, isDebug, picked, provider) => {
        const logic = mountWizard()
        preflightLogic.actions.loadPreflightSuccess({ is_debug: isDebug } as PreflightStatus)
        if (picked) {
            logic.actions.setLocalProvider(picked)
        }

        logic.actions.setCustomDomainInput('acme.com')
        logic.actions.useCustomDomain()
        await expectLogic(logic, () => logic.actions.createSender()).toFinishAllListeners()

        expect(backend.requestsTo('integration_create').at(-1)?.body).toMatchObject({ config: { provider } })
    })

    it.each([
        [
            'the typed name, address and reply-to',
            'Support team',
            'support',
            'support@acme.com',
            { name: 'Support team', email: 'support@mail.acme.com', reply_to: 'support@acme.com' },
        ],
        [
            'the suggestions when the fields are left blank',
            '  ',
            '',
            ' ',
            { name: 'MockHog', email: 'hello@mail.acme.com' },
        ],
    ])('creates the sender with %s', async (_name, typedName, typedLocalPart, typedReplyTo, config) => {
        const logic = mountWizard()

        logic.actions.setCustomDomainInput('acme.com')
        logic.actions.useCustomDomain()
        logic.actions.setSenderNameInput(typedName)
        logic.actions.setLocalPart(typedLocalPart)
        logic.actions.setReplyTo(typedReplyTo)
        await expectLogic(logic, () => logic.actions.createSender()).toFinishAllListeners()

        const body = backend.requestsTo('integration_create').at(-1)?.body as { config: Record<string, unknown> }
        expect(body.config).toMatchObject(config)
        expect('reply_to' in body.config).toBe('reply_to' in config)
    })

    it('refuses an address that already has a sender', async () => {
        const logic = await mountWithExistingSender()

        logic.actions.setCustomDomainInput('hello@acme.com')
        logic.actions.useCustomDomain()

        expect(logic.values.existingSender?.config.email).toBe('hello@mail.acme.com')
    })
})
