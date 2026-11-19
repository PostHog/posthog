import { describe, expect, it } from 'vitest'

import { resolveMode, resolveSplitWrites } from '@/hono/request-state-resolver'
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

describe('resolveSplitWrites', () => {
    const base = {
        useSingleExec: true,
        readOnly: false,
        requested: undefined,
        flagEnabled: false,
        clientProfile: new MCPClientProfile({ clientName: 'claude-ai' }),
    }

    // Wrappers that send a consumer gate writes on the `exec` name, so the flag must not move writes out from under them.
    it.each([
        ['off by default', {}, false],
        ['on when the connection asks for it', { requested: true }, true],
        ['on with the rollout flag', { flagEnabled: true }, true],
        ['off when the connection declines it, flag or not', { requested: false, flagEnabled: true }, false],
        [
            'off for the posthog-code consumer under the flag',
            { flagEnabled: true, clientProfile: new MCPClientProfile({ consumer: 'posthog-code' }) },
            false,
        ],
        [
            'off for the plugin consumer under the flag',
            { flagEnabled: true, clientProfile: new MCPClientProfile({ consumer: 'plugin' }) },
            false,
        ],
        [
            'off for the slack consumer under the flag',
            { flagEnabled: true, clientProfile: new MCPClientProfile({ consumer: 'slack' }) },
            false,
        ],
        [
            'on for the AI plugin when it asks',
            { requested: true, clientProfile: new MCPClientProfile({ consumer: 'plugin' }) },
            true,
        ],
        ['off in tools mode, which names every tool already', { requested: true, useSingleExec: false }, false],
        ['off on a read-only connection, which has no writes', { requested: true, readOnly: true }, false],
    ])('is %s', (_label, overrides, expected) => {
        expect(resolveSplitWrites({ ...base, ...overrides })).toBe(expected)
    })
})
