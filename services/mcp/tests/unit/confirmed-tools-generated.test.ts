import { createServer } from 'node:http'
import type { AddressInfo } from 'node:net'
import { afterEach, describe, expect, it } from 'vitest'

import { ApiClient } from '@/api/client'
import { PayloadStash, SignedStateCodec } from '@/lib/signed-state'
import { setConfirmedActionRuntime } from '@/tools/confirmed-action-registry'
import type { PrepareConfirmedActionResult } from '@/tools/confirmed-action-runtime'
import { GENERATED_TOOL_MAP } from '@/tools/generated'

import { createTestContext, setActiveProjectAndOrg } from '../shared/test-utils'

function inMemoryRedis(): ConstructorParameters<typeof PayloadStash>[0] {
    const values = new Map<string, string>()
    return {
        set: async (key, value) => {
            values.set(key, value)
            return 'OK'
        },
        get: async (key) => values.get(key) ?? null,
        del: async (...keys) => keys.filter((key) => values.delete(key)).length,
        incrby: async (key, increment) => {
            const next = Number(values.get(key) ?? 0) + increment
            values.set(key, String(next))
            return next
        },
        expire: async () => 1,
        ttl: async () => 60,
    }
}

const confirmedEmail = {
    to: 'jane@example.com',
    template_key: 'welcome',
    subject: 'Hi',
    html: '<p>Hi</p>',
    reply_to: ['support@example.com'],
    scheduled_at: '2026-11-13T09:00:00+02:00',
    capture_engagement: false,
}

const sensitiveEmail = {
    to: 'jane@example.com',
    template_key: 'reset-password',
    subject: 'Reset your password',
    html: '<p>Reset</p>',
    tracking: { opens: true, clicks: true },
    sensitive: true,
}

describe('Generated confirmed tools', () => {
    afterEach(() => setConfirmedActionRuntime(undefined))

    it.each([
        {
            tool: 'workflows-send-email',
            input: confirmedEmail,
            request: { method: 'POST', url: '/api/projects/42/messaging/send/email/', body: confirmedEmail },
        },
        {
            tool: 'workflows-send-email',
            input: sensitiveEmail,
            request: { method: 'POST', url: '/api/projects/42/messaging/send/email/', body: sensitiveEmail },
        },
        {
            tool: 'access-control-default-rule-set',
            input: { resource: 'dashboard', access_level: 'viewer' },
            request: {
                method: 'PUT',
                url: '/api/organizations/org-1/projects/42/access_control_default_rules/',
                body: { resource: 'dashboard', resource_id: null, access_level: 'viewer' },
            },
        },
    ])('$tool sends the request the user confirmed', async ({ tool, input, request }) => {
        const received: { method?: string; url?: string; body: unknown }[] = []
        const posthog = createServer((incoming, response) => {
            let body = ''
            incoming.on('data', (chunk) => (body += chunk))
            incoming.on('end', () => {
                received.push({ method: incoming.method, url: incoming.url, body: JSON.parse(body) })
                response.setHeader('Content-Type', 'application/json')
                response.end(JSON.stringify({ id: 'result-1' }))
            })
        })
        await new Promise<void>((resolve) => posthog.listen(0, '127.0.0.1', resolve))
        try {
            setConfirmedActionRuntime({
                codec: new SignedStateCodec(Buffer.alloc(32, 0x42)),
                stash: new PayloadStash(inMemoryRedis()),
            })
            const baseUrl = `http://127.0.0.1:${(posthog.address() as AddressInfo).port}`
            const context = createTestContext(new ApiClient({ apiToken: 'test-token', baseUrl }))
            await setActiveProjectAndOrg(context, '42', 'org-1')
            const prepareTool = GENERATED_TOOL_MAP[`${tool}-prepare`]!()

            const prepared = (await prepareTool.handler(
                context,
                prepareTool.schema.parse(input)
            )) as PrepareConfirmedActionResult
            const result = await GENERATED_TOOL_MAP[`${tool}-execute`]!().handler(context, {
                confirmation_hash: prepared.confirmation_hash,
                confirmation: 'confirm',
            })

            expect(result).toMatchObject({ id: 'result-1' })
            expect(received).toEqual([request])
        } finally {
            await new Promise((resolve) => posthog.close(resolve))
        }
    })
})
