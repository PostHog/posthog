import * as fs from 'node:fs'
import * as path from 'node:path'

import { describe, expect, it } from 'vitest'
import { parse as parseYaml } from 'yaml'

import { GENERATED_TOOLS } from '@/tools/generated/signals'

// A second tool on the same operation gives each filter two spellings, so an
// agent that reads one tool's description cannot call the other. Keep one tool
// on the operation, and keep the parameters that description names.
describe('inbox-reports-list owns the Inbox reports list operation', () => {
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
            sort: 'priority',
            limit: 10,
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
