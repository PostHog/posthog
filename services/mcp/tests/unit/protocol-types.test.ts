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

    it('defaults to cli mode (single exec) for unknown clients', () => {
        expect(resolveMode(base)).toEqual({ mode: 'cli', useSingleExec: true })
    })

    it('defaults to cli mode when no client hints are present at all', () => {
        expect(resolveMode({ mode: undefined, clientProfile: new MCPClientProfile({}) })).toEqual({
            mode: 'cli',
            useSingleExec: true,
        })
    })

    const cursorByName = profile({ clientName: 'cursor' })
    const cursorByUserAgent = profile({ clientName: undefined, userAgent: 'Cursor/3.1.15 (darwin arm64)' })

    it.each([
        ['Cursor client name', cursorByName],
        ['name-less Cursor user-agent', cursorByUserAgent],
    ])('auto-selects tools mode for the %s', (_label, clientProfile) => {
        expect(resolveMode({ mode: undefined, clientProfile })).toEqual({ mode: 'tools', useSingleExec: false })
    })

    it.each([
        ['Cursor client name', cursorByName],
        ['name-less Cursor user-agent', cursorByUserAgent],
    ])('keeps the %s on the cli default when Cursor exec mode is on', (_label, clientProfile) => {
        expect(resolveMode({ mode: undefined, clientProfile, cursorExecMode: true })).toEqual({
            mode: 'cli',
            useSingleExec: true,
        })
    })

    it('explicit mode=tools wins over Cursor exec mode', () => {
        expect(resolveMode({ mode: 'tools', clientProfile: cursorByName, cursorExecMode: true })).toEqual({
            mode: 'tools',
            useSingleExec: false,
        })
    })

    it('explicit mode=cli forces single exec', () => {
        expect(resolveMode({ ...base, mode: 'cli' })).toEqual({ mode: 'cli', useSingleExec: true })
    })

    it('explicit mode=cli wins over the Cursor tools-mode auto-detection', () => {
        const result = resolveMode({ mode: 'cli', clientProfile: profile({ clientName: 'cursor' }) })
        expect(result).toEqual({ mode: 'cli', useSingleExec: true })
    })

    it('explicit mode=tools disables single exec for a client that would default to cli', () => {
        expect(resolveMode({ ...base, mode: 'tools' })).toEqual({ mode: 'tools', useSingleExec: false })
    })
})
