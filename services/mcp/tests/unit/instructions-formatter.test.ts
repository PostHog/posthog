import { describe, expect, it } from 'vitest'

import type { GroupType } from '@/api/client'
import type { QueryToolInfo } from '@/lib/instructions'
import { InstructionsFormatter, type InstructionsContext } from '@/lib/instructions-formatter'

const realisticGroupTypes: GroupType[] = [
    { group_type: 'organization', group_type_index: 0, name_singular: null, name_plural: null },
]
const realisticTools = [
    { name: 'dashboard-create', category: 'Dashboards' },
    { name: 'dashboard-get', category: 'Dashboards' },
    { name: 'feature-flag-create', category: 'Feature flags' },
    { name: 'feature-flag-get-all', category: 'Feature flags' },
    { name: 'execute-sql', category: 'SQL' },
]
const realisticQueryTools: QueryToolInfo[] = [
    { name: 'query-trends', title: 'Trends', systemPromptHint: 'time series' },
    { name: 'query-funnel', title: 'Funnel', systemPromptHint: 'conversion rate' },
]
const realisticMetadata =
    'You are currently in project "My App" (id: 1) within organization "Acme" (id: org_1).\n' +
    'Project timezone: America/New_York.\n' +
    "The user's name is Jane Doe (jane@acme.com)."

const fullCtx: InstructionsContext = {
    guidelines: 'some guidelines',
    groupTypes: realisticGroupTypes,
    metadata: realisticMetadata,
    tools: realisticTools,
    queryTools: realisticQueryTools,
    featureFlags: { 'mcp-feedback-tool': true },
}

