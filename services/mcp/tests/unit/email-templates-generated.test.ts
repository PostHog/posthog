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
    const codeSend = { to: 'jane@example.com', template_key: 'welcome', subject: 'Hi', html: '<p>Hi</p>' }
    const createWithEmail = (email: Record<string, unknown>): Record<string, unknown> => ({
        name: 'Welcome',
        content: { templating: 'liquid', email: { subject: 'Hi', text: 'Hi', design, ...email } },
    })

    it.each([
        ['workflows-send-email', 'a misspelled field', { ...codeSend, capture_engagment: false }],
        ['workflows-send-email', 'a field of a send by template', { ...codeSend, template: { key: 'welcome', hash } }],
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
        expect(toolSchema('workflows-send-email').parse(codeSend)).toEqual(codeSend)
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
