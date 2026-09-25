import { describe, expect, it } from 'vitest'

import { redactCredentials, redactCredentialsInText } from '@/lib/credential-redaction'

// Invented credentials. The shapes are the providers' own, the values are not.
const MASKED_OPENAI_ECHO =
    'Incorrect API key provided: sk-pr**********************************************2f4B. You can find your API key at https://platform.openai.com/account/api-keys.'

describe('credential redaction', () => {
    it.each([
        // A provider masks the middle of the key it rejects, so the readable
        // prefix and tail are what a name-based rule leaves behind.
        ['masked provider echo', MASKED_OPENAI_ECHO, ['sk-pr', '2f4B']],
        ['elided middle', 'invalid key sk-ant-api03-Wm4x...8vQz for this workspace', ['sk-ant', '8vQz']],
        ['unmasked key', 'AuthenticationError: api key AIzaKq7Rn2Ld8Vt4Xb9Zc6Mw1Ps3Jh5Gf0Dy is revoked', ['AIzaKq7']],
        ['forwarded header', "request failed, headers={'authorization': 'Bearer Hn4Kq7Rn2Ld8Vt4Xb9Zc'}", ['Hn4Kq7']],
        ['labeled value', 'upstream rejected api_key=Qp8Zx3Vn7Bm2Kd6Ls1Ty', ['Qp8Zx3']],
        ['quoted json label', '{"error":{"message":"bad request","x-api-key":"Rt5Wq9Jn3Fv7Bz2Mh8Kd"}}', ['Rt5Wq9']],
        ['github token in a trace url', 'clone failed: ghp_Zv6Nq2Rt8Lm4Xd9Kb3Wc7Ps1Jh5Gf0Dy', ['ghp_Zv6']],
        [
            'private key block',
            'config error: -----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEAxK\n-----END RSA PRIVATE KEY-----',
            ['MIIEowIBAAKCAQEAxK', 'BEGIN RSA PRIVATE KEY'],
        ],
    ])('removes every readable part of a %s', (_name, text, fragments) => {
        const redacted = redactCredentialsInText(text)

        for (const fragment of fragments) {
            expect(redacted).not.toContain(fragment)
        }
        expect(redacted).toContain('[redacted]')
    })

    it.each([
        ['status and request id', 'Request req_7d21f4 failed with status 429: rate limit reached for gpt-4o-mini'],
        ['normalized error', 'Request <ID> failed with status <N>'],
        ['organization in a quota message', 'You exceeded your current quota for organization org-4Kq7Rn2Ld8'],
        ['tool failure', 'Tool call get_weather failed: connection reset by peer'],
    ])('keeps a %s intact', (_name, text) => {
        expect(redactCredentialsInText(text)).toBe(text)
    })

    it('withholds a credential held under a key rather than in a sentence', () => {
        const error = {
            message: 'authentication failed',
            request: { headers: { 'X-Api-Key': 'Qp8Zx3Vn7Bm2Kd6Ls1Ty', cookie: 'session=Rt5Wq9Jn3Fv7Bz2Mh8Kd' } },
            attempts: [{ token: 'Hn4Kq7Rn2Ld8Vt4Xb9Zc' }],
            status: 401,
        }

        const redacted = redactCredentials(error) as any

        expect(JSON.stringify(redacted)).not.toMatch(/Qp8Zx3|Rt5Wq9|Hn4Kq7/)
        expect(redacted.message).toBe('authentication failed')
        expect(redacted.status).toBe(401)
    })
})
