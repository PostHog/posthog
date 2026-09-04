import { describe, expect, it } from 'vitest'

import { GENERATED_TOOLS } from '@/tools/generated/notebooks'
import { NotebooksAddCellSchema } from '@/tools/notebooks/addCell'
import { NotebooksDeleteCellSchema } from '@/tools/notebooks/deleteCell'
import { NotebookEditSchema } from '@/tools/notebooks/edit'
import { NotebooksUpdateCellSchema } from '@/tools/notebooks/updateCell'
import type { ZodObjectAny } from '@/tools/types'

// The notebook tools disagree on what to call the identifier: the CRUD tools take `short_id` and
// the cell tools take `notebook_id`. Production traces show agents carrying one tool's spelling to
// the next and being rejected at the schema, before any request goes out. Each tool therefore
// accepts the others' spellings, and dropping a map brings those rejections back.
describe('notebook identifier contracts', () => {
    const SHORT_ID = 'aBcD1234'

    const parseWith = (schema: ZodObjectAny, input: Record<string, unknown>): Record<string, unknown> => {
        const result = schema.safeParse(input)
        expect(result.success).toBe(true)
        return result.data as Record<string, unknown>
    }

    describe.each([
        ['notebooks-retrieve'],
        ['notebooks-get'],
        ['notebooks-destroy'],
        ['notebooks-partial-update'],
        ['notebooks-list-frames'],
    ])('%s normalizes aliases to `short_id`', (toolName) => {
        const schema = GENERATED_TOOLS[toolName]!().schema

        it.each([
            ['short_id', { short_id: SHORT_ID }],
            ['notebook_id', { notebook_id: SHORT_ID }],
            ['notebookId', { notebookId: SHORT_ID }],
            ['shortId', { shortId: SHORT_ID }],
        ])('accepts %s', (_label, input) => {
            const data = parseWith(schema, input)

            expect(data.short_id).toBe(SHORT_ID)
            expect(data).not.toHaveProperty('notebook_id')
        })

        it('keeps short_id when the caller sends both spellings', () => {
            expect(parseWith(schema, { short_id: SHORT_ID, notebook_id: 'other' }).short_id).toBe(SHORT_ID)
        })
    })

    describe.each([
        ['notebooks-update-cell', NotebooksUpdateCellSchema],
        ['notebooks-delete-cell', NotebooksDeleteCellSchema],
    ])('%s normalizes aliases to `notebook_id`', (_toolName, schema) => {
        it.each([
            ['notebook_id', { notebook_id: SHORT_ID }],
            ['short_id', { short_id: SHORT_ID }],
            ['shortId', { shortId: SHORT_ID }],
        ])('accepts %s', (_label, id) => {
            const data = parseWith(schema, { ...id, node_id: 'cell-1' })

            expect(data.notebook_id).toBe(SHORT_ID)
            expect(data).not.toHaveProperty('short_id')
        })
    })

    it('notebooks-add-cell accepts short_id in place of notebook_id', () => {
        const data = parseWith(NotebooksAddCellSchema, {
            short_id: SHORT_ID,
            cell_type: 'markdown',
            markdown: '# Findings',
        })

        expect(data.notebook_id).toBe(SHORT_ID)
    })

    it('notebook-edit accepts notebook_id in place of short_id', () => {
        const data = parseWith(NotebookEditSchema, {
            notebook_id: SHORT_ID,
            old_markdown: 'before',
            new_markdown: 'after',
        })

        expect(data.short_id).toBe(SHORT_ID)
    })
})
