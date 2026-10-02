import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { FakeEmailDomainBackend } from './__mocks__/fakeEmailDomainBackend'
import { emailDomainWizardLogic } from './emailDomainWizardLogic'

describe('emailDomainWizardLogic', () => {
    beforeEach(() => {
        useMocks(new FakeEmailDomainBackend().mocks())
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
})
