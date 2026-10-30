import { describe, expect, it, vi } from 'vitest'

import { redactCredentials, redactCredentialsInText } from '@/lib/credential-redaction'
import redactFailureLogsHooks from '@/tools/engineeringAnalytics/redactFailureLogsHooks'
import { GENERATED_TOOLS as ENGINEERING_ANALYTICS_TOOLS } from '@/tools/generated/engineering_analytics'
import { GENERATED_TOOLS } from '@/tools/generated/logs'
import redactCredentialsHooks from '@/tools/logs/redactCredentialsHooks'
import type { Context } from '@/tools/types'

// Invented values. None of them is a real credential.
const PERSONAL_KEY = 'phx_INVENTEDpersonalKEY0000000000000000'
const OTHER_SECRET = 'INVENTEDsecret1111'
const GITHUB_TOKEN = 'ghp_INVENTEDgithubTOKEN000000000000000000'

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
            name: 'a private key block in one string',
            input: '{"key":"x","pem":"-----BEGIN RSA PRIVATE KEY-----\\nINVENTEDkeyBODY\\n-----END RSA PRIVATE KEY-----"}',
            expected:
                '{"key":"[REDACTED]","pem":"-----BEGIN RSA PRIVATE KEY-----[REDACTED]-----END RSA PRIVATE KEY-----"}',
        },
        {
            name: 'a GitHub token outside a parameter',
            input: `git clone https://${GITHUB_TOKEN}@github.com/example/repo`,
            expected: 'git clone https://ghp_[REDACTED]@github.com/example/repo',
        },
        {
            name: 'credential command-line flags with a separate value',
            input: `+ mysql --password ${OTHER_SECRET} --user root && deploy --api-key "${OTHER_SECRET}"`,
            expected: '+ mysql --password [REDACTED] --user root && deploy --api-key [REDACTED]',
        },
        {
            name: 'a user and password flag',
            input: `+ curl -u deploy:${OTHER_SECRET} https://example.com --user='ci:${OTHER_SECRET}'`,
            expected: "+ curl -u deploy:[REDACTED] https://example.com --user='ci:[REDACTED]'",
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
            name: 'a Docker user id and a password read from stdin',
            input: 'docker run -u 1000:1000 app && docker login --password-stdin ghcr.io',
            expected: 'docker run -u 1000:1000 app && docker login --password-stdin ghcr.io',
        },
        {
            name: 'safe parameters and a public project token',
            input: '/e?ip=1&ver=1.2&keyword=shoes&monkey=1&api_host=phc_INVENTEDprojectTOKEN00000',
            expected: '/e?ip=1&ver=1.2&keyword=shoes&monkey=1&api_host=phc_INVENTEDprojectTOKEN00000',
        },
    ])('masks $name', ({ input, expected }) => {
        expect(redactCredentialsInText(input)).toBe(expected)
    })

    it('parses an unclosed private key label in linear time', () => {
        // A backtracking header pattern takes tens of seconds on this input, far past the test timeout.
        const input = `-----BEGIN ${'PRIVATE KEY '.repeat(100_000)}`

        expect(redactCredentialsInText(input)).toBe(input)
    })

    it.each([
        { name: 'a dictionary key', input: "assert {'key': 'beta-feature'} == {'key': 'beta-feature-2'}" },
        { name: 'an HTTP status code', input: 'Request failed with status code: 500' },
        { name: 'a Node error code', input: "Error: Cannot find module { code: 'ERR_MODULE_NOT_FOUND' }" },
        { name: 'an npm error code', input: 'npm error code: E404' },
        { name: 'a token count', input: '{"input_tokens": 1200, "session": "warm"}' },
    ])('keeps $name in CI output', ({ input }) => {
        expect(redactFailureLogsHooks.afterResponse({} as Context, {}, input)).toBe(input)
    })

    it.each([
        { input: `+ export DATABASE_PASSWORD=${OTHER_SECRET}`, expected: '+ export DATABASE_PASSWORD=[REDACTED]' },
        { input: `  GITHUB_TOKEN: ${OTHER_SECRET}`, expected: '  GITHUB_TOKEN: [REDACTED]' },
        { input: `/cb?access_token=${OTHER_SECRET}&a=1`, expected: '/cb?access_token=[REDACTED]&a=1' },
        { input: `{"api_key": "${OTHER_SECRET}"}`, expected: '{"api_key": "[REDACTED]"}' },
        { input: `client_secret: ${OTHER_SECRET}`, expected: 'client_secret: [REDACTED]' },
        { input: `private_key: ${OTHER_SECRET}`, expected: 'private_key: [REDACTED]' },
        { input: `AWS_SECRET_ACCESS_KEY: ${OTHER_SECRET}`, expected: 'AWS_SECRET_ACCESS_KEY: [REDACTED]' },
        { input: `X-Hub-Signature: ${OTHER_SECRET}`, expected: 'X-Hub-Signature: [REDACTED]' },
        { input: `?sig=${OTHER_SECRET}&a=1`, expected: '?sig=[REDACTED]&a=1' },
        { input: `sessionid=${OTHER_SECRET}`, expected: 'sessionid=[REDACTED]' },
    ])('masks $expected in CI output', ({ input, expected }) => {
        expect(redactFailureLogsHooks.afterResponse({} as Context, {}, input)).toBe(expected)
    })

    it.each([
        {
            name: 'a header inside an assertion does not mask the lines after it',
            lines: [
                [1, "assert pem.startswith('-----BEGIN PRIVATE KEY-----')"],
                [2, 'FAILED tests/test_pem.py::test_header'],
                [3, '##[error]Process completed with exit code 1.'],
            ],
            expected: [
                "assert pem.startswith('-----BEGIN PRIVATE KEY-----[REDACTED]",
                'FAILED tests/test_pem.py::test_header',
                '##[error]Process completed with exit code 1.',
            ],
        },
        {
            name: 'an omitted gap that hides the footer ends the key',
            lines: [
                [1, '-----BEGIN PRIVATE KEY-----'],
                [2, 'INVENTEDkeyLINEone'],
                [null, '... 30 lines omitted ...'],
                [33, 'FAILED tests/test_deploy.py::test_key'],
            ],
            expected: [
                '-----BEGIN PRIVATE KEY-----',
                '[REDACTED]',
                '... 30 lines omitted ...',
                'FAILED tests/test_deploy.py::test_key',
            ],
        },
        {
            name: 'a byte-truncation marker counts as a gap before a footer',
            lines: [
                [1, 'INVENTEDnotAkey'],
                [2, '... [log truncated] ...'],
                [3, 'INVENTEDshortLINE'],
                [4, '-----END PRIVATE KEY-----'],
            ],
            expected: [
                'INVENTEDnotAkey',
                '... [log truncated] ...',
                '[REDACTED]',
                '[REDACTED]-----END PRIVATE KEY-----',
            ],
        },
        {
            name: 'an escaped header opens the key',
            lines: [
                [1, String.raw`\u002D\u002D\u002D\u002D\u002DBEGIN EC PRIVATE KEY\u002D\u002D\u002D\u002D\u002D`],
                [2, 'INVENTEDshortLINE'],
            ],
            expected: [
                String.raw`\u002D\u002D\u002D\u002D\u002DBEGIN EC PRIVATE KEY\u002D\u002D\u002D\u002D\u002D`,
                '[REDACTED]',
            ],
        },
        {
            name: 'a short last body line next to a long body line',
            lines: [
                [null, '... 9 lines omitted ...'],
                [10, 'Zx8Yw7Vu6Ts5Rq4Po3Nm2Lk1Ji0Hg9Fe8Dc7Ba6Zx8Yw7Vu6Ts5Rq4Po3Nm2Lk1J'],
                [11, 'INVENTEDtail=='],
                [null, '... 2 lines omitted ...'],
                [14, 'Done'],
            ],
            expected: ['... 9 lines omitted ...', '[REDACTED]', '[REDACTED]', '... 2 lines omitted ...', 'Done'],
        },
    ])('$name', ({ lines, expected }) => {
        const response = { jobs: [{ lines: lines.map(([original_line, text]) => ({ original_line, text })) }] }

        const redacted = redactFailureLogsHooks.afterResponse({} as Context, {}, response) as typeof response

        expect(redacted.jobs[0]!.lines.map((line) => line.text)).toEqual(expected)
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

    it.each([
        'engineering-analytics-ci-failure-logs',
        'engineering-analytics-run-failure-logs',
        'engineering-analytics-broken-tests',
    ])('redacts environment values and multiline private keys through the generated %s handler', async (tool) => {
        const line = (original_line: number | null, text: string): Record<string, unknown> => ({
            original_line,
            text,
        })
        const response = {
            logs_available: true,
            jobs: [
                {
                    job_id: 1,
                    lines: [
                        line(10, `  AWS_SECRET_ACCESS_KEY: ${OTHER_SECRET}`),
                        line(11, '  GITHUB_TOKEN: ***'),
                        line(12, `+ export DATABASE_PASSWORD=${OTHER_SECRET}`),
                        line(13, '  NODE_ENV: production'),
                        line(14, '-----BEGIN OPENSSH PRIVATE KEY-----'),
                        line(15, 'INVENTEDkeyLINEone'),
                        line(null, '... 3 lines omitted ...'),
                        line(19, 'INVENTEDkeyLINEtwo-----END OPENSSH PRIVATE KEY-----'),
                        line(20, 'FAILED tests/test_deploy.py::test_key'),
                    ],
                },
                {
                    job_id: 2,
                    lines: [
                        line(1, 'INVENTEDnotAkey'),
                        line(null, '... 40 lines omitted ...'),
                        line(42, 'aB3dE5fG7hJ9kL1mN3pQ5rS7tU9vW1xY3zA5bC7dE9fG1hJ3kL5mN7pQ9rS1tU3v'),
                        line(43, 'short'),
                        line(44, '-----END PRIVATE KEY-----'),
                        line(45, 'sha256 0123456789abcdef0123456789abcdef0123456789abcdef'),
                    ],
                },
                {
                    job_id: 3,
                    lines: [
                        line(null, '... 9 lines omitted ...'),
                        line(10, 'Zx8Yw7Vu6Ts5Rq4Po3Nm2Lk1Ji0Hg9Fe8Dc7Ba6Zx8Yw7Vu6Ts5Rq4Po3Nm2Lk1J'),
                        line(11, '##[error]Process completed with exit code 1.'),
                    ],
                },
            ],
        }
        const context = {
            stateManager: { getProjectId: vi.fn().mockResolvedValue(1) },
            api: { request: vi.fn().mockResolvedValue(response) },
        } as unknown as Context

        expect(await ENGINEERING_ANALYTICS_TOOLS[tool]!().handler(context, {})).toEqual({
            logs_available: true,
            jobs: [
                {
                    job_id: 1,
                    lines: [
                        line(10, '  AWS_SECRET_ACCESS_KEY: [REDACTED]'),
                        line(11, '  GITHUB_TOKEN: [REDACTED]'),
                        line(12, '+ export DATABASE_PASSWORD=[REDACTED]'),
                        line(13, '  NODE_ENV: production'),
                        line(14, '-----BEGIN OPENSSH PRIVATE KEY-----'),
                        line(15, '[REDACTED]'),
                        line(null, '... 3 lines omitted ...'),
                        line(19, '[REDACTED]-----END OPENSSH PRIVATE KEY-----'),
                        line(20, 'FAILED tests/test_deploy.py::test_key'),
                    ],
                },
                {
                    job_id: 2,
                    lines: [
                        line(1, 'INVENTEDnotAkey'),
                        line(null, '... 40 lines omitted ...'),
                        line(42, '[REDACTED]'),
                        line(43, '[REDACTED]'),
                        line(44, '[REDACTED]-----END PRIVATE KEY-----'),
                        line(45, 'sha256 0123456789abcdef0123456789abcdef0123456789abcdef'),
                    ],
                },
                {
                    job_id: 3,
                    lines: [
                        line(null, '... 9 lines omitted ...'),
                        line(10, '[REDACTED]'),
                        line(11, '##[error]Process completed with exit code 1.'),
                    ],
                },
            ],
        })
    })
})
