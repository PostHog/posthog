import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { integrationsLogic } from 'lib/integrations/integrationsLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { IntegrationType } from '~/types'

import { SendingDomain } from './sendingDomain'
import { sendingDomainLogic } from './sendingDomainLogic'

const emailSender = (id: number, email: string, verified: boolean): Partial<IntegrationType> => ({
    id,
    kind: 'email',
    display_name: email,
    config: { domain: email.split('@')[1], email, name: 'Acme', verified },
})

const FIRST = emailSender(1, 'hello@first.example.com', true)
const SECOND = emailSender(2, 'hello@second.example.com', true)
const PENDING = emailSender(3, 'hello@pending.example.com', false)
const SLACK: Partial<IntegrationType> = { id: 4, kind: 'slack', display_name: 'Slack', config: {} }

describe('sendingDomainLogic', () => {
    let integrations: Partial<IntegrationType>[]
    let listFails: boolean
    let listed: Promise<void>

    beforeEach(() => {
        integrations = []
        listFails = false
        listed = Promise.resolve()
        useMocks({
            get: {
                '/api/projects/:team_id/integrations/': async () => {
                    await listed
                    return listFails
                        ? [500]
                        : [200, { count: integrations.length, next: null, previous: null, results: integrations }]
                },
            },
        })
    })

    const mount = (defaultIntegrationId: number | null): ReturnType<typeof sendingDomainLogic.build> => {
        initKeaTests(true, {
            ...MOCK_DEFAULT_TEAM,
            workflows_config: {
                ...MOCK_DEFAULT_TEAM.workflows_config,
                default_email_integration_id: defaultIntegrationId,
            },
        })
        const logic = sendingDomainLogic()
        logic.mount()
        return logic
    }

    const settled = async (logic: ReturnType<typeof sendingDomainLogic.build>): Promise<void> => {
        await expectLogic(logic).toFinishAllListeners()
    }

    it.each<[string, Partial<IntegrationType>[], number | null, SendingDomain]>([
        [
            "the project's default sender",
            [FIRST, SECOND, PENDING, SLACK],
            2,
            {
                status: 'verified',
                integrationId: 2,
                domain: 'second.example.com',
                email: 'hello@second.example.com',
                from: 'Acme <hello@second.example.com>',
            },
        ],
        [
            'the first verified sender with no project default',
            [PENDING, FIRST, SECOND],
            null,
            {
                status: 'verified',
                integrationId: 1,
                domain: 'first.example.com',
                email: 'hello@first.example.com',
                from: 'Acme <hello@first.example.com>',
            },
        ],
        [
            'a domain waiting for DNS',
            [SLACK, PENDING],
            null,
            { status: 'pending', integrationId: 3, domain: 'pending.example.com' },
        ],
        ['no domain', [SLACK], null, { status: 'none' }],
    ])('shows %s', async (_case, listedIntegrations, defaultIntegrationId, sendingDomain) => {
        integrations = listedIntegrations
        const logic = mount(defaultIntegrationId)
        await settled(logic)

        expect(logic.values).toMatchObject({ sendingDomain, integrationsFailed: false })
    })

    it('shows a failed load only after it fails, and the sender once "Try again" lists it', async () => {
        integrations = [FIRST]
        listFails = true
        let releaseList = (): void => {}
        listed = new Promise((resolve) => (releaseList = resolve))
        const logic = mount(null)

        expect(logic.values).toMatchObject({ sendingDomain: null, integrationsFailed: false })

        releaseList()
        await settled(logic)

        expect(logic.values).toMatchObject({ sendingDomain: null, integrationsFailed: true })

        listFails = false
        integrationsLogic.actions.loadIntegrations()

        expect(logic.values).toMatchObject({ sendingDomain: null, integrationsFailed: false })

        await settled(logic)

        expect(logic.values).toMatchObject({
            sendingDomain: { status: 'verified', email: 'hello@first.example.com' },
            integrationsFailed: false,
        })
    })
})
