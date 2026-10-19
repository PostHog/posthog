import { describe, expect, it } from 'vitest'

import { redactCredentialsInText } from '@/lib/credential-redaction'
import redactCredentialsHooks from '@/tools/logs/redactCredentialsHooks'
import type { Context } from '@/tools/types'

// Invented values. None of them is a real credential.
const PERSONAL_KEY = 'phx_INVENTEDpersonalKEY0000000000000000'
const OTHER_SECRET = 'INVENTEDsecret1111'

describe('credential redaction', () => {
    it.each([
        {
            name: 'a query parameter in a URL',
            input: `GET https://app.example.com/api/flags?personal_api_key=${OTHER_SECRET}&limit=10`,
            expected: 'GET https://app.example.com/api/flags?personal_api_key=[REDACTED]&limit=10',
        },
        {
            name: 'a request URL inside a JSON-encoded body',
            input: `{"request":"https://app.example.com/decide?v=3&access_token=${OTHER_SECRET}","status":200}`,
            expected: '{"request":"https://app.example.com/decide?v=3&access_token=[REDACTED]","status":200}',
        },
        {
            name: 'an escaped JSON string',
            input: `{\\"url\\":\\"/hook?Client_Secret=${OTHER_SECRET}\\"}`,
            expected: '{\\"url\\":\\"/hook?Client_Secret=[REDACTED]\\"}',
        },
        {
            name: 'a percent-encoded nested URL',
            input: `/login?next=https%3A%2F%2Fexample.com%2Fcb%3Fstate%3D1%26token%3D${OTHER_SECRET}%26a%3Db`,
            expected: '/login?next=https%3A%2F%2Fexample.com%2Fcb%3Fstate%3D1%26token%3D[REDACTED]%26a%3Db',
        },
        {
            name: 'a bare form body',
            input: `body: password=${OTHER_SECRET}&user=jo`,
            expected: 'body: password=[REDACTED]&user=jo',
        },
        {
            name: 'a PostHog personal API key outside a parameter',
            input: `Authorization: Bearer ${PERSONAL_KEY}`,
            expected: 'Authorization: Bearer phx_[REDACTED]',
        },
        {
            name: 'safe parameters and a public project token',
            input: '/e?ip=1&ver=1.2&keyword=shoes&monkey=1&api_host=phc_INVENTEDprojectTOKEN00000',
            expected: '/e?ip=1&ver=1.2&keyword=shoes&monkey=1&api_host=phc_INVENTEDprojectTOKEN00000',
        },
    ])('masks $name', ({ input, expected }) => {
        expect(redactCredentialsInText(input)).toBe(expected)
    })

    it('masks credentials in every string of a logs response', async () => {
        const result = {
            results: [
                {
                    uuid: 'log-1',
                    body: JSON.stringify({ url: `https://example.com/api?personal_api_key=${PERSONAL_KEY}` }),
                    attributes: { 'http.url': `/v1?apikey=${OTHER_SECRET}` },
                },
            ],
            entries: [{ pattern: { template: `GET /api?token=${OTHER_SECRET} <*>` } }],
        }

        const redacted = await redactCredentialsHooks.afterResponse({} as Context, {}, result)

        const serialized = JSON.stringify(redacted)
        expect(serialized).not.toContain(PERSONAL_KEY)
        expect(serialized).not.toContain(OTHER_SECRET)
        expect(serialized).toContain('https://example.com/api?personal_api_key=[REDACTED]')
        expect(redacted).toMatchObject({ results: [{ uuid: 'log-1' }] })
    })
})
