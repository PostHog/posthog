import { describe, expect, it } from 'vitest'

import { InstructionsBuilder } from '@/hono/instructions'
import type { ResolvedState } from '@/hono/request-state-resolver'
import { MCPClientProfile } from '@/lib/client-detection'
import { getToolDefinitions } from '@/tools/toolDefinitions'

import { makeToolExecutorState } from '../shared/test-utils'

const CATALOG_TOOL_NAMES = Object.keys(getToolDefinitions())
const CATALOG = new Set(CATALOG_TOOL_NAMES)

/** Tools named in prose that predates any availability gate. Each one is still a
 *  live instance of the same defect, kept as a ratchet rather than fixed here:
 *  `analysis-artifacts` and `url-patterns` name dashboard and link tools, the
 *  metric-discovery sections name the data-catalog trio, and `examples`,
 *  `retrieving-data`, `cli-data-discovery` and `schema-workflow` name query, SQL,
 *  schema and skill tools. Remove a name once its section gates the mention. */
const UNGATED_BY_DESIGN = new Set([
    'actions-get-all',
    'agent-feedback',
    'business-knowledge-document-window-retrieve',
    'dashboard-create',
    'dashboard-get',
    'dashboard-widgets-batch-add',
    'dashboards-get-all',
    'data-catalog-metric-run',
    'execute-sql',
    'feature-flag-get-all',
    'generate-app-url',
    'insight-create',
    'insight-get',
    'metric-describe',
    'metric-list',
    'query-funnel',
    'query-lifecycle',
    'query-llm-traces-list',
    'query-paths',
    'query-retention',
    'query-stickiness',
    'query-trends',
    'read-data-schema',
    'skill-get',
])

/** Catalog tools the rendered guidance names in backticks. Tokens no tool claims
 *  (`series`, `call`, `$pageview`) are prose, so they are left out. */
function advertisedCommands(text: string): string[] {
    const named = new Set<string>()
    for (const match of text.matchAll(/`([a-z][a-z0-9-]*)`/g)) {
        const token = match[1]
        if (token && CATALOG.has(token)) {
            named.add(token)
        }
    }
    return [...named].sort()
}

/** Both surfaces an agent reads before its first call, plus the separate
 *  reference Claude web/desktop gets. */
function execGuidance(toolNames: string[]): string {
    const builder = new InstructionsBuilder('some guidelines')
    const state = (vendorClient?: string): ResolvedState =>
        makeToolExecutorState(
            toolNames.map((name) => ({ name })),
            { clientProfile: new MCPClientProfile(vendorClient ? { vendorClient } : {}) }
        )
    return [
        builder.buildExecToolDescription(state()),
        builder.buildExecCommandReference(state()),
        builder.buildExecCommandReference(state('ClaudeAI')),
    ].join('\n\n')
}

/** A command the guidance names is only safe if the guidance stops naming it once
 *  the connection loses the tool — otherwise the agent is sent to a name `search`
 *  and `call` cannot resolve. */
function namesToolWhenWithheld(name: string): boolean {
    const available = CATALOG_TOOL_NAMES.filter((tool) => tool !== name)
    return advertisedCommands(execGuidance(available)).includes(name)
}

describe('exec guidance advertises only resolvable commands', () => {
    const advertised = advertisedCommands(execGuidance(CATALOG_TOOL_NAMES))
    const gated = advertised.filter((name) => !UNGATED_BY_DESIGN.has(name))

    it('gates every advertised command that is not a known exemption', () => {
        expect(gated.filter(namesToolWhenWithheld)).toEqual([])
    })

    it('keeps the exemption list free of names that are now gated', () => {
        const stale = [...UNGATED_BY_DESIGN].filter((name) => !namesToolWhenWithheld(name)).sort()
        expect(stale).toEqual([])
    })

    it('names docs-search when the connection holds it', () => {
        expect(advertised).toContain('docs-search')
    })
})
