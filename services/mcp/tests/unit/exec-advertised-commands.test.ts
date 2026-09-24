import { describe, expect, it } from 'vitest'
import { z } from 'zod'

import { InstructionsBuilder } from '@/hono/instructions'
import type { ResolvedState } from '@/hono/request-state-resolver'
import { MCPClientProfile } from '@/lib/client-detection'
import { createExecTool } from '@/tools/exec'
import { getToolDefinitions } from '@/tools/toolDefinitions'
import type { Context, Tool, ZodObjectAny } from '@/tools/types'

import { makeToolExecutorState } from '../shared/test-utils'

const CATALOG_TOOL_NAMES = Object.keys(getToolDefinitions())
const CATALOG = new Set(CATALOG_TOOL_NAMES)

/** Tools named in prose that predates any availability gate. Each one is still a
 *  live instance of the same defect, kept as a ratchet rather than fixed here:
 *  `analysis-artifacts` and `url-patterns` name dashboard and link tools, the
 *  metric-discovery sections name the data-catalog trio, and `examples`,
 *  `retrieving-data`, `cli-data-discovery` and `schema-workflow` name query, SQL,
 *  schema and skill tools. `cli-rendering` names a tool as an example of one
 *  `render-ui` can render, and `cli-syntax` names one as an example of a namespaced
 *  reference. Remove a name once its section gates the mention. */
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
    'experiment-get',
    'feature-flag-get-all',
    'generate-app-url',
    'insight-create',
    'insight-get',
    'insights-list',
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

/** Backticked kebab-case names the guidance uses, which is the shape every tool
 *  name has. Single-word tokens (`series`, `call`) are prose and cannot be a tool. */
function backtickedNames(text: string): string[] {
    const named = new Set<string>()
    for (const match of text.matchAll(/`([a-z][a-z0-9]*(?:-[a-z0-9]+)+)`/g)) {
        const token = match[1]
        if (token) {
            named.add(token)
        }
    }
    return [...named].sort()
}

/** Unlike `backtickedNames`, this scans inside the span, so a name still counts
 *  when the span holds a whole invocation (`call docs-search <json_input>`). URL
 *  slugs that share the shape drop out against the catalog. */
function namedCatalogTools(text: string): string[] {
    const named = new Set<string>()
    for (const span of text.matchAll(/`([^`\n]+)`/g)) {
        for (const match of (span[1] ?? '').matchAll(/[a-z][a-z0-9]*(?:-[a-z0-9]+)+/g)) {
            if (CATALOG.has(match[0])) {
                named.add(match[0])
            }
        }
    }
    return [...named].sort()
}

/** Kebab-case names that are deliberately not exec commands: a built-in skill
 *  loaded by name, and the render-ui tool, which MCP Apps hosts get as its own
 *  MCP tool rather than through the exec catalog. */
const NOT_EXEC_COMMANDS = new Set(['querying-posthog-data', 'render-ui'])

function advertisedCommands(text: string): string[] {
    return namedCatalogTools(text)
}

/** Both surfaces an agent reads before its first call, plus the separate
 *  reference Claude web/desktop gets. */
function execGuidance(toolNames: string[]): string {
    const builder = new InstructionsBuilder('some guidelines')
    const state = (vendorClient?: string, renderUiEnabled = false): ResolvedState =>
        makeToolExecutorState(
            toolNames.map((name) => ({ name })),
            { clientProfile: new MCPClientProfile(vendorClient ? { vendorClient } : {}), renderUiEnabled }
        )
    return [
        builder.buildExecToolDescription(state()),
        builder.buildExecCommandReference(state()),
        builder.buildExecCommandReference(state('ClaudeAI')),
        builder.buildExecCommandReference(state(undefined, true)),
    ].join('\n\n')
}

/** A command the guidance names is only safe if the guidance stops naming it once
 *  the connection loses the tool — otherwise the agent is sent to a name `search`
 *  and `call` cannot resolve. */
function namesToolWhenWithheld(name: string): boolean {
    const available = CATALOG_TOOL_NAMES.filter((tool) => tool !== name)
    return advertisedCommands(execGuidance(available)).includes(name)
}

const CATALOG_TOOLS: Tool<ZodObjectAny>[] = CATALOG_TOOL_NAMES.map((name) => ({
    name,
    title: name,
    description: name,
    schema: z.object({}),
    scopes: [],
    annotations: { destructiveHint: false, idempotentHint: true, openWorldHint: false, readOnlyHint: true },
    handler: async () => ({}),
}))

async function replyToBareCommand(name: string): Promise<string> {
    const exec = createExecTool(CATALOG_TOOLS, {} as Context, 'description', 'reference', undefined)
    return exec.handler({} as Context, { command: `${name} {}` }).then(
        (result) => String(result),
        (error: Error) => error.message
    )
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

    it('names no command that the catalog cannot resolve', () => {
        const unresolvable = backtickedNames(execGuidance(CATALOG_TOOL_NAMES)).filter(
            (name) => !CATALOG.has(name) && !NOT_EXEC_COMMANDS.has(name)
        )
        expect(unresolvable).toEqual([])
    })

    it('names docs-search when the connection holds it', () => {
        expect(advertised).toContain('docs-search')
    })

    // Resolvable is not the same as reachable: an agent reading a CLI contract types
    // an advertised name as a command, so the reply must carry the form that works.
    it('routes every advertised command to the invocation the dispatcher accepts', async () => {
        const deadEnds: string[] = []
        for (const name of advertised) {
            const reply = await replyToBareCommand(name)
            if (!reply.includes(`call ${name}`)) {
                deadEnds.push(name)
            }
        }
        expect(deadEnds).toEqual([])
    })
})
