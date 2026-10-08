import { describe, expect, it, vi } from 'vitest'

import { GENERATED_TOOLS } from '@/tools/generated/signals'
import type { Context } from '@/tools/types'

describe('signals-scout-edit-report handler', () => {
    it.each([
        {},
        { corroboration_only: false, supersedes_implementation: false },
        { corroboration_only: true, supersedes_implementation: true },
    ])('preserves explicitly supplied flags without inserting omitted flags: %j', async (flags) => {
        const request = vi.fn().mockResolvedValue({ report_id: 'report-1' })
        const context = {
            api: { request, getProjectBaseUrl: vi.fn().mockReturnValue('https://us.posthog.com/project/42') },
            stateManager: { getProjectId: vi.fn().mockResolvedValue('42') },
        } as unknown as Context
        const tool = GENERATED_TOOLS['signals-scout-edit-report']!()
        const input = { run_id: 'run-1', report_id: 'report-1', append_note: 'Checked again', ...flags }
        await tool.handler(context, tool.schema.parse(input))
        expect(request.mock.calls[0]![0].body).toEqual({
            report_id: 'report-1',
            append_note: 'Checked again',
            ...flags,
        })
    })
})
