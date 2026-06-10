import type { AcpMessage } from './acp-types'
import { accumulateSessionResources, deriveContextUsage } from './contextUsage'

function usageUpdateEvent(used: number, size: number, ts = 1, cost?: { amount: number; currency: string }): AcpMessage {
    return {
        type: 'acp_message',
        ts,
        message: {
            jsonrpc: '2.0',
            method: 'session/update',
            params: {
                sessionId: 's1',
                update: { sessionUpdate: 'usage_update', used, size, ...(cost ? { cost } : {}) },
            },
        },
    }
}

function breakdownEvent(breakdown: Record<string, number>, method = '_posthog/usage_update', ts = 1): AcpMessage {
    return {
        type: 'acp_message',
        ts,
        message: { jsonrpc: '2.0', method, params: { sessionId: 's1', breakdown } },
    }
}

function resourcesUsedEvent(
    products: { id: string; label: string }[],
    ts = 1,
    method = '_posthog/resources_used'
): AcpMessage {
    return {
        type: 'acp_message',
        ts,
        message: { jsonrpc: '2.0', method, params: { sessionId: 's1', products } },
    }
}

describe('contextUsage', () => {
    describe('deriveContextUsage', () => {
        it('returns null with no events', () => {
            expect(deriveContextUsage([])).toBeNull()
        })

        it('returns null when no usage_update has arrived', () => {
            const events: AcpMessage[] = [
                {
                    type: 'acp_message',
                    ts: 1,
                    message: { jsonrpc: '2.0', method: '_posthog/turn_complete', params: { stopReason: 'end_turn' } },
                },
            ]
            expect(deriveContextUsage(events)).toBeNull()
        })

        it('derives the aggregate from a session/update usage_update', () => {
            const result = deriveContextUsage([usageUpdateEvent(50_000, 200_000)])
            expect(result).toEqual({
                used: 50_000,
                size: 200_000,
                percentage: 25,
                cost: null,
                breakdown: null,
            })
        })

        it('uses the latest usage_update when several arrived', () => {
            const result = deriveContextUsage([
                usageUpdateEvent(10_000, 200_000, 1),
                usageUpdateEvent(80_000, 200_000, 2),
            ])
            expect(result?.used).toBe(80_000)
            expect(result?.percentage).toBe(40)
        })

        it('merges the breakdown from a _posthog/usage_update notification', () => {
            const result = deriveContextUsage([
                usageUpdateEvent(50_000, 200_000),
                breakdownEvent({
                    systemPrompt: 4000,
                    tools: 500,
                    rules: 0,
                    skills: 0,
                    mcp: 0,
                    subagents: 0,
                    conversation: 45_500,
                }),
            ])
            expect(result?.breakdown?.systemPrompt).toBe(4000)
            expect(result?.breakdown?.conversation).toBe(45_500)
        })

        it('tolerates the double-underscore method prefix from extNotification', () => {
            const result = deriveContextUsage([
                usageUpdateEvent(50_000, 200_000),
                breakdownEvent(
                    {
                        systemPrompt: 4000,
                        tools: 0,
                        rules: 0,
                        skills: 0,
                        mcp: 0,
                        subagents: 0,
                        conversation: 46_000,
                    },
                    '__posthog/usage_update'
                ),
            ])
            expect(result?.breakdown?.systemPrompt).toBe(4000)
        })

        it('caps percentage at 100 when used exceeds size', () => {
            const result = deriveContextUsage([usageUpdateEvent(250_000, 200_000)])
            expect(result?.percentage).toBe(100)
        })

        it('reports 0% for a zero-size context window', () => {
            const result = deriveContextUsage([usageUpdateEvent(0, 0)])
            expect(result?.percentage).toBe(0)
        })

        it('passes the cost through when present', () => {
            const event = usageUpdateEvent(50_000, 200_000, 1, { amount: 1.23, currency: 'USD' })
            expect(deriveContextUsage([event])?.cost).toEqual({ amount: 1.23, currency: 'USD' })
        })
    })

    describe('accumulateSessionResources', () => {
        it('returns [] with no events', () => {
            expect(accumulateSessionResources([])).toEqual([])
        })

        it('collects products across notifications in first-seen order', () => {
            const events: AcpMessage[] = [
                resourcesUsedEvent([{ id: 'feature_flags', label: 'Feature flags' }], 1),
                resourcesUsedEvent([{ id: 'product_analytics', label: 'Product analytics' }], 2),
            ]
            expect(accumulateSessionResources(events)).toEqual([
                { id: 'feature_flags', label: 'Feature flags' },
                { id: 'product_analytics', label: 'Product analytics' },
            ])
        })

        it('de-duplicates a product used across multiple turns', () => {
            const events: AcpMessage[] = [
                resourcesUsedEvent([{ id: 'feature_flags', label: 'Feature flags' }], 1),
                resourcesUsedEvent([{ id: 'experiments', label: 'Experiments' }], 2),
                resourcesUsedEvent([{ id: 'feature_flags', label: 'Feature flags' }], 3),
            ]
            expect(accumulateSessionResources(events)).toEqual([
                { id: 'feature_flags', label: 'Feature flags' },
                { id: 'experiments', label: 'Experiments' },
            ])
        })

        it('accepts the double-underscore method prefix', () => {
            const events: AcpMessage[] = [
                resourcesUsedEvent([{ id: 'sql', label: 'SQL' }], 1, '__posthog/resources_used'),
            ]
            expect(accumulateSessionResources(events)).toEqual([{ id: 'sql', label: 'SQL' }])
        })

        it('ignores unrelated events, empty payloads and missing products', () => {
            const events: AcpMessage[] = [
                {
                    type: 'acp_message',
                    ts: 1,
                    message: { jsonrpc: '2.0', method: '_posthog/turn_complete', params: { stopReason: 'end_turn' } },
                },
                resourcesUsedEvent([], 2),
                {
                    type: 'acp_message',
                    ts: 3,
                    message: { jsonrpc: '2.0', method: '_posthog/resources_used', params: { sessionId: 's1' } },
                },
            ]
            expect(accumulateSessionResources(events)).toEqual([])
        })
    })
})
