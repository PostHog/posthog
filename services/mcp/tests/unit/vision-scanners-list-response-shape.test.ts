import { describe, expect, it, vi } from 'vitest'

import { GENERATED_TOOLS } from '@/tools/generated/replay_vision'
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

const scannerWithLargeTargeting = (): Record<string, unknown> => ({
    id: '0190a000-0000-7000-8000-000000000001',
    name: 'Checkout friction',
    description: 'Watches checkout sessions',
    scanner_type: 'monitor',
    prompt_question: 'Did the user struggle to pay?',
    tags: ['checkout'],
    enabled: true,
    sampling_rate: 0.5,
    last_swept_at: '2026-10-01T00:00:00Z',
    credits_this_month: 12,
    goal: 'Find people who cannot pay',
    scanner_config: { prompt: 'Look for payment friction. '.repeat(500) },
    query: {
        kind: 'RecordingsQuery',
        properties: [
            {
                key: 'account_id',
                type: 'person',
                operator: 'exact',
                value: Array.from({ length: 2000 }, (_, i) => `account-${i}`),
            },
        ],
    },
    created_by: { id: 7, email: 'someone@example.com', first_name: 'Some', last_name: 'One', uuid: 'abc' },
})

describe('vision-scanners-list response shape', () => {
    it('keeps scanner metadata and drops the prompt and recording filters', async () => {
        const request = vi.fn().mockResolvedValue({ results: [scannerWithLargeTargeting()], next: null, count: 1 })

        const result = await GENERATED_TOOLS['vision-scanners-list']!().handler(createMockContext(request), {})

        const row = (result as any).results[0]
        // pickResponseFields drops an unmatched path with no error, so a typo in the yaml include
        // list would silently remove a field the replay skills tell agents to show.
        expect(row).toMatchObject({
            id: '0190a000-0000-7000-8000-000000000001',
            name: 'Checkout friction',
            scanner_type: 'monitor',
            prompt_question: 'Did the user struggle to pay?',
            enabled: true,
            sampling_rate: 0.5,
            last_swept_at: '2026-10-01T00:00:00Z',
            credits_this_month: 12,
            created_by: { id: 7, email: 'someone@example.com' },
        })
        expect(row).not.toHaveProperty('scanner_config')
        expect(row).not.toHaveProperty('query')
        expect(row).not.toHaveProperty('goal')
        expect(JSON.stringify(result).length).toBeLessThan(2000)
    })
})
