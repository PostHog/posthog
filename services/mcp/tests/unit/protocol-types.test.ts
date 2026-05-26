import { describe, expect, it } from 'vitest'

import { MCPClientProfile } from '@/lib/client-detection'
import { resolveModeAndVersion } from '@/hono/request-state-resolver'

describe('resolveModeAndVersion', () => {
    function profile(overrides: Partial<ConstructorParameters<typeof MCPClientProfile>[0]> = {}): MCPClientProfile {
        return new MCPClientProfile({ clientName: 'generic-client', ...overrides })
    }

    const base = {
        mode: undefined as undefined,
        clientProfile: profile(),
        flagVersion: undefined as number | undefined,
        clientVersion: undefined as number | undefined,
    }

    it('defaults to version 1, no single exec', () => {
        expect(resolveModeAndVersion(base)).toEqual({ useSingleExec: false, version: 1 })
    })

    it('explicit mode=cli forces single exec and version 2', () => {
        expect(resolveModeAndVersion({ ...base, mode: 'cli' })).toEqual({
            useSingleExec: true,
            version: 2,
        })
    })

    it('explicit mode=tools disables single exec even for a coding agent', () => {
        const result = resolveModeAndVersion({
            ...base,
            mode: 'tools',
            clientProfile: profile({ clientName: 'claude-code' }),
        })
        expect(result.useSingleExec).toBe(false)
    })

    it('coding agent activates single exec', () => {
        const result = resolveModeAndVersion({
            ...base,
            clientProfile: profile({ clientName: 'claude-code' }),
        })
        expect(result).toEqual({ useSingleExec: true, version: 2 })
    })

    it('non-coding agent does NOT activate single exec', () => {
        const result = resolveModeAndVersion({
            ...base,
            clientProfile: profile({ clientName: 'some-dashboard-client' }),
        })
        expect(result.useSingleExec).toBe(false)
    })

    it('PostHog code consumer activates single exec', () => {
        const result = resolveModeAndVersion({
            ...base,
            clientProfile: profile({ consumer: 'posthog-code' }),
        })
        expect(result.useSingleExec).toBe(true)
    })

    it('uses flagVersion when not in single exec mode', () => {
        const result = resolveModeAndVersion({ ...base, flagVersion: 2 })
        expect(result).toEqual({ useSingleExec: false, version: 2 })
    })

    it('clientVersion overrides default when no flagVersion', () => {
        const result = resolveModeAndVersion({ ...base, clientVersion: 2 })
        expect(result).toEqual({ useSingleExec: false, version: 2 })
    })

    it('flagVersion takes precedence over clientVersion', () => {
        const result = resolveModeAndVersion({ ...base, flagVersion: 2, clientVersion: 1 })
        expect(result.version).toBe(2)
    })

    it('single exec always forces version 2 regardless of flagVersion', () => {
        const result = resolveModeAndVersion({ ...base, mode: 'cli', flagVersion: 1 })
        expect(result).toEqual({ useSingleExec: true, version: 2 })
    })
})
