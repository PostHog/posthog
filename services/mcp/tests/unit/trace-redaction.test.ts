import { describe, expect, it } from 'vitest'

import { redactTraceResults } from '@/lib/trace-redaction'

describe('trace redaction', () => {
    // Invented values. Each key stands for one class of withheld field.
    const SECRETS: Record<string, string> = {
        $mcp_auth_method: 'personal_api_key',
        api_key: 'invented-key-value',
        authorization: 'Bearer invented-token-value',
        $user_email: 'someone@example.com',
        $ip: '198.51.100.7',
        $geoip_city_name: 'Nowhere',
        granted_scopes: 'insight:write,query:read',
        remaining_budget_usd: '12.50',
    }

    function traceWithProperties(properties: Record<string, unknown>): Record<string, unknown> {
        return { id: 'trace-1', events: [{ id: 'e1', event: '$ai_generation', properties }] }
    }

    it('withholds every property outside the AI namespace and reports it by name', () => {
        const result = redactTraceResults([
            traceWithProperties({ $ai_model: 'gpt-4', $ai_input: 'summarize this', ...SECRETS }),
        ]) as any
        const properties = result[0].events[0].properties
        const serialized = JSON.stringify(result)

        for (const [key, value] of Object.entries(SECRETS)) {
            expect(properties).not.toHaveProperty(key)
            expect(serialized).not.toContain(value)
            expect(properties._redactedKeys).toContain(key)
        }
        expect(properties.$ai_model).toBe('gpt-4')
        expect(properties.$ai_input).toBe('summarize this')
    })

    it.each(['$session_id', '$lib', '$lib_version'])('keeps %s, which an agent needs to act on a trace', (key) => {
        const result = redactTraceResults([traceWithProperties({ [key]: 'kept' })]) as any

        expect(result[0].events[0].properties[key]).toBe('kept')
    })

    it('adds no marker when a bag holds nothing to withhold', () => {
        const trace = traceWithProperties({ $ai_model: 'gpt-4', $session_id: 's1' })

        expect(redactTraceResults([trace])).toEqual([trace])
    })

    it('explains the redaction once per trace, not once per event bag', () => {
        const events = Array.from({ length: 50 }, (_, i) => ({ id: `e${i}`, properties: { api_key: 'invented' } }))
        const result = redactTraceResults([{ id: 'trace-1', events }]) as any

        expect(result[0]._redacted.reason).toBeTruthy()
        expect(JSON.stringify(result).split(result[0]._redacted.reason).length - 1).toBe(1)
    })

    it('redacts the person properties a trace carries, not only its events', () => {
        const result = redactTraceResults([
            { id: 'trace-1', person: { uuid: 'p1', distinct_id: 'd1', properties: { email: 'someone@example.com' } } },
        ]) as any

        expect(JSON.stringify(result)).not.toContain('someone@example.com')
        expect(result[0].person.uuid).toBe('p1')
        expect(result[0].person.properties._redactedKeys).toEqual(['email'])
    })

    it('redacts every trace of a list response, not just the first', () => {
        const results = redactTraceResults([
            traceWithProperties({ api_key: 'invented-key-one' }),
            traceWithProperties({ api_key: 'invented-key-two' }),
        ]) as any

        expect(JSON.stringify(results)).not.toContain('invented-key-one')
        expect(JSON.stringify(results)).not.toContain('invented-key-two')
    })
})
