import { createServer } from 'node:net'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { startHonoHarness } from '../integration/harness/hono'

const { warmup } = vi.hoisted(() => ({ warmup: vi.fn() }))

vi.mock('ioredis', () => ({
    default: class {
        async connect(): Promise<void> {}
        async flushdb(): Promise<void> {}
        async quit(): Promise<void> {}
    },
}))

vi.mock('@/hono/app', () => ({
    createApp: () => ({
        app: { fetch: () => new Response('ready') },
        warmup,
    }),
}))

vi.mock('../integration/harness/skill-archive', () => ({
    startSkillArchiveServer: async () => ({ url: 'http://127.0.0.1/skills.zip', stop: async () => {} }),
}))

describe('Hono integration harness', () => {
    afterEach(() => {
        vi.unstubAllEnvs()
        vi.clearAllMocks()
    })

    it.each([false, true])(
        'holds its port throughout warmup and releases it on shutdown (warmup fails: %s)',
        async (fails) => {
            vi.stubEnv('MCP_APPS_BASE_URL', '')
            vi.stubEnv('POSTHOG_API_BASE_URL', '')
            vi.stubEnv('POSTHOG_MCP_SKILLS_URL', '')
            let port = 0
            warmup.mockImplementationOnce(async () => {
                port = Number(new URL(process.env.MCP_APPS_BASE_URL!).port)
                const competitor = createServer()
                const error = await new Promise<NodeJS.ErrnoException | null>((resolve) => {
                    competitor.once('error', resolve)
                    competitor.listen(port, '127.0.0.1', () => competitor.close(() => resolve(null)))
                })
                expect(error?.code).toBe('EADDRINUSE')
                if (fails) {
                    throw new Error('warmup failed')
                }
            })

            const started = startHonoHarness({
                apiBaseUrl: 'http://127.0.0.1:8010',
                apiToken: 'test-token',
                orgId: 'test-org',
                projectId: '1',
            })
            if (fails) {
                await expect(started).rejects.toThrow('warmup failed')
            } else {
                const harness = await started
                try {
                    expect(harness.baseUrl.port).toBe(String(port))
                    expect(await (await fetch(harness.baseUrl)).text()).toBe('ready')
                } finally {
                    await harness.stop()
                }
            }

            const next = createServer()
            try {
                await new Promise<void>((resolve, reject) => {
                    next.once('error', reject)
                    next.listen(port, '127.0.0.1', resolve)
                })
            } finally {
                await new Promise<void>((resolve) => next.close(() => resolve()))
            }
        }
    )
})
