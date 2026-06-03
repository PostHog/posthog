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
})
