import { describe, expect, it, vi } from 'vitest'

import { GENERATED_TOOLS } from '@/tools/generated/signals'
import type { Context } from '@/tools/types'

describe('edit-report handlers', () => {
    // Both names reach the same endpoint, and scouts call the short one. A flag published on one
    // schema but dropped from the other handler's body is a field the scout can see and cannot use.
    const TOOL_NAMES = ['signals-scout-edit-report', 'scout-edit-report'] as const

    it.each(
        TOOL_NAMES.flatMap((name) =>
            [
                {},
                { corroboration_only: false, supersedes_implementation: false },
                { corroboration_only: true, supersedes_implementation: true },
            ].map((flags) => ({ name, flags }))
        )
    )('$name preserves explicitly supplied flags without inserting omitted flags: $flags', async ({ name, flags }) => {
        const request = vi.fn().mockResolvedValue({ report_id: 'report-1' })
        const context = {
            api: { request, getProjectBaseUrl: vi.fn().mockReturnValue('https://us.posthog.com/project/42') },
            stateManager: { getProjectId: vi.fn().mockResolvedValue('42') },
        } as unknown as Context
        const tool = GENERATED_TOOLS[name]!()
        const input = { run_id: 'run-1', report_id: 'report-1', append_note: 'Checked again', ...flags }
        await tool.handler(context, tool.schema.parse(input))
        expect(request.mock.calls[0]![0].body).toEqual({
            report_id: 'report-1',
            append_note: 'Checked again',
            ...flags,
        })
    })
})
