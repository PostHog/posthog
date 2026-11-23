import { createServer } from 'node:http'
import type { AddressInfo } from 'node:net'
import { describe, expect, it, vi } from 'vitest'

import { ApiClient } from '@/api/client'
import { GENERATED_TOOLS } from '@/tools/generated/integrations'
import type { Context } from '@/tools/types'

describe('integrations-email-create', () => {
    const tool = GENERATED_TOOLS['integrations-email-create']!()

    it('creates an ses email sender whatever kind the caller passes', async () => {
        const request = vi.fn().mockResolvedValue({ id: 7 })
        const context = {
            api: { request },
            stateManager: { getProjectId: async () => '42' },
        } as unknown as Context
        const params = tool.schema.parse({
            kind: 'slack',
            config: { email: 'hello@mail.example.com', name: 'Example' },
        })

        await tool.handler(context, params)

        expect(request).toHaveBeenCalledWith(
            expect.objectContaining({
                method: 'POST',
                path: '/api/projects/42/integrations/',
                body: {
                    kind: 'email',
                    config: expect.objectContaining({
                        email: 'hello@mail.example.com',
                        name: 'Example',
                        provider: 'ses',
                    }),
                },
            })
        )
    })

    it.each([
        ['integrations-email-create', 'POST', '/api/projects/42/integrations/'],
        ['integrations-email-partial-update', 'PATCH', '/api/projects/42/integrations/7/email/'],
    ])('%s sends addresses as given and leaves out the setup method', async (name, method, path) => {
        const sender = GENERATED_TOOLS[name]!()
        const params = sender.schema.parse({
            id: 7,
            config: {
                email: 'sales&ops@mail.example.com',
                name: 'Example',
                reply_to: 'billing=alerts@mail.example.com',
                setup_method: 'auto',
            },
        })
        const received: { method: string; path: string; body: any }[] = []
        const server = createServer((request, reply) => {
            let raw = ''
            request.on('data', (chunk) => (raw += chunk))
            request.on('end', () => {
                received.push({
                    method: request.method!,
                    path: new URL(request.url!, 'http://localhost').pathname,
                    body: JSON.parse(raw),
                })
                reply.setHeader('Content-Type', 'application/json')
                reply.end(JSON.stringify({ id: 7 }))
            })
        })
        await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve))
        const context = {
            api: new ApiClient({
                apiToken: 'phx_test',
                baseUrl: `http://127.0.0.1:${(server.address() as AddressInfo).port}`,
            }),
            stateManager: { getProjectId: async () => '42' },
        } as unknown as Context

        try {
            await sender.handler(context, params)
        } finally {
            await new Promise<void>((resolve) => server.close(() => resolve()))
        }

        expect(received).toEqual([
            {
                method,
                path,
                body: expect.objectContaining({
                    config: {
                        email: 'sales&ops@mail.example.com',
                        name: 'Example',
                        reply_to: 'billing=alerts@mail.example.com',
                        provider: 'ses',
                    },
                }),
            },
        ])
    })

    it.each(['maildev', 'sandbox'])('rejects the %s provider', (provider) => {
        expect(() =>
            tool.schema.parse({ config: { email: 'hello@mail.example.com', name: 'Example', provider } })
        ).toThrow()
    })
})
