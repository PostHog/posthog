import { describe, expect, it } from 'vitest'

import { MCPClientProfile } from '@/lib/client-detection'
import { isRequest, jsonRpcError, resolveModeAndVersion } from '@/hono/protocol-types'

describe('isRequest', () => {
    it('returns true when message has an id', () => {
        expect(isRequest({ jsonrpc: '2.0', id: 1, method: 'ping' })).toBe(true)
    })

    it('returns false for notifications (no id)', () => {
        expect(isRequest({ jsonrpc: '2.0', method: 'notifications/initialized' })).toBe(false)
    })
})

describe('jsonRpcError', () => {
    it('returns a 200 Response with the error payload', async () => {
        const resp = jsonRpcError(42, -32600, 'Invalid request')
        expect(resp.status).toBe(200)
        expect(resp.headers.get('Content-Type')).toBe('application/json')
        const body = await resp.json()
        expect(body).toEqual({
            jsonrpc: '2.0',
            id: 42,
            error: { code: -32600, message: 'Invalid request' },
        })
    })

    it('uses null id when none provided', async () => {
        const body = await jsonRpcError(null, -32700, 'Parse error').json()
        expect(body.id).toBeNull()
    })
})

describe('resolveModeAndVersion', () => {
    function profile(overrides: Partial<ConstructorParameters<typeof MCPClientProfile>[0]> = {}): MCPClientProfile {
        return new MCPClientProfile({ clientName: 'generic-client', ...overrides })
    }

    const base = {
        mode: undefined as undefined,
        singleExecFlagOn: false,
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

    it('explicit mode=tools disables single exec even when flag is on for a coding agent', () => {
        const result = resolveModeAndVersion({
            ...base,
            mode: 'tools',
            singleExecFlagOn: true,
            clientProfile: profile({ clientName: 'claude-code' }),
        })
        expect(result.useSingleExec).toBe(false)
    })

    it('coding agent with flag on activates single exec', () => {
        const result = resolveModeAndVersion({
            ...base,
            singleExecFlagOn: true,
            clientProfile: profile({ clientName: 'claude-code' }),
        })
        expect(result).toEqual({ useSingleExec: true, version: 2 })
    })

    it('non-coding agent with flag on does NOT activate single exec', () => {
        const result = resolveModeAndVersion({
            ...base,
            singleExecFlagOn: true,
            clientProfile: profile({ clientName: 'some-dashboard-client' }),
        })
        expect(result.useSingleExec).toBe(false)
    })

    it('flag on + PostHog code consumer activates single exec', () => {
        const result = resolveModeAndVersion({
            ...base,
            singleExecFlagOn: true,
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
