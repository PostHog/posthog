import { describe, expect, it, vi } from 'vitest'

import { GENERATED_TOOLS } from '@/tools/generated/integrations'
import type { Context } from '@/tools/types'

describe('integrations-domain-connect-apply-url-create', () => {
    it('only builds URLs for email senders', async () => {
        const request = vi.fn().mockResolvedValue({ url: 'https://dns.example.com/apply' })
        const context = {
            api: { request },
            stateManager: { getProjectId: async () => '42' },
        } as unknown as Context
        const tool = GENERATED_TOOLS['integrations-domain-connect-apply-url-create']!()
        const params = tool.schema.parse({
            context: 'proxy',
            integration_id: 7,
            proxy_record_id: '00000000-0000-4000-8000-000000000001',
        })

        await tool.handler(context, params)

        expect(request).toHaveBeenCalledWith(expect.objectContaining({ body: { context: 'email', integration_id: 7 } }))
    })
})
