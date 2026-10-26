import { describe, expect, it } from 'vitest'
import type { z } from 'zod'

import { GENERATED_TOOL_MAP } from '@/tools/generated'

describe('Generated email template tools', () => {
    const toolSchema = (name: string): z.ZodType => GENERATED_TOOL_MAP[name]!().schema
    const hash = `v1:${'a'.repeat(64)}`
    const templateId = '0190a1b2-c3d4-7e5f-8a9b-0c1d2e3f4a5b'
    const design = {
        schemaVersion: 16,
        body: { id: 'body', rows: [], values: {} },
    }
    const upload = { key: 'welcome', name: 'Welcome', subject: 'Hi', html: '<p>Hi</p>' }
    const createWithEmail = (email: Record<string, unknown>): Record<string, unknown> => ({
        name: 'Welcome',
        content: { templating: 'liquid', email: { subject: 'Hi', text: 'Hi', design, ...email } },
    })

    it.each([
        [
            'workflows-send-email',
            'a misspelled template field',
            { to: 'jane@example.com', template: { key: 'welcome', content_hash: hash } },
        ],
        [
            'workflows-send-email',
            'an unknown top-level field',
            { to: 'jane@example.com', template: { key: 'welcome', hash }, tempalte_key: 'welcome' },
        ],
        ['workflows-upload-email-template', 'a misspelled top-level field', { ...upload, if_superseded: true }],
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
    ])('%s refuses an input with %s', (tool, _case, input) => {
        expect(toolSchema(tool).safeParse(input).success).toBe(false)
    })

    it('accepts a send by template key and hash', () => {
        const input = { to: 'jane@example.com', template: { key: 'welcome', hash }, message_data: { name: 'Jane' } }

        expect(toolSchema('workflows-send-email').parse(input)).toEqual({ ...input, capture_engagement: true })
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
})
