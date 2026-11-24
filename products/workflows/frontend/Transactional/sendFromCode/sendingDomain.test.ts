import { execFileSync } from 'child_process'

import { IntegrationType } from '~/types'

import { senderAddress, sendingDomainOf } from './sendingDomain'

const parsedBySendApi = (address: string): [string, string] =>
    JSON.parse(
        execFileSync('python3', [
            '-I',
            '-c',
            'import json, sys; from email.utils import parseaddr; print(json.dumps(parseaddr(sys.argv[1])))',
            address,
        ]).toString()
    )

const emailSender = (id: number, email: string, verified: boolean): IntegrationType =>
    ({
        id,
        kind: 'email',
        display_name: email,
        config: { domain: email.split('@')[1], email, name: 'Acme', verified },
    }) as IntegrationType

const stoppedSender = (id: number, email: string): IntegrationType => {
    const sender = emailSender(id, email, true)
    return { ...sender, config: { ...sender.config, ses_sending_status: 'failed' } }
}

describe('sendingDomain', () => {
    test.each([['Acme'], ['Acme, Inc.'], [`Bob's "Shop"`], ['Shop \\ Outlet'], ['']])(
        'keeps the sender named %p whole when the send API parses it',
        (name) => {
            expect(parsedBySendApi(senderAddress(name, 'hello@example.com'))).toEqual([name, 'hello@example.com'])
        }
    )

    test.each([
        ['the project default among several verified senders', 2, 'hello@second.example.com'],
        ['the first sender that can send when the default is not verified', 3, 'hello@first.example.com'],
        ['the first sender that can send when the default stopped sending', 4, 'hello@first.example.com'],
    ])('sends from %s', (_case, defaultIntegrationId, email) => {
        const integrations = [
            stoppedSender(4, 'hello@stopped.example.com'),
            emailSender(1, 'hello@first.example.com', true),
            emailSender(2, 'hello@second.example.com', true),
            emailSender(3, 'hello@pending.example.com', false),
        ]

        expect(sendingDomainOf(integrations, defaultIntegrationId)).toMatchObject({ status: 'verified', email })
    })

    it('sends from the project default when every verified sender stopped sending', () => {
        const integrations = [
            stoppedSender(1, 'hello@first.example.com'),
            stoppedSender(2, 'hello@default.example.com'),
        ]

        expect(sendingDomainOf(integrations, 2)).toMatchObject({
            status: 'verified',
            email: 'hello@default.example.com',
        })
    })
})
