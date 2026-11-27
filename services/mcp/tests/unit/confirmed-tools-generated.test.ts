import { createServer } from 'node:http'
import type { AddressInfo } from 'node:net'
import { afterEach, describe, expect, it } from 'vitest'

import { ApiClient } from '@/api/client'
import { buildToolResultPayload } from '@/lib/build-tool-result'
import { PayloadStash, SignedStateCodec } from '@/lib/signed-state'
import { setConfirmedActionRuntime } from '@/tools/confirmed-action-registry'
import type { PrepareConfirmedActionResult } from '@/tools/confirmed-action-runtime'
import { GENERATED_TOOL_MAP } from '@/tools/generated'

import { createTestContext, setActiveProjectAndOrg } from '../shared/test-utils'

function inMemoryRedis(entries: Record<string, string> = {}): ConstructorParameters<typeof PayloadStash>[0] {
    const values = new Map<string, string>(Object.entries(entries))
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
    capture_engagement: false,
}

const confirmedTemplateEmail = {
    to: 'jane@example.com',
    template_id: '0190f1d2-3c4b-7a5e-9f00-112233445566',
    message_data: { reset_link: 'https://example.com/reset/abc' },
    distinct_id: 'user-1',
}

const SEND_EMAIL_CONFIRMATION_FROM_OLDER_SCHEMA = {
    hash: 'eyJhbGciOiJIUzI1NiIsInR5cCI6Ik1DUC1TSUdORUQtU1RBVEUifQ.eyJwYXlsb2FkIjp7ImRpZ2VzdCI6ImJmMmNlZTcwODNiMjNiOTQ1YzMwODExMTlmZjE4ZjVhOTU4MWQ1YmNiMzkzYWQ1YmMwNzcyZjZmOWY5YTRhZWQifSwic3ViIjoidGVzdC1kaXN0aW5jdC1pZCIsImF1ZCI6IndvcmtmbG93cy1zZW5kLWVtYWlsQDZkZWQyY2MwOTYyZmQyNDAiLCJpYXQiOjE3MDAwMDAwMDAsImV4cCI6MTcwMDAwMDMwMCwianRpIjoibm9uY2UtZml4ZWQifQ.cymNk3iDfbQPDR-oVP1AOHjZjCRptl473TV6L6ZLuP8',
    stash: {
        'mcp:signed-state:payload:nonce-fixed':
            '{"args":{"to":"jane@example.com","template_key":"welcome","subject":"Hi","html":"<p>Hi</p>"},"scope":{"projectId":"42"}}',
    },
}

describe('Generated confirmed tools', () => {
    afterEach(() => setConfirmedActionRuntime(undefined))

    it.each([
        {
            tool: 'workflows-send-email',
            input: confirmedEmail,
            message:
                /may send it from the PostHog test sender instead, only to members of your organization, and ignore from and reply_to/,
            request: { method: 'POST', url: '/api/projects/42/messaging/send/email/', body: confirmedEmail },
        },
        {
            tool: 'workflows-send-email-template',
            input: confirmedTemplateEmail,
            message: /\S/,
            request: {
                method: 'POST',
                url: '/api/projects/42/messaging/send/email/',
                body: confirmedTemplateEmail,
            },
        },
        {
            tool: 'access-control-default-rule-set',
            input: { resource: 'dashboard', access_level: 'viewer' },
            message: /\S/,
            request: {
                method: 'PUT',
                url: '/api/organizations/org-1/projects/42/access_control_default_rules/',
                body: { resource: 'dashboard', resource_id: null, access_level: 'viewer' },
            },
        },
    ])('$tool shows the user what they confirm and sends that request', async ({ tool, input, message, request }) => {
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
            const shown = buildToolResultPayload({
                handlerResult: prepared,
                toolMeta: prepareTool._meta,
                toolName: prepareTool.name,
                params: input,
            })
                .content.map((part) => part.text)
                .join('')
            expect(prepared.message).toMatch(message)
            expect(shown).toMatch(message)
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

    it('refuses a workflows-send-email confirmation prepared under an older input schema and sends nothing', async () => {
        const received: string[] = []
        const posthog = createServer((incoming, response) => {
            received.push(`${incoming.method} ${incoming.url}`)
            response.setHeader('Content-Type', 'application/json')
            response.end(JSON.stringify({ message_id: 'm-1' }))
        })
        await new Promise<void>((resolve) => posthog.listen(0, '127.0.0.1', resolve))
        try {
            setConfirmedActionRuntime({
                codec: new SignedStateCodec(Buffer.alloc(32, 0x42), { now: () => 1_700_000_000_000 }),
                stash: new PayloadStash(inMemoryRedis(SEND_EMAIL_CONFIRMATION_FROM_OLDER_SCHEMA.stash)),
            })
            const baseUrl = `http://127.0.0.1:${(posthog.address() as AddressInfo).port}`
            const context = createTestContext(new ApiClient({ apiToken: 'test-token', baseUrl }))
            await setActiveProjectAndOrg(context, '42', 'org-1')

            const result = await GENERATED_TOOL_MAP['workflows-send-email-execute']!().handler(context, {
                confirmation_hash: SEND_EMAIL_CONFIRMATION_FROM_OLDER_SCHEMA.hash,
                confirmation: 'confirm',
            })

            expect(result).toMatchObject({
                isError: true,
                content: [{ text: expect.stringContaining('by a different version of this tool') }],
            })
            expect(received).toEqual([])
        } finally {
            await new Promise((resolve) => posthog.close(resolve))
        }
    })
})
