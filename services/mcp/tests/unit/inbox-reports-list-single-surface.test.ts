import * as fs from 'node:fs'
import * as path from 'node:path'

import { describe, expect, it } from 'vitest'
import { parse as parseYaml } from 'yaml'

import { GENERATED_TOOLS } from '@/tools/generated/signals'

// The Inbox list operation once carried a second tool with its own hand-written
// input schema, so the same call had two spellings: `priorities` against
// `priority`, `scouts` against `scout`. One tool now owns the operation, and its
// description tells agents to page the actionable view with the caller's
// priority preference. These tests keep both parts true.
describe('inbox-reports-list is the only tool on the reports list operation', () => {
    const config = parseYaml(
        fs.readFileSync(path.resolve(__dirname, '../../../../products/signals/mcp/tools.yaml'), 'utf-8')
    ) as { tools: Record<string, { operation?: string; enabled?: boolean }> }

    it('has exactly one enabled tool for signals_reports_list', () => {
        const owners = Object.entries(config.tools)
            .filter(([, tool]) => tool.enabled && tool.operation === 'signals_reports_list')
            .map(([name]) => name)
        expect(owners).toEqual(['inbox-reports-list'])
    })

    it('keeps the parameters its description documents', () => {
        // The schema strips unknown keys, so assert the parsed output, not just that parsing passed.
        const call = {
            view: 'actionable',
            use_priority_preference: true,
            scope: 'teammate',
            teammate_uuid: '01a04d4c-9994-716b-8038-10627229a016',
            priority: 'P0,P1',
            source_product: 'error_tracking',
            scout: 'signals-scout-error-tracking',
        }
        const result = GENERATED_TOOLS['inbox-reports-list']!().schema.safeParse(call)
        expect(result.success).toBe(true)
        expect(result.data).toMatchObject(call)
    })
})
