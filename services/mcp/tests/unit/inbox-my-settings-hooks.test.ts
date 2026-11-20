import { describe, expect, it, vi } from 'vitest'

import { PostHogApiError } from '@/lib/errors'
import { GENERATED_TOOLS } from '@/tools/generated/signals'
import type { Context } from '@/tools/types'

const MY_SETTINGS_PATH = '/api/users/%40me/signal_autonomy/'

function contextWith(request: () => Promise<unknown>): { context: Context; request: ReturnType<typeof vi.fn> } {
    const requestMock = vi.fn(request)
    return { context: { api: { request: requestMock } } as unknown as Context, request: requestMock }
}

function notFound(method: string): PostHogApiError {
    return new PostHogApiError({
        status: 404,
        statusText: 'Not Found',
        body: '',
        url: 'https://app.example.com/api/users/%40me/signal_autonomy/',
        method,
    })
}

describe('inbox my settings tools', () => {
    it.each([
        { tool: 'inbox-my-settings-get', params: { user_id: '42' }, method: 'GET' },
        { tool: 'inbox-my-settings-update', params: { user_id: '42', autostart_priority: 'P1' }, method: 'POST' },
    ])('$tool always targets the authenticated user', async ({ tool, params, method }) => {
        const { context, request } = contextWith(async () => ({ id: 'config-1' }))

        await GENERATED_TOOLS[tool]!().handler(context, params)

        expect(request).toHaveBeenCalledWith(expect.objectContaining({ method, path: MY_SETTINGS_PATH }))
    })

    it('reads a 404 as no overrides', async () => {
        const { context } = contextWith(async () => {
            throw notFound('GET')
        })

        const result = await GENERATED_TOOLS['inbox-my-settings-get']!().handler(context, {})

        expect(result).toEqual({ has_overrides: false, message: expect.stringContaining('project defaults') })
    })

    it('keeps a 404 on update as an error', async () => {
        const { context } = contextWith(async () => {
            throw notFound('POST')
        })

        await expect(
            GENERATED_TOOLS['inbox-my-settings-update']!().handler(context, { autostart_priority: 'P1' })
        ).rejects.toBeInstanceOf(PostHogApiError)
    })
})
