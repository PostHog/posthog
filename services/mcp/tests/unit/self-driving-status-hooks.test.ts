import { describe, expect, it, vi } from 'vitest'

import { GENERATED_TOOLS } from '@/tools/generated/signals'
import type { Context } from '@/tools/types'

function contextWith(state: Record<string, unknown>): Context {
    return {
        api: {
            request: vi.fn().mockResolvedValue(state),
            getProjectBaseUrl: vi.fn().mockReturnValue('https://us.example.com/project/7'),
        },
        stateManager: { getProjectId: vi.fn().mockResolvedValue('7') },
    } as unknown as Context
}

async function status(state: Record<string, unknown>): Promise<Record<string, unknown>> {
    return (await GENERATED_TOOLS['self-driving-status-get']!().handler(contextWith(state), {})) as Record<
        string,
        unknown
    >
}

describe('self-driving-status-get', () => {
    it.each([
        [false, false],
        [true, true],
    ])(
        'links an inactive project to activation (GitHub optional: %s)',
        async (githubOptional, mentionsWithoutGithub) => {
            const result = await status({ completed_at: null, draft: null, github_optional_available: githubOptional })

            expect(result).toMatchObject({
                completed_at: null,
                _posthogUrl: 'https://us.example.com/project/7/inbox/activate',
                _agentNote: expect.stringContaining('Self-driving is not active in this project'),
            })
            expect(String(result._agentNote).includes('/inbox/activate/without-github')).toBe(mentionsWithoutGithub)
        }
    )

    it('leaves an active project without activation guidance', async () => {
        const result = await status({ completed_at: '2026-11-01T00:00:00Z', github_optional_available: false })

        expect(result).toEqual({ completed_at: '2026-11-01T00:00:00Z', github_optional_available: false })
    })
})
