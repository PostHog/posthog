import { describe, expect, it } from 'vitest'

import { compactTraceResults } from '@/lib/trace-compaction'
import { redactTrace, redactTraceResults } from '@/lib/trace-redaction'

// Invented values, one per property class the redactor must withhold. Each one
// is a distinctive string, so a test can assert it appears nowhere in the
// serialized response rather than checking one key at a time.
const SECRETS = {
    credential: 'sk-test-INVENTEDCREDENTIAL0000',
    authState: 'INVENTEDAUTHSTATE1111',
    header: 'INVENTEDCOOKIEHEADER2222',
    identity: 'invented-person@example.com',
    location: 'INVENTEDCITY3333',
    permissions: 'INVENTEDPERMISSION4444',
    budget: 'INVENTEDBUDGET5555',
    custom: 'INVENTEDCUSTOM6666',
}

function traceWithSecrets(): Record<string, unknown> {
    return {
        id: 'trace-1',
        totalCost: 0.42,
        inputState: { messages: [{ role: 'user', content: 'Why did checkout drop?' }] },
        person: {
            uuid: 'person-1',
            distinct_id: 'distinct-1',
            properties: { email: SECRETS.identity, $geoip_city_name: SECRETS.location },
        },
        events: [
            {
                id: 'e1',
                event: '$ai_generation',
                createdAt: '2026-09-02T11:30:23Z',
                properties: {
                    $ai_model: 'gpt-4',
                    $ai_total_cost_usd: 0.42,
                    $ai_input: [{ role: 'user', content: 'Why did checkout drop?' }],
                    $ai_output_choices: [{ role: 'assistant', content: 'Payments timed out.' }],
                    $session_id: 'session-1',
                    api_key: SECRETS.credential,
                    auth: { method: 'oauth', token: SECRETS.authState },
                    request_headers: { cookie: SECRETS.header },
                    user_email: SECRETS.identity,
                    $geoip_city_name: SECRETS.location,
                    permissions: [SECRETS.permissions],
                    budget_remaining_usd: SECRETS.budget,
                    prompt_version: SECRETS.custom,
                    $ai_debug_data: { headers: { authorization: SECRETS.header } },
                },
            },
        ],
    }
}

function secretsIn(value: unknown): string[] {
    const serialized = JSON.stringify(value)
    return Object.entries(SECRETS)
        .filter(([, secret]) => serialized.includes(secret))
        .map(([name]) => name)
}

describe('trace redaction', () => {
    it('keeps the AI payload of an event', () => {
        const properties = (redactTrace(traceWithSecrets()) as any).events[0].properties

        expect(properties.$ai_model).toBe('gpt-4')
        expect(properties.$ai_total_cost_usd).toBe(0.42)
        expect(properties.$ai_input).toEqual([{ role: 'user', content: 'Why did checkout drop?' }])
        expect(properties.$ai_output_choices).toEqual([{ role: 'assistant', content: 'Payments timed out.' }])
        expect(properties.$session_id).toBe('session-1')
    })

    it('withholds every non-AI property value and reports its name instead', () => {
        const properties = (redactTrace(traceWithSecrets()) as any).events[0].properties

        expect(secretsIn(properties)).toEqual([])
        expect(properties._redactedKeys).toEqual([
            'api_key',
            'auth',
            'request_headers',
            'user_email',
            '$geoip_city_name',
            'permissions',
            'budget_remaining_usd',
            'prompt_version',
            '$ai_debug_data',
        ])
    })

    it('withholds person properties while keeping the person navigable', () => {
        const person = (redactTrace(traceWithSecrets()) as any).person

        expect(person.uuid).toBe('person-1')
        expect(person.distinct_id).toBe('distinct-1')
        expect(secretsIn(person)).toEqual([])
        expect(person.properties._redactedKeys).toEqual(['email', '$geoip_city_name'])
    })

    it.each([
        ['a custom property in the $ai_ namespace', '$ai_authorization'],
        ['a property named like a taxonomy property', '$ai_model_secret'],
    ])('withholds %s, which the namespace does not reserve', (_label, key) => {
        const trace = { id: 't1', events: [{ id: 'e1', properties: { [key]: SECRETS.credential } }] }

        const properties = (redactTrace(trace) as any).events[0].properties

        expect(secretsIn(properties)).toEqual([])
        expect(properties._redactedKeys).toEqual([key])
    })

    it.each([
        ['$ai_base_url', 'https://api.example.com/v1?api_key=sk-test-INVENTEDCREDENTIAL0000'],
        ['$ai_request_url', 'https://api.example.com/v1/messages#api_key=sk-test-INVENTEDCREDENTIAL0000'],
    ])('strips the query string from %s, where a key is often passed', (key, url) => {
        const trace = { id: 't1', events: [{ id: 'e1', properties: { [key]: url } }] }

        const properties = (redactTrace(trace) as any).events[0].properties

        expect(secretsIn(properties)).toEqual([])
        expect(properties[key]).toContain('https://api.example.com/v1')
    })

    it('leaves a trace without a properties bag alone', () => {
        expect(redactTraceResults([{ id: 't1' }, 'not-a-trace'])).toEqual([{ id: 't1' }, 'not-a-trace'])
        expect(redactTraceResults(null)).toBeNull()
    })
})

describe('trace redaction through the response pipeline', () => {
    it.each(['full', 'summary'] as const)('withholds every secret at %s detail, for one trace and a list', (detail) => {
        const single = compactTraceResults(redactTraceResults([traceWithSecrets()]), detail)
        const list = compactTraceResults(
            redactTraceResults([traceWithSecrets(), { ...traceWithSecrets(), id: 'trace-2' }]),
            detail
        )

        expect(secretsIn(single)).toEqual([])
        expect(secretsIn(list)).toEqual([])
    })
})
