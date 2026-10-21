import { describe, expect, it, vi } from 'vitest'

import { redactCredentials, redactCredentialsInText } from '@/lib/credential-redaction'
import { GENERATED_TOOLS } from '@/tools/generated/logs'
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
            expected: 'Authorization: [REDACTED]',
        },
        {
            name: 'the first parameter in a nested URL',
            input: `/login?next=https%3A%2F%2Fexample.com%2Fcb%3Ftoken%3D${OTHER_SECRET}`,
            expected: '/login?next=https%3A%2F%2Fexample.com%2Fcb%3Ftoken%3D[REDACTED]',
        },
        {
            name: 'complete values containing encoded separators and commas',
            input: `/cb?password=INVENTED%26secret,1111&limit=10`,
            expected: '/cb?password=[REDACTED]&limit=10',
        },
        {
            name: 'encoded parameter names',
            input: `/cb?access%5Ftoken=${OTHER_SECRET}&safe=1`,
            expected: '/cb?access%5Ftoken=[REDACTED]&safe=1',
        },
        {
            name: 'multiple nested encoding levels',
            input: `/cb?next=https%253A%252F%252Fexample.com%252F%253Faccess%255Ftoken%253Dsecret%252526suffix%2526safe%253D1`,
            expected:
                '/cb?next=https%253A%252F%252Fexample.com%252F%253Faccess%255Ftoken%253D[REDACTED]%2526safe%253D1',
        },
        {
            name: 'JSON credentials including escaped quotes',
            input: String.raw`{"api_key":"secret\"suffix","safe":"keep","credentials.password":"another secret"}`,
            expected: '{"api_key":"[REDACTED]","safe":"keep","credentials.password":"[REDACTED]"}',
        },
        {
            name: 'JSON credentials inside an escaped JSON string',
            input: JSON.stringify({ body: JSON.stringify({ password: 'secret with spaces', safe: 'keep' }) }),
            expected: JSON.stringify({ body: JSON.stringify({ password: '[REDACTED]', safe: 'keep' }) }),
        },
        {
            name: 'JSON unicode escapes in credential names',
            input: String.raw`{"access\u005ftoken":"secret","safe":true}`,
            expected: String.raw`{"access\u005ftoken":"[REDACTED]","safe":true}`,
        },
        {
            name: 'headers and YAML credential fields',
            input: 'Authorization: Bearer generic-secret\r\nX-Api-Key: key with spaces\nclient_secret: yaml-secret\nsafe: keep',
            expected: 'Authorization: [REDACTED]\r\nX-Api-Key: [REDACTED]\nclient_secret: [REDACTED]\nsafe: keep',
        },
        {
            name: 'a form body inside a JSON string',
            input: '{"body":"password=secret&safe=1"}',
            expected: '{"body":"password=[REDACTED]&safe=1"}',
        },
        {
            name: 'backslashes inside a parameter value',
            input: '/?password=secret\\suffix&safe=1',
            expected: '/?password=[REDACTED]&safe=1',
        },
        {
            name: 'whitespace around a form assignment',
            input: 'password = secret&safe=1',
            expected: 'password = [REDACTED]&safe=1',
        },
        {
            name: 'URL passwords with encoded and literal delimiters',
            input: 'postgres://service:secret%26suffix,more@example.com/db https://user:pass@example.com/path',
            expected: 'postgres://service:[REDACTED]@example.com/db https://user:[REDACTED]@example.com/path',
        },
        {
            name: 'a bearer token outside a header',
            input: 'request failed with Bearer generic-secret',
            expected: 'request failed with Bearer [REDACTED]',
        },
        {
            name: 'a private PostHog token outside a header',
            input: `key supplied: ${PERSONAL_KEY}`,
            expected: 'key supplied: phx_[REDACTED]',
        },
        {
            name: 'credential containers without masking adjacent JSON fields',
            input: '{"credentials":{"password":"secret","nested":["another"]},"safe":"keep"}',
            expected: '{"credentials":[REDACTED],"safe":"keep"}',
        },
        {
            name: 'an existing redaction marker',
            input: 'Authorization: [REDACTED]\n/?password=[REDACTED]&safe=1',
            expected: 'Authorization: [REDACTED]\n/?password=[REDACTED]&safe=1',
        },
        {
            name: 'excessively nested encoding',
            input: Array.from({ length: 10 }).reduce<string>((value) => encodeURIComponent(value), '/?token=secret'),
            expected: '[REDACTED]',
        },
        {
            name: 'unrelated text and encoding',
            input: String.raw`{"message":"keyword=shoes monkey=1","url":"https://example.com/a%2Fb?next=hello%20world&limit=10","safe":"a\"b"}`,
            expected: String.raw`{"message":"keyword=shoes monkey=1","url":"https://example.com/a%2Fb?next=hello%20world&limit=10","safe":"a\"b"}`,
        },
        {
            name: 'safe parameters and a public project token',
            input: '/e?ip=1&ver=1.2&keyword=shoes&monkey=1&api_host=phc_INVENTEDprojectTOKEN00000',
            expected: '/e?ip=1&ver=1.2&keyword=shoes&monkey=1&api_host=phc_INVENTEDprojectTOKEN00000',
        },
    ])('masks $name', ({ input, expected }) => {
        expect(redactCredentialsInText(input)).toBe(expected)
    })

    it('masks structured credential fields without mutating the response', () => {
        const input = { attributes: { authorization: 'Bearer secret', password: ['secret'], safe: 42 }, body: null }

        expect(redactCredentials(input)).toEqual({
            attributes: { authorization: '[REDACTED]', password: '[REDACTED]', safe: 42 },
            body: null,
        })
        expect(input.attributes.authorization).toBe('Bearer secret')
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

        expect(redacted).toEqual({
            results: [
                {
                    uuid: 'log-1',
                    body: '{"url":"https://example.com/api?personal_api_key=[REDACTED]"}',
                    attributes: { 'http.url': '/v1?apikey=[REDACTED]' },
                },
            ],
            entries: [{ pattern: { template: 'GET /api?token=[REDACTED] <*>' } }],
        })
    })

    it.each([
        {
            tool: 'query-logs',
            response: { results: [{ body: 'Authorization: Bearer secret' }] },
            expected: { results: [{ body: 'Authorization: [REDACTED]' }] },
        },
        {
            tool: 'logs-patterns',
            response: { patterns: [{ template: '/?token=secret' }] },
            expected: { patterns: [{ template: '/?token=[REDACTED]' }] },
        },
        {
            tool: 'logs-patterns-diff',
            response: { entries: [{ pattern: { template: 'https://user:secret@example.com/' } }] },
            expected: { entries: [{ pattern: { template: 'https://user:[REDACTED]@example.com/' } }] },
        },
        {
            tool: 'logs-attribute-values-list',
            response: { results: ['/?access%5Ftoken=secret'] },
            expected: { results: ['/?access%5Ftoken=[REDACTED]'] },
        },
        {
            tool: 'logs-facet-values-create',
            response: { results: [{ value: '{"password":"secret"}', count: 2 }] },
            expected: { results: [{ value: '{"password":"[REDACTED]"}', count: 2 }] },
        },
    ])('redacts responses through the generated $tool handler', async ({ tool, response, expected }) => {
        const context = {
            stateManager: { getProjectId: vi.fn().mockResolvedValue(1) },
            api: { request: vi.fn().mockResolvedValue(response) },
        } as unknown as Context

        expect(await GENERATED_TOOLS[tool]!().handler(context, {})).toEqual(expected)
    })
})
