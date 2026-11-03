import { describe, expect, it, vi } from 'vitest'

import { GENERATED_TOOLS } from '@/tools/generated/integrations'
import type { Context } from '@/tools/types'

describe('integrations-email-create', () => {
    const tool = GENERATED_TOOLS['integrations-email-create']!()

    it('creates an ses sender from an email and a name', async () => {
        const request = vi.fn().mockResolvedValue({ id: 7 })
        const context = {
            api: { request },
            stateManager: { getProjectId: async () => '42' },
        } as unknown as Context
        const params = tool.schema.parse({ config: { email: 'hello@mail.example.com', name: 'Example' } })

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
})
