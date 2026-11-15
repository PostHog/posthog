import { execFileSync } from 'child_process'

import { senderAddress } from './sendingDomain'

const parsedBySendApi = (address: string): [string, string] =>
    JSON.parse(
        execFileSync('python3', [
            '-I',
            '-c',
            'import json, sys; from email.utils import parseaddr; print(json.dumps(parseaddr(sys.argv[1])))',
            address,
        ]).toString()
    )

describe('senderAddress', () => {
    test.each([['Acme'], ['Acme, Inc.'], [`Bob's "Shop"`], ['Shop \\ Outlet'], ['']])(
        'keeps the sender named %p whole when the send API parses it',
        (name) => {
            expect(parsedBySendApi(senderAddress(name, 'hello@example.com'))).toEqual([name, 'hello@example.com'])
        }
    )
})
