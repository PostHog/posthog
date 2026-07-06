import { describe, expect, it } from 'vitest'

import { resolveMode } from '@/hono/request-state-resolver'
import { MCPClientProfile } from '@/lib/client-detection'

describe('resolveMode', () => {
    function profile(overrides: Partial<ConstructorParameters<typeof MCPClientProfile>[0]> = {}): MCPClientProfile {
        return new MCPClientProfile({ clientName: 'generic-client', ...overrides })
    }

    const base = {
        mode: undefined as undefined,
        clientProfile: profile(),
        renderUiFlagEnabled: false,
    }

    it('defaults to tools mode, no single exec', () => {
        expect(resolveMode(base)).toEqual({ mode: 'tools', useSingleExec: false })
    })

    it('explicit mode=cli forces single exec', () => {
        expect(resolveMode({ ...base, mode: 'cli' })).toEqual({ mode: 'cli', useSingleExec: true })
    })

    it('explicit mode=tools disables single exec even for a coding agent', () => {
        const result = resolveMode({
            ...base,
            mode: 'tools',
            clientProfile: profile({ clientName: 'claude-code' }),
        })
        expect(result.useSingleExec).toBe(false)
    })

    it('coding agent activates single exec', () => {
        const result = resolveMode({
            ...base,
            clientProfile: profile({ clientName: 'claude-code' }),
        })
        expect(result).toEqual({ mode: 'cli', useSingleExec: true })
    })

    it('LibreChat activates single exec', () => {
        const result = resolveMode({
            ...base,
            clientProfile: profile({ clientName: 'LibreChat' }),
        })
        expect(result).toEqual({ mode: 'cli', useSingleExec: true })
    })

    it('non-coding agent does NOT activate single exec', () => {
        const result = resolveMode({
            ...base,
            clientProfile: profile({ clientName: 'some-dashboard-client' }),
        })
        expect(result.useSingleExec).toBe(false)
    })

    it('PostHog code consumer activates single exec', () => {
        const result = resolveMode({
            ...base,
            clientProfile: profile({ consumer: 'posthog-code' }),
        })
        expect(result.useSingleExec).toBe(true)
    })

    it('Claude web/desktop activates single exec when render-ui is enabled', () => {
        const result = resolveMode({
            ...base,
            clientProfile: profile({ vendorClient: 'ClaudeAI' }),
            renderUiFlagEnabled: true,
        })
        expect(result).toEqual({ mode: 'cli', useSingleExec: true })
    })

    it('Claude web/desktop detected via User-Agent activates single exec when render-ui is enabled', () => {
        const result = resolveMode({
            ...base,
            clientProfile: profile({ userAgent: 'Claude-User' }),
            renderUiFlagEnabled: true,
        })
        expect(result.useSingleExec).toBe(true)
    })

    it('Claude web/desktop detected via User-Agent stays single exec even when render-ui is disabled', () => {
        // Anthropic clients always run in CLI (single-exec) mode, so the Claude-User
        // user-agent resolves to single-exec regardless of the render-ui flag — the
        // flag only gates whether the `render-ui` tool itself is advertised.
        const result = resolveMode({
            ...base,
            clientProfile: profile({ userAgent: 'Claude-User' }),
            renderUiFlagEnabled: false,
        })
        expect(result.useSingleExec).toBe(true)
    })

    it('explicit mode=tools wins over Claude UI host even with render-ui enabled', () => {
        const result = resolveMode({
            ...base,
            mode: 'tools',
            clientProfile: profile({ vendorClient: 'ClaudeAI' }),
            renderUiFlagEnabled: true,
        })
        expect(result.useSingleExec).toBe(false)
    })
})
