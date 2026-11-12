import { afterEach, describe, expect, it, vi } from 'vitest'
import type { z } from 'zod'

import { ApiClient } from '@/api/client'
import { GENERATED_TOOL_MAP } from '@/tools/generated'
import type { Context } from '@/tools/types'

describe('Generated email template tools', () => {
    afterEach(() => {
        vi.unstubAllGlobals()
    })

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

    it.each([
        [true, 'omitted', {}],
        [false, 'false', { basic: false }],
    ])('workflows-list-email-templates sends basic=%s when the input has it %s', async (sent, _case, input) => {
        const fetch = vi
            .fn()
            .mockResolvedValue(
                new Response(JSON.stringify({ count: 0, next: null, previous: null, results: [] }), { status: 200 })
            )
        vi.stubGlobal('fetch', fetch)
        const context = {
            api: new ApiClient({ apiToken: 'token', baseUrl: 'https://example.com' }),
            stateManager: { getProjectId: async () => '42' },
        } as unknown as Context
        const tool = GENERATED_TOOL_MAP['workflows-list-email-templates']!()

        await tool.handler(context, tool.schema.parse(input))

        const url = new URL(fetch.mock.calls[0]![0] as string)
        expect(url.pathname).toBe('/api/projects/42/messaging_templates/')
        expect(url.searchParams.get('basic')).toBe(String(sent))
    })
})
