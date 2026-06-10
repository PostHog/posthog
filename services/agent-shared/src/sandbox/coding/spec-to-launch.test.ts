import { describe, expect, it } from 'vitest'

import { AgentSpec, AgentSpecSchema } from '../../spec/spec'
import { renderLaunchConfig } from './spec-to-launch'

function spec(overrides: Record<string, unknown> = {}): AgentSpec {
    return AgentSpecSchema.parse({
        model: 'anthropic/claude-sonnet-4-6',
        ...overrides,
    })
}

describe('renderLaunchConfig', () => {
    it('maps model into provider + model id, reasoning, and limits', () => {
        const cfg = renderLaunchConfig(
            spec({
                reasoning: 'high',
                limits: {
                    max_turns: 50,
                    max_tool_calls: 200,
                    max_wall_seconds: 600,
                    max_memory_mb: 2048,
                    max_cpu_cores: 2,
                },
            })
        )
        expect(cfg.provider).toBe('anthropic')
        expect(cfg.model).toBe('claude-sonnet-4-6')
        expect(cfg.reasoningEffort).toBe('high')
        expect(cfg.limits).toEqual({ memoryMb: 2048, cpuCores: 2, wallSeconds: 600 })
    })

    it('leaves provider unset when the model id has no provider prefix', () => {
        const cfg = renderLaunchConfig(spec({ model: 'claude-sonnet-4-6' }))
        expect(cfg.provider).toBeUndefined()
        expect(cfg.model).toBe('claude-sonnet-4-6')
    })

    it('threads modelBaseUrl + systemPrompt through', () => {
        const cfg = renderLaunchConfig(spec(), {
            modelBaseUrl: 'http://host.docker.internal:9911/inference',
            systemPrompt: 'You are a coding agent.',
        })
        expect(cfg.modelBaseUrl).toBe('http://host.docker.internal:9911/inference')
        expect(cfg.systemPrompt).toBe('You are a coding agent.')
    })

    it('maps skills to id + description', () => {
        const cfg = renderLaunchConfig(
            spec({
                skills: [{ id: 'debug', path: 'skills/debug', description: 'Debug sessions' }],
            })
        )
        expect(cfg.skills).toEqual([{ id: 'debug', description: 'Debug sessions' }])
    })

    it('passes runtime MCPs through the resolver into mcpServers', () => {
        const cfg = renderLaunchConfig(
            spec({
                mcps: [{ id: 'linear', url: 'https://mcp.linear.app', secrets: [] }],
            }),
            {
                resolveMcp: (ref) => ({
                    type: 'http',
                    name: ref.id,
                    url: ref.url,
                    headers: [{ name: 'Authorization', value: 'Bearer tok' }],
                }),
            }
        )
        expect(cfg.mcpServers).toContainEqual({
            type: 'http',
            name: 'linear',
            url: 'https://mcp.linear.app',
            headers: [{ name: 'Authorization', value: 'Bearer tok' }],
        })
    })

    it('adds the tier-3 custom-tool broker MCP only when the spec has custom tools', () => {
        const withCustom = renderLaunchConfig(
            spec({
                tools: [{ kind: 'custom', id: 'fetch-data', path: 'tools/fetch-data' }],
            }),
            { customToolBroker: { url: 'http://host.docker.internal:9912/mcp', bearer: 'sess-tok' } }
        )
        expect(withCustom.mcpServers).toContainEqual({
            type: 'http',
            name: 'posthog-custom-tools',
            url: 'http://host.docker.internal:9912/mcp',
            headers: [{ name: 'Authorization', value: 'Bearer sess-tok' }],
        })

        const noCustom = renderLaunchConfig(spec(), {
            customToolBroker: { url: 'http://host.docker.internal:9912/mcp', bearer: 'sess-tok' },
        })
        expect(noCustom.mcpServers.find((m) => m.name === 'posthog-custom-tools')).toBeUndefined()
    })

    it('sets writable from the trust profile', () => {
        expect(renderLaunchConfig(spec({ sandbox: { trust_profile: 'coding-readonly' } })).writable).toBe(false)
        expect(renderLaunchConfig(spec({ sandbox: { trust_profile: 'coding-write' } })).writable).toBe(true)
        expect(renderLaunchConfig(spec({ sandbox: { trust_profile: 'coding-pr' } })).writable).toBe(true)
    })

    it('passes the pinned workspace through', () => {
        const cfg = renderLaunchConfig(
            spec({
                sandbox: { trust_profile: 'coding-readonly', workspace: { repo: 'posthog/posthog', ref: 'abc123' } },
            })
        )
        expect(cfg.workspace).toEqual({ repo: 'posthog/posthog', ref: 'abc123' })
    })
})
