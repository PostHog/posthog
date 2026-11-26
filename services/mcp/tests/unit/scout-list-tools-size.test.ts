import { describe, expect, it, vi } from 'vitest'

import { CODEX_TOOL_RESULT_TOKEN_LIMIT } from '@/lib/client-detection'
import { formatResponse } from '@/lib/response'
import { byteLength, maxResponseBytes } from '@/lib/response-budget'
import { GENERATED_TOOL_MAP } from '@/tools/generated'
import type { Context } from '@/tools/types'

// Scouts read these lists to dedupe and to see the fleet, and the Codex limit drops the rows
// past it. A default page has to fit with room left for longer rows than these.
const HEADROOM_BYTES = maxResponseBytes(CODEX_TOOL_RESULT_TOKEN_LIMIT) * 0.7

const prose = (length: number): string => 'checked the checkout funnel and the error spike. '.repeat(length / 50)

function runRow(index: number): Record<string, unknown> {
    const runId = `0199a000-0000-7000-8000-${String(index).padStart(12, '0')}`
    return {
        run_id: runId,
        skill_name: 'signals-scout-error-tracking',
        skill_version: 12,
        status: 'failed',
        created_at: '2026-11-20T10:00:00Z',
        started_at: '2026-11-20T10:00:01Z',
        completed_at: '2026-11-20T10:20:00Z',
        task_id: runId,
        task_run_id: runId,
        task_url: `/project/1/tasks/${runId}?runId=${runId}`,
        summary: prose(4000),
        summary_lead: `${prose(600).slice(0, 599)}…`,
        error: prose(1500),
        failure_reason: 'Sandbox turn timed out after the run budget',
        emitted_count: 1,
        emitted_finding_ids: ['finding-1'],
        emitted_report_ids: [runId],
        edited_report_ids: [runId],
        metadata: { harness_prompt_version: 'v42', report_channel: 'both', notes: prose(800) },
        total_spend: 12.5,
    }
}

function configRow(index: number): Record<string, unknown> {
    const owner = { id: index, uuid: `owner-${index}`, distinct_id: `distinct-${index}`, first_name: 'Ada' }
    return {
        id: `0199b000-0000-7000-8000-${String(index).padStart(12, '0')}`,
        skill_name: `signals-scout-example-${index}`,
        display_name: `Example ${index}`,
        description: prose(250),
        scout_origin: 'canonical',
        scout_role: 'product',
        enabled: true,
        status: 'active',
        pause_reason: null,
        emit: true,
        run_interval_minutes: 1440,
        run_cron_schedule: null,
        last_run_at: '2026-11-20T10:00:00Z',
        consecutive_failure_count: 0,
        last_precheck_at: '2026-11-20T10:00:00Z',
        last_precheck_outcome: 'run',
        tags: ['errors'],
        source_product: null,
        owners: [{ ...owner, hedgehog_config: { color: 'blue', accessories: ['hat'] } }],
        status_changed_by: owner,
        structured_output_schema: { type: 'object', description: prose(400) },
        precheck_query: prose(500),
        effective_precheck_query: prose(500),
        output_destinations: { slack: { channel: 'C0000000000' } },
        write_scopes: ['notebook:write'],
    }
}

async function callTool(
    name: string,
    rows: Record<string, unknown>[]
): Promise<{ results: Record<string, unknown>[] }> {
    const context = {
        api: { request: vi.fn().mockResolvedValue(rows), getProjectBaseUrl: () => 'https://example.com/project/1' },
        stateManager: { getProjectId: async () => '1' },
    } as unknown as Context
    const tool = GENERATED_TOOL_MAP[name]!()
    return (await tool.handler(context, tool.schema.parse({}))) as { results: Record<string, unknown>[] }
}

describe('scout list tools fit one Codex tool result', () => {
    it.each([
        { tool: 'scout-runs-list', rows: Array.from({ length: 20 }, (_, index) => runRow(index)), key: 'run_id' },
        {
            tool: 'scout-config-list',
            rows: Array.from({ length: 35 }, (_, index) => configRow(index)),
            key: 'skill_name',
        },
    ])('returns every row of a default $tool page in a compact text', async ({ tool, rows, key }) => {
        const result = await callTool(tool, rows)

        expect(result.results.map((row) => row[key])).toEqual(rows.map((row) => row[key]))
        expect(byteLength(formatResponse(result))).toBeLessThan(HEADROOM_BYTES)
    })
})
