import { describe, expect, it } from 'vitest'

import { MCPClientProfile } from '@/lib/client-detection'
import { InstructionsBuilder } from '@/hono/instructions'
import type { ResolvedState } from '@/hono/request-state-resolver'
import { getToolDefinitions } from '@/tools/toolDefinitions'

const CATALOG_TOOL_NAMES = Object.keys(getToolDefinitions())

/** Tools the prompt names as a command to run, and that the catalog can withhold
 *  from a connection (a feature allowlist, a missing scope, a feature flag, or an
 *  `x-posthog-exclude-tools` denylist). Each one needs its guidance gated on
 *  availability, or the agent follows the prompt into a name `search` and `call`
 *  cannot resolve. */
const GATED_TOOLS = ['docs-search', 'business-knowledge-documents-search', 'notebooks-add-cell']

/** Every catalog tool the rendered guidance names in backticks. Tokens that no
 *  tool definition claims (`series`, `call`, `$pageview`, ...) are prose, so they
 *  are left out rather than guessed at. */
function advertisedCommands(text: string): string[] {
    const catalog = new Set(CATALOG_TOOL_NAMES)
    const named = new Set<string>()
    for (const match of text.matchAll(/`([a-z][a-z0-9-]*)`/g)) {
        const token = match[1]
        if (token && catalog.has(token)) {
            named.add(token)
        }
    }
    return [...named].sort()
}

function stateWith(toolNames: string[], vendorClient?: string): ResolvedState {
    return {
        allTools: toolNames.map((name) => ({ name })),
        clientProfile: new MCPClientProfile(vendorClient ? { vendorClient } : {}),
        toolFeatureFlags: {},
        renderUiEnabled: false,
        metadata: 'You are currently in project "My App" (id: 1, token: token_1).',
        groupTypes: [],
        requestContext: { mcpConsumer: undefined },
        sessionContext: null,
    } as unknown as ResolvedState
}

/** Both surfaces an agent reads before its first call: the exec tool description
 *  and the `command` parameter reference. Claude web/desktop gets a separate
 *  reference builder, so it is rendered too. */
function execGuidance(toolNames: string[]): string {
    const builder = new InstructionsBuilder('some guidelines')
    return [
        builder.buildExecToolDescription(stateWith(toolNames)),
        builder.buildExecCommandReference(stateWith(toolNames)),
        builder.buildExecCommandReference(stateWith(toolNames, 'ClaudeAI')),
    ].join('\n\n')
}

describe('exec guidance advertises only resolvable commands', () => {
    it('names no command the catalog cannot resolve', () => {
        const unknown = advertisedCommands(execGuidance(CATALOG_TOOL_NAMES)).filter(
            (name) => !CATALOG_TOOL_NAMES.includes(name)
        )
        expect(unknown).toEqual([])
    })

    it.each(GATED_TOOLS)('never names %s when the connection does not hold it', (withheld) => {
        const available = CATALOG_TOOL_NAMES.filter((name) => name !== withheld)
        expect(advertisedCommands(execGuidance(available))).not.toContain(withheld)
    })

    it('still names docs-search when the connection holds it', () => {
        expect(advertisedCommands(execGuidance(CATALOG_TOOL_NAMES))).toContain('docs-search')
    })
})
