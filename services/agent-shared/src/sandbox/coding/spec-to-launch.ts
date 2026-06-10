/**
 * spec → coding-harness launch config. This is the §3.1 mapping table from
 * docs/agent-platform/plans/agent-sandbox-tiers.md, as code. It is the
 * supervisor's core new component: it turns a frozen `AgentSpec` into the
 * config the tier-2 harness boots with.
 *
 * Pure + side-effect free — secret/integration resolution is injected via
 * `resolveMcp` / `customToolBroker` so the plaintext never has to live here.
 */

import type { AgentSpec } from '../../spec/spec'
import type { McpRef } from '../../spec/spec'
import type { CodingLaunchConfig, McpServerConfig } from './contract'

export interface RenderOpts {
    /** Base URL the harness sends inference to — the session-scoped proxy (§8). */
    modelBaseUrl?: string
    /** Rendered system prompt (framework preamble + agent.md). */
    systemPrompt?: string
    /** MCP endpoint fronting the tier-3 custom-tool broker. Added iff the spec has custom tools. */
    customToolBroker?: { url: string; bearer: string }
    /** Resolve a runtime MCP ref (spec.mcps[]) to a concrete server config (URL + headers). */
    resolveMcp?: (ref: McpRef) => McpServerConfig | null
}

const WRITABLE_PROFILES = new Set(['coding-write', 'coding-pr'])

/** Split `anthropic/claude-...` into provider + model id; no slash → no provider. */
function splitModel(model: string): { provider?: string; model: string } {
    const idx = model.indexOf('/')
    if (idx === -1) {
        return { model }
    }
    return { provider: model.slice(0, idx), model: model.slice(idx + 1) }
}

export function renderLaunchConfig(spec: AgentSpec, opts: RenderOpts = {}): CodingLaunchConfig {
    const { provider, model } = splitModel(spec.model)

    const mcpServers: McpServerConfig[] = []
    for (const ref of spec.mcps) {
        const resolved = opts.resolveMcp?.(ref)
        if (resolved) {
            mcpServers.push(resolved)
        }
    }

    const hasCustomTools = spec.tools.some((t) => t.kind === 'custom')
    if (hasCustomTools && opts.customToolBroker) {
        mcpServers.push({
            type: 'http',
            name: 'posthog-custom-tools',
            url: opts.customToolBroker.url,
            headers: [{ name: 'Authorization', value: `Bearer ${opts.customToolBroker.bearer}` }],
        })
    }

    const trustProfile = spec.sandbox?.trust_profile ?? 'frozen'

    return {
        model,
        provider,
        reasoningEffort: spec.reasoning,
        modelBaseUrl: opts.modelBaseUrl,
        systemPrompt: opts.systemPrompt,
        skills: spec.skills.map((s) => ({ id: s.id, description: s.description ?? '' })),
        mcpServers,
        workspace: spec.sandbox?.workspace,
        limits: {
            memoryMb: spec.limits.max_memory_mb,
            cpuCores: spec.limits.max_cpu_cores,
            wallSeconds: spec.limits.max_wall_seconds,
        },
        writable: WRITABLE_PROFILES.has(trustProfile),
    }
}
