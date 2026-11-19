import { describe, expect, it, vi } from 'vitest'

import { GENERATED_TOOLS } from '@/tools/generated/signals'
import type { Context } from '@/tools/types'

describe('signals-scout-edit-report handler', () => {
    const toolNames = ['scout-edit-report', 'signals-scout-edit-report'] as const
    const ordinaryEdits = [
        { append_note: 'Checked again' },
        { append_evidence: [{ description: 'A second signal supports this finding.', source_id: 'observation-2' }] },
        {
            actionability: 'requires_human_input' as const,
            actionability_explanation: 'A project member must confirm the desired behavior.',
        },
    ]

    it.each(toolNames.flatMap((toolName) => ordinaryEdits.map((edit) => ({ toolName, edit }))))(
        '$toolName forwards an ordinary edit without reviewer fields: $edit',
        async ({ toolName, edit }) => {
            const request = vi.fn().mockResolvedValue({ report_id: 'report-1' })
            const context = {
                api: { request, getProjectBaseUrl: vi.fn().mockReturnValue('https://us.posthog.com/project/42') },
                stateManager: { getProjectId: vi.fn().mockResolvedValue('42') },
            } as unknown as Context
            const tool = GENERATED_TOOLS[toolName]!()
            const input = { run_id: 'run-1', report_id: 'report-1', ...edit }
            await tool.handler(context, tool.schema.parse(input))
            expect(request.mock.calls[0]![0].body).toEqual({ report_id: 'report-1', ...edit })
        }
    )

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

    it.each(toolNames)('%s preserves an explicit reviewer proposal', async (toolName) => {
        const request = vi.fn().mockResolvedValue({ report_id: 'report-1' })
        const context = {
            api: { request, getProjectBaseUrl: vi.fn().mockReturnValue('https://us.posthog.com/project/42') },
            stateManager: { getProjectId: vi.fn().mockResolvedValue('42') },
        } as unknown as Context
        const tool = GENERATED_TOOLS[toolName]!()
        const input = {
            run_id: 'run-1',
            report_id: 'report-1',
            suggested_reviewers: [{ github_login: 'reviewer', reason: 'Owns the affected surface.' }],
            expected_reviewers: { reviewers_id: null, corrections_id: null },
            reviewer_outcome: 'selected' as const,
        }
        await tool.handler(context, tool.schema.parse(input))
        expect(request.mock.calls[0]![0].body).toEqual({
            report_id: 'report-1',
            suggested_reviewers: input.suggested_reviewers,
            expected_reviewers: input.expected_reviewers,
            reviewer_outcome: 'selected',
        })
    })
})
