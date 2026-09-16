import { describe, expect, it } from 'vitest'

import { redactTraceResults } from '@/lib/trace-redaction'

describe('trace redaction', () => {
    // Invented values. Each key stands for one class of withheld field.
    const SECRETS: Record<string, string> = {
        $mcp_auth_method: 'personal_api_key',
        api_key: 'invented-key-value',
        authorization: 'Bearer invented-token-value',
        x_forwarded_for: '198.51.100.7',
        $user_email: 'someone@example.com',
        $geoip_city_name: 'Nowhere',
        granted_scopes: 'insight:write,query:read',
        remaining_budget_usd: '12.50',
    }

    function traceWithProperties(properties: Record<string, unknown>): Record<string, unknown> {
        return { id: 'trace-1', events: [{ id: 'e1', event: '$ai_generation', properties }] }
    }

    it('withholds every property outside the AI namespace and reports it by name', () => {
        const { results } = redactTraceResults([
            traceWithProperties({ $ai_model: 'gpt-4', $ai_input: 'summarize this', ...SECRETS }),
        ]) as any
        const properties = results[0].events[0].properties
        const serialized = JSON.stringify(results)

        for (const [key, value] of Object.entries(SECRETS)) {
            expect(properties).not.toHaveProperty(key)
            expect(serialized).not.toContain(value)
            expect(properties._redactedKeys).toContain(key)
        }
        expect(properties.$ai_model).toBe('gpt-4')
        expect(properties.$ai_input).toBe('summarize this')
    })

    it.each(['$session_id', '$lib', '$lib_version'])('keeps %s, which an agent needs to act on a trace', (key) => {
        const { results } = redactTraceResults([traceWithProperties({ [key]: 'kept' })]) as any

        expect(results[0].events[0].properties[key]).toBe('kept')
    })

    it('adds no marker when a bag holds nothing to withhold', () => {
        const trace = traceWithProperties({ $ai_model: 'gpt-4', $session_id: 's1' })

        expect(redactTraceResults([trace])).toEqual({ results: [trace] })
    })

    it('explains the redaction once for the whole response, not once per trace', () => {
        const traces = Array.from({ length: 50 }, (_, i) => traceWithProperties({ api_key: `invented-${i}` }))
        const { results, notice } = redactTraceResults(traces) as any

        expect(notice.reason).toBeTruthy()
        expect(JSON.stringify(results)).not.toContain(notice.reason)
    })

    it('filters inside $ai_debug_data, which the prefix rule would wave through whole', () => {
        const { results } = redactTraceResults([
            traceWithProperties({
                $ai_debug: true,
                $ai_debug_data: {
                    'user.id': 'someone@example.com',
                    authorization: 'Bearer invented-token-value',
                    // A withheld key drops its whole subtree, however deep the secret sits.
                    'http.request': { headers: { cookie: 'session=invented-cookie-value' } },
                    $ai_model: 'gpt-4',
                },
            }),
        ]) as any
        const debugData = results[0].events[0].properties.$ai_debug_data
        const serialized = JSON.stringify(results)

        expect(serialized).not.toContain('invented-token-value')
        expect(serialized).not.toContain('someone@example.com')
        expect(serialized).not.toContain('invented-cookie-value')
        expect(debugData._redactedKeys).toEqual(['user.id', 'authorization', 'http.request'])
        expect(debugData.$ai_model).toBe('gpt-4')
    })

    it('redacts the person properties a trace carries, not only its events', () => {
        const { results } = redactTraceResults([
            {
                id: 'trace-1',
                person: {
                    uuid: 'p1',
                    distinct_id: 'd1',
                    created_at: 'yesterday',
                    properties: { email: 'someone@example.com' },
                },
            },
        ]) as any

        expect(JSON.stringify(results)).not.toContain('someone@example.com')
        expect(results[0].person).toMatchObject({ uuid: 'p1', distinct_id: 'd1', created_at: 'yesterday' })
        expect(results[0].person.properties._redactedKeys).toEqual(['email'])
    })

    it('redacts every trace of a list response, not just the first', () => {
        const { results } = redactTraceResults([
            traceWithProperties({ api_key: 'invented-key-one' }),
            traceWithProperties({ api_key: 'invented-key-two' }),
        ]) as any

        expect(JSON.stringify(results)).not.toContain('invented-key-one')
        expect(JSON.stringify(results)).not.toContain('invented-key-two')
    })
})
