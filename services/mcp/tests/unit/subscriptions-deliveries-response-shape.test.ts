import { describe, expect, it, vi } from 'vitest'

import { GENERATED_TOOLS } from '@/tools/generated/subscriptions'
import type { Context } from '@/tools/types'

function createMockContext(requestMock: ReturnType<typeof vi.fn>): Context {
    return {
        api: {
            request: requestMock,
            getProjectBaseUrl: (projectId: string) => `https://us.posthog.com/project/${projectId}`,
        } as any,
        stateManager: { getProjectId: vi.fn().mockResolvedValue('42') } as any,
        env: {} as any,
        sessionManager: {} as any,
        cache: {} as any,
        getDistinctId: async () => 'test-distinct-id',
        trackEvent: async () => {},
    }
}

const aiDelivery = (id: string): Record<string, unknown> => ({
    id,
    status: 'completed',
    trigger_type: 'scheduled',
    created_at: '2026-08-25T00:00:00Z',
    finished_at: '2026-08-25T00:01:00Z',
    ai_report: '# Weekly report\n\nfull markdown body',
    ai_report_prompt: 'Summarize the weekly product usage in detail',
    ai_report_diagnostics: [{ query: 'SELECT 1', error: null }],
    content_snapshot: { insight: 'frozen state' },
    recipient_results: [{ email: 'user@example.com', status: 'sent' }],
    error: null,
})

describe('subscriptions deliveries response shape', () => {
    it('list strips the AI report prompt and report content from every row', async () => {
        const request = vi.fn().mockResolvedValue({
            results: [aiDelivery('d1'), aiDelivery('d2')],
            next: null,
            previous: null,
        })

        const result = await GENERATED_TOOLS['subscriptions-deliveries-list']!().handler(createMockContext(request), {
            subscription_id: 107463,
        })

        for (const row of (result as any).results) {
            // Metadata a history view needs stays present.
            expect(row.id).toBeTruthy()
            expect(row.status).toBe('completed')
            expect(row.trigger_type).toBe('scheduled')
            // Bulky and sensitive fields are excluded to keep list responses small.
            expect(row).not.toHaveProperty('ai_report_prompt')
            expect(row).not.toHaveProperty('ai_report')
            expect(row).not.toHaveProperty('ai_report_diagnostics')
            expect(row).not.toHaveProperty('content_snapshot')
            expect(row).not.toHaveProperty('recipient_results')
            expect(row).not.toHaveProperty('error')
        }
    })

    it('retrieve keeps the AI report and its prompt for a single delivery', async () => {
        const request = vi.fn().mockResolvedValue(aiDelivery('d1'))

        const result = await GENERATED_TOOLS['subscriptions-deliveries-retrieve']!().handler(
            createMockContext(request),
            { subscription_id: 107463, id: 'd1' }
        )

        expect(result).toHaveProperty('ai_report')
        expect(result).toHaveProperty('ai_report_prompt')
        // Diagnostics stay excluded to keep the response focused on the report.
        expect(result).not.toHaveProperty('ai_report_diagnostics')
    })
})
