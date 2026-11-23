import { describe, expect, it, vi } from 'vitest'

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

    it.each(['integrations-email-create', 'integrations-email-partial-update'])(
        '%s sends addresses as given and leaves out the setup method',
        async (name) => {
            const request = vi.fn().mockResolvedValue({ id: 7 })
            const context = {
                api: { request },
                stateManager: { getProjectId: async () => '42' },
            } as unknown as Context
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

            await sender.handler(context, params)

            expect(request.mock.calls[0]![0].body.config).toEqual({
                email: 'sales&ops@mail.example.com',
                name: 'Example',
                reply_to: 'billing=alerts@mail.example.com',
                provider: 'ses',
            })
        }
    )

    it.each(['maildev', 'sandbox'])('rejects the %s provider', (provider) => {
        expect(() =>
            tool.schema.parse({ config: { email: 'hello@mail.example.com', name: 'Example', provider } })
        ).toThrow()
    })
})
