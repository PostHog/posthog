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

describe('sendingDomain', () => {
    test.each([['Acme'], ['Acme, Inc.'], [`Bob's "Shop"`], ['Shop \\ Outlet'], ['']])(
        'keeps the sender named %p whole when the send API parses it',
        (name) => {
            expect(parsedBySendApi(senderAddress(name, 'hello@example.com'))).toEqual([name, 'hello@example.com'])
        }
    )

    test.each([
        ['the project default among several verified senders', 2, 'hello@second.example.com'],
        ['the first verified sender when the default is not verified', 3, 'hello@first.example.com'],
    ])('sends from %s', (_case, defaultIntegrationId, email) => {
        const integrations = [
            emailSender(1, 'hello@first.example.com', true),
            emailSender(2, 'hello@second.example.com', true),
            emailSender(3, 'hello@pending.example.com', false),
        ]

        expect(sendingDomainOf(integrations, defaultIntegrationId)).toMatchObject({ status: 'verified', email })
    })
})