describe('InstructionsFormatter', () => {
    describe('buildV1Instructions', () => {
        it('returns the legacy section content when no metadata is supplied', () => {
            const formatter = new InstructionsFormatter()
            const result = formatter.buildV1Instructions()
            expect(result).toContain('helpful assistant that can query PostHog API')
            expect(result).toContain("'docs-search' tool")
        })

        it('appends metadata to the legacy section when provided', () => {
            const formatter = new InstructionsFormatter()
            const metadata = 'You are currently in project "Test".'
            const result = formatter.buildV1Instructions(metadata)
            expect(result).toContain('helpful assistant that can query PostHog API')
            expect(result).toContain('You are currently in project "Test".')
            const legacyIdx = result.indexOf('helpful assistant')
            const metaIdx = result.indexOf('You are currently')
            expect(legacyIdx).toBeLessThan(metaIdx)
        })

        it('treats an empty metadata string as no metadata', () => {
            const formatter = new InstructionsFormatter()
            expect(formatter.buildV1Instructions('')).toBe(formatter.buildV1Instructions())
        })
    })

    describe('buildV2Instructions', () => {
        it('resolves every placeholder when fully populated', () => {
            const formatter = new InstructionsFormatter()
            const result = formatter.buildV2Instructions(fullCtx)
            expect(result).toContain('Defined group types: organization')
            expect(result).toContain("The user's name is Jane Doe")
            expect(result).toContain('Project timezone: America/New_York.')
            expect(result).toContain('- dashboard')
            expect(result).toContain('- feature-flag')
            expect(result).toContain('- execute-sql')
            expect(result).toContain('- `query-funnel` — conversion rate')
            expect(result).toContain('- `query-trends` — time series')
            expect(result).not.toMatch(
                /\{tool_domains\}|\{query_tools\}|\{metadata\}|\{defined_groups\}|\{guidelines\}/
            )
        })

        it('renders the basic functionality, retrieving data, and examples sections', () => {
            const formatter = new InstructionsFormatter()
            const result = formatter.buildV2Instructions(fullCtx)
            expect(result).toContain('### Basic functionality')
            expect(result).toContain('### Retrieving data')
            expect(result).toContain('### Examples')
        })

        it('does not leak any CLI-only sections (tools mode is not exec mode)', () => {
            const formatter = new InstructionsFormatter()
            const result = formatter.buildV2Instructions(fullCtx)
            expect(result).not.toContain('SCHEMA DRILL-DOWN RULE')
            expect(result).not.toContain('Using the `posthog` tool')
            expect(result).not.toContain('CLI-style command string')
        })

        it('omits placeholders cleanly when context fields are undefined', () => {
            const formatter = new InstructionsFormatter()
            const result = formatter.buildV2Instructions({ guidelines: 'rules' })
            expect(result).not.toContain('{guidelines}')
            expect(result).not.toContain('{defined_groups}')
            expect(result).not.toContain('{tool_domains}')
            expect(result).not.toContain('{query_tools}')
            expect(result).not.toContain('{metadata}')
        })

        it('includes the agent-feedback section only when the mcp-feedback-tool flag is on', () => {
            const formatter = new InstructionsFormatter()
            const withFeedback = formatter.buildV2Instructions(fullCtx)
            expect(withFeedback).toContain('### Sharing feedback on this MCP server')

            for (const featureFlags of [undefined, { 'mcp-feedback-tool': false }, {}]) {
                const result = formatter.buildV2Instructions({ ...fullCtx, featureFlags })
                expect(result).not.toContain('### Sharing feedback on this MCP server')
            }
        })
    })

    describe('buildExecInstructions', () => {
        it('renders the compact instructions section with placeholders resolved', () => {
            const formatter = new InstructionsFormatter()
            const result = formatter.buildExecInstructions(fullCtx)
            expect(result).toContain('dashboard|execute-sql|feature-flag')
            expect(result).toContain('funnel|trends')
            expect(result).toContain('Defined group types: organization')
            expect(result).toContain("The user's name is Jane Doe")
            expect(result).not.toMatch(
                /\{tool_domains\}|\{query_tools\}|\{metadata\}|\{defined_groups\}|\{guidelines\}/
            )
        })

        // Claude Code caps MCP `instructions` at 2048 chars — stay under the budget with
        // a realistic-ish tool count so this asserts something meaningful. 60 domains +
        // 12 query tools ≈ today's v2 deployment.
        it('stays under the 2048-character budget at realistic tool counts', () => {
            const manyTools = Array.from({ length: 60 }, (_, i) => ({
                name: `domain-${i}-get`,
                category: `Category ${i % 6}`,
            }))
            const manyQueryTools: QueryToolInfo[] = Array.from({ length: 12 }, (_, i) => ({
                name: `query-tool-${i}`,
                title: `Query tool ${i}`,
                systemPromptHint: `short hint for query tool ${i}`,
            }))
            const formatter = new InstructionsFormatter()
            const result = formatter.buildExecInstructions({
                guidelines: 'guidelines',
                groupTypes: realisticGroupTypes,
                metadata: realisticMetadata,
                tools: manyTools,
                queryTools: manyQueryTools,
            })
            expect(result.length).toBeLessThanOrEqual(2048)
        })

        it('does not bleed the full command reference into the compact instructions', () => {
            const formatter = new InstructionsFormatter()
            const result = formatter.buildExecInstructions(fullCtx)
            expect(result).not.toContain('SCHEMA DRILL-DOWN RULE')
            expect(result).not.toContain('### Basic functionality')
            expect(result).not.toContain('### Examples')
        })
    })

    describe('buildExecToolDescription', () => {
        it('renders just the exec tool blurb, no other sections', () => {
            const formatter = new InstructionsFormatter()
            const result = formatter.buildExecToolDescription()
            expect(result).toContain('Using the `posthog` tool')
            expect(result).toContain('MANDATORY — HARD REQUIREMENTS')
            expect(result).not.toContain('### Basic functionality')
            expect(result).not.toContain('### Examples')
        })
    })

    describe('buildExecCommandReference', () => {
        it('carries the CLI mechanics regardless of stripEnvContext', () => {
            const formatter = new InstructionsFormatter()
            for (const stripEnvContext of [true, false]) {
                const result = formatter.buildExecCommandReference(fullCtx, { stripEnvContext })
                expect(result).toContain('SCHEMA DRILL-DOWN RULE')
                expect(result).toContain('### Basic functionality')
                expect(result).toContain('### Examples')
            }
        })

        it('does not include the exec-tool blurb (that lives on the tool description)', () => {
            const formatter = new InstructionsFormatter()
            const result = formatter.buildExecCommandReference(fullCtx, { stripEnvContext: false })
            expect(result).not.toContain('Using the `posthog` tool')
        })

        it('embeds env-context, tool-domain list, and query-tool catalog when stripEnvContext is false', () => {
            const formatter = new InstructionsFormatter()
            const result = formatter.buildExecCommandReference(fullCtx, { stripEnvContext: false })
            expect(result).toContain("The user's name is Jane Doe")
            expect(result).toContain('Defined group types: organization')
            expect(result).toContain('- dashboard')
            expect(result).toContain('- `query-trends` — time series')
        })

        it('strips env-context, tool-domain list, and query-tool catalog when stripEnvContext is true', () => {
            const formatter = new InstructionsFormatter()
            const result = formatter.buildExecCommandReference(fullCtx, { stripEnvContext: true })
            expect(result).not.toContain("The user's name is Jane Doe")
            expect(result).not.toContain('Defined group types: organization')
            expect(result).not.toContain('- `query-trends` — time series')
            // The bullet for the `dashboard` domain would clash with in-prose mentions,
            // so anchor on the list-prefix newline pattern to avoid false positives.
            expect(result).not.toContain('\n- dashboard\n')
        })

        it('includes the agent-feedback section only when the mcp-feedback-tool flag is on', () => {
            const formatter = new InstructionsFormatter()
            for (const stripEnvContext of [true, false]) {
                const withFeedback = formatter.buildExecCommandReference(fullCtx, { stripEnvContext })
                expect(withFeedback).toContain('### Sharing feedback on this MCP server')

                const withoutFeedback = formatter.buildExecCommandReference(
                    { ...fullCtx, featureFlags: { 'mcp-feedback-tool': false } },
                    { stripEnvContext }
                )
                expect(withoutFeedback).not.toContain('### Sharing feedback on this MCP server')
            }
        })
    })

    // Mirrors the single-exec wiring in `src/mcp.ts`. When the client honors the MCP
    // `instructions` field, four pieces move out of the `command` description and into
    // `instructions`: tool domains, available query tools, user preferences (timezone/name
    // via `{metadata}`), and defined group types. Codex (no `instructions` support) keeps
    // today's behavior: empty `instructions`, everything inlined in the `command` description.
    describe('exec mode wiring', () => {
        it.each([
            { name: 'supportsInstructions=true (Claude Code etc.)', supportsInstructions: true },
            { name: 'supportsInstructions=false (Codex)', supportsInstructions: false },
        ])('$name: splits product context between instructions and commandReference', ({ supportsInstructions }) => {
            const formatter = new InstructionsFormatter()
            const instructions = supportsInstructions ? formatter.buildExecInstructions(fullCtx) : ''
            const commandReference = formatter.buildExecCommandReference(fullCtx, {
                stripEnvContext: supportsInstructions,
            })

            expect(commandReference).toContain('SCHEMA DRILL-DOWN RULE')
            expect(commandReference).toContain('### Basic functionality')

            if (supportsInstructions) {
                expect(instructions).toContain('funnel|trends')
                expect(instructions).toContain("The user's name is Jane Doe")
                expect(instructions).toContain('dashboard|execute-sql|feature-flag')
                expect(instructions).toContain('Defined group types: organization')
                expect(commandReference).not.toContain("The user's name is Jane Doe")
                expect(commandReference).not.toContain('Defined group types: organization')
                expect(commandReference).not.toContain('- `query-trends` — time series')
                expect(commandReference).not.toContain('\n- dashboard\n')
            } else {
                expect(instructions).toBe('')
                expect(commandReference).toContain('- `query-trends` — time series')
                expect(commandReference).toContain("The user's name is Jane Doe")
                expect(commandReference).toContain('- dashboard')
                expect(commandReference).toContain('Defined group types: organization')
            }
        })
    })
})
