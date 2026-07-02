import { describe, expect, it } from 'vitest'

import { InstructionsBuilder } from '@/hono/instructions'
import { InstructionsFormatter, type InstructionsContext } from '@/lib/instructions-formatter'
import { SQL_SCHEMA_DISCOVERY_FEATURE_FLAG } from '@/tools/posthogAiTools/readDataWarehouseSchema'

// The `mcp-sql-schema-discovery` flag is prompt-only: when on, no instruction names
// `read-data-warehouse-schema` and discovery is steered through
// `system.information_schema.*`. When off, the legacy tool-based discovery stays.
describe('mcp-sql-schema-discovery flag gating', () => {
    const ctx: InstructionsContext = {
        guidelines: 'some guidelines',
        tools: [
            { name: 'execute-sql', category: 'SQL' },
            { name: 'read-data-warehouse-schema', category: 'Data schema' },
        ],
    }

    describe('execute-sql description (InstructionsBuilder.formatExecuteSqlDescription)', () => {
        const builder = new InstructionsBuilder('some guidelines')

        it.each([undefined, {}, { [SQL_SCHEMA_DISCOVERY_FEATURE_FLAG]: false }])(
            'names read-data-warehouse-schema when the flag is off (%o)',
            (featureFlags) => {
                const result = builder.formatExecuteSqlDescription(featureFlags)
                expect(result).toContain('read-data-warehouse-schema')
                expect(result).not.toContain('system.information_schema')
            }
        )

        it('routes through system.information_schema and never names the tool when the flag is on', () => {
            const result = builder.formatExecuteSqlDescription({ [SQL_SCHEMA_DISCOVERY_FEATURE_FLAG]: true })
            expect(result).toContain('system.information_schema')
            expect(result).not.toContain('read-data-warehouse-schema')
        })
    })

    describe('entity discovery section (InstructionsFormatter)', () => {
        const formatter = new InstructionsFormatter()
        const renderBothModes = (c: InstructionsContext): string[] => [
            formatter.buildToolsInstructions(c),
            formatter.buildExecCommandReference(c, { stripEnvContext: false }),
        ]

        it('names read-data-warehouse-schema in both modes when the flag is off', () => {
            const [toolsMode, cliMode] = renderBothModes(ctx)
            expect(toolsMode).toContain('read-data-warehouse-schema')
            expect(toolsMode).not.toContain('system.information_schema')
            expect(cliMode).toContain('read-data-warehouse-schema')
            expect(cliMode).not.toContain('system.information_schema')
        })

        it('routes through system.information_schema in both modes when the flag is on', () => {
            const [toolsMode, cliMode] = renderBothModes({
                ...ctx,
                featureFlags: { [SQL_SCHEMA_DISCOVERY_FEATURE_FLAG]: true },
            })
            expect(toolsMode).toContain('system.information_schema')
            expect(toolsMode).not.toContain('read-data-warehouse-schema')
            expect(cliMode).toContain('system.information_schema')
            expect(cliMode).not.toContain('read-data-warehouse-schema')
        })
    })
})
