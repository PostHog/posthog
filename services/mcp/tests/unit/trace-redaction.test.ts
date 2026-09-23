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
    personSet: 'INVENTEDPERSONSET7777',
}

function traceWithSecrets(): Record<string, unknown> {
    return {
        id: 'trace-1',
        totalCost: 0.42,
        inputState: { messages: [{ role: 'user', content: 'Why did checkout drop?' }] },
        person: {
            uuid: 'person-1',
            distinct_id: 'distinct-1',
            properties: {
                email: SECRETS.identity,
                $geoip_city_name: SECRETS.location,
                // Names the event allowlist retains. A person bag is written
                // with `$set`, so these hold whatever the application chose.
                $ai_model: SECRETS.personSet,
                $session_id: SECRETS.personSet,
            },
        },
        events: [
            {
                id: 'e1',
                event: '$ai_generation',
                createdAt: '2026-09-02T11:30:23Z',
                properties: {
                    $ai_generation_id: 'generation-1',
                    $ai_model: 'gpt-4',
                    $ai_total_cost_usd: 0.42,
                    $ai_cache_read_cost_usd: 0.01,
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
        // The gateway writes this one and `taxonomy.py` does not describe it, so
        // the generated allowlist alone would withhold part of the trace's spend.
        expect(properties.$ai_cache_read_cost_usd).toBe(0.01)
        expect(properties.$ai_input).toEqual([{ role: 'user', content: 'Why did checkout drop?' }])
        expect(properties.$ai_output_choices).toEqual([{ role: 'assistant', content: 'Payments timed out.' }])
        expect(properties.$session_id).toBe('session-1')
    })

    it('withholds every non-AI property value and reports its name instead', () => {
        const event = (redactTrace(traceWithSecrets()) as any).events[0]

        expect(secretsIn(event)).toEqual([])
        expect(event._redactedKeys).toEqual([
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

    it('withholds every person property, including names the event allowlist keeps', () => {
        const person = (redactTrace(traceWithSecrets()) as any).person

        expect(person.uuid).toBe('person-1')
        expect(person.distinct_id).toBe('distinct-1')
        expect(secretsIn(person)).toEqual([])
        expect(person.properties).toEqual({})
        expect(person._redactedKeys).toEqual(['email', '$geoip_city_name', '$ai_model', '$session_id'])
    })

    it.each([
        ['a custom property in the $ai_ namespace', '$ai_authorization'],
        ['a property named like a taxonomy property', '$ai_model_secret'],
    ])('withholds %s, which the namespace does not reserve', (_label, key) => {
        const trace = { id: 't1', events: [{ id: 'e1', properties: { [key]: SECRETS.credential } }] }

        const event = (redactTrace(trace) as any).events[0]

        expect(secretsIn(event)).toEqual([])
        expect(event._redactedKeys).toEqual([key])
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

    it('withholds a URL property that is not a string, having no query string to cut', () => {
        const value = { url: `https://api.example.com/v1?api_key=${SECRETS.credential}` }
        const trace = { id: 't1', events: [{ id: 'e1', properties: { $ai_request_url: value } }] }

        const event = (redactTrace(trace) as any).events[0]

        expect(secretsIn(event)).toEqual([])
        expect(event._redactedKeys).toEqual(['$ai_request_url'])
    })

    it('returns a bag that holds only retained properties unchanged', () => {
        const trace = { id: 't1', events: [{ id: 'e1', properties: { $ai_model: 'gpt-4' } }] }

        expect(redactTrace(trace)).toEqual(trace)
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

    it.each(['full', 'summary'] as const)('keeps the generation identifier at %s detail', (detail) => {
        const [trace] = compactTraceResults(redactTraceResults([traceWithSecrets()]), detail) as any[]

        expect(trace.events[0].properties.$ai_generation_id).toBe('generation-1')
    })
})
