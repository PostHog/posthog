import { describe, expect, it } from 'vitest'

import { MCPClientProfile } from '@/lib/client-detection'
import { resolveMode } from '@/hono/request-state-resolver'

describe('resolveMode', () => {
    function profile(overrides: Partial<ConstructorParameters<typeof MCPClientProfile>[0]> = {}): MCPClientProfile {
        return new MCPClientProfile({ clientName: 'generic-client', ...overrides })
    }

    const base = {
        mode: undefined as undefined,
        singleExecFlagOn: false,
        clientProfile: profile(),
    }

    it('defaults to no single exec', () => {
        expect(resolveMode(base)).toEqual({ useSingleExec: false })
    })

    it('explicit mode=cli forces single exec', () => {
        expect(resolveMode({ ...base, mode: 'cli' })).toEqual({ useSingleExec: true })
    })

    it('explicit mode=tools disables single exec even when flag is on for a coding agent', () => {
        const result = resolveMode({
            ...base,
            mode: 'tools',
            singleExecFlagOn: true,
            clientProfile: profile({ clientName: 'claude-code' }),
        })
        expect(result.useSingleExec).toBe(false)
    })

    it('coding agent with flag on activates single exec', () => {
        const result = resolveMode({
            ...base,
            singleExecFlagOn: true,
            clientProfile: profile({ clientName: 'claude-code' }),
        })
        expect(result).toEqual({ useSingleExec: true })
    })

    it('non-coding agent with flag on does NOT activate single exec', () => {
        const result = resolveMode({
            ...base,
            singleExecFlagOn: true,
            clientProfile: profile({ clientName: 'some-dashboard-client' }),
        })
        expect(result.useSingleExec).toBe(false)
    })

    it('flag on + PostHog code consumer activates single exec', () => {
        const result = resolveMode({
            ...base,
            singleExecFlagOn: true,
            clientProfile: profile({ consumer: 'posthog-code' }),
        })
        expect(result.useSingleExec).toBe(true)
    })
})
