import { createServer } from 'node:http'
import type { AddressInfo } from 'node:net'
import { afterEach, describe, expect, it } from 'vitest'
import type { z } from 'zod'

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

describe('Generated email template tools', () => {
    const toolSchema = (name: string): z.ZodType => GENERATED_TOOL_MAP[name]!().schema
    const templateId = '0190a1b2-c3d4-7e5f-8a9b-0c1d2e3f4a5b'
    const design = {
        schemaVersion: 16,
        body: { id: 'body', rows: [], values: {} },
    }
    const codeSend = { to: 'jane@example.com', template_key: 'welcome', subject: 'Hi', html: '<p>Hi</p>' }
    const createWithEmail = (email: Record<string, unknown>): Record<string, unknown> => ({
        name: 'Welcome',
        content: { templating: 'liquid', email: { subject: 'Hi', text: 'Hi', design, ...email } },
    })

    it.each([
        ['workflows-send-email-prepare', 'a misspelled field', { ...codeSend, capture_engagment: false }],
        ['workflows-send-email-prepare', 'a field of a send by template', { ...codeSend, template_id: templateId }],
        [
            'workflows-make-email-template-transactional-prepare',
            'an unknown top-level field',
            { id: templateId, from_integration: 1 },
        ],
        [
            'workflows-update-email-template',
            'a read-only field',
            { id: templateId, name: 'Welcome', created_at: '2026-01-01T00:00:00Z' },
        ],
        [
            'workflows-create-email-template',
            'a misspelled field in content.email',
            createWithEmail({ preview_text: 'Hi' }),
        ],
        [
            'workflows-patch-email-template',
            'a misspelled operation field',
            { id: templateId, operations: [{ op: 'move_content', id: 'block', column_id: 'column', indx: 0 }] },
        ],
        [
            'workflows-patch-email-template',
            'an unknown top-level field',
            { id: templateId, operations: [{ op: 'remove_content', id: 'block' }], dry_run: true },
        ],
    ])('%s refuses an input with %s', (tool, _case, input) => {
        expect(toolSchema(tool).safeParse(input).success).toBe(false)
    })

    it('accepts a send of the email your code rendered', () => {
        expect(toolSchema('workflows-send-email-prepare').parse(codeSend)).toEqual(codeSend)
    })

    it('keeps keys the design format adds at its top level and in its body', () => {
        const editorDesign = {
            ...design,
            idCounter: 3,
            body: { ...design.body, footers: [], customKey: { nested: true } },
        }
        const input = createWithEmail({ design: editorDesign })

        expect(toolSchema('workflows-create-email-template').parse(input)).toMatchObject(input)
    })

    describe('a confirmed send', () => {
        afterEach(() => setConfirmedActionRuntime(undefined))

        it('sends the email the user confirmed', async () => {
            const received: { method?: string; url?: string; body: unknown }[] = []
            const posthog = createServer((request, response) => {
                let body = ''
                request.on('data', (chunk) => (body += chunk))
                request.on('end', () => {
                    received.push({ method: request.method, url: request.url, body: JSON.parse(body) })
                    response.setHeader('Content-Type', 'application/json')
                    response.end(JSON.stringify({ id: 'send-1', status: 'queued' }))
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
                const confirmed = { ...codeSend, reply_to: ['support@example.com'], capture_engagement: false }

                const prepared = (await GENERATED_TOOL_MAP['workflows-send-email-prepare']!().handler(
                    context,
                    confirmed
                )) as PrepareConfirmedActionResult
                const sent = await GENERATED_TOOL_MAP['workflows-send-email-execute']!().handler(context, {
                    confirmation_hash: prepared.confirmation_hash,
                    confirmation: 'confirm',
                })

                expect(sent).toMatchObject({ id: 'send-1', status: 'queued' })
                expect(received).toEqual([
                    { method: 'POST', url: '/api/projects/42/messaging/send/email/', body: confirmed },
                ])
            } finally {
                await new Promise((resolve) => posthog.close(resolve))
            }
        })
    })
})
