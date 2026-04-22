import type { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js'
import { strToU8, zipSync } from 'fflate'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { type FlagGated, shouldIncludeByFlag } from '@/lib/feature-flag-gating'
import { loadContextMillManifest } from '@/resources/manifest-loader'
import type { Context } from '@/tools/types'

// POSTHOG_MCP_LOCAL_SKILLS_URL isn't declared on Env; the production code reads
// it via a Record cast in fetchContextMillResources. Tests mirror that.
const testEnv = { POSTHOG_MCP_LOCAL_SKILLS_URL: 'http://localhost/test-skills.zip' } as unknown as Context['env']
const testContext = { env: testEnv } as unknown as Context

function fakeServerRecording(registered: string[]): McpServer {
    return { registerResource: (name: string) => registered.push(name) } as unknown as McpServer
}

describe('shouldIncludeByFlag', () => {
    it('always includes entries without a feature_flag', () => {
        expect(shouldIncludeByFlag({})).toBe(true)
        expect(shouldIncludeByFlag({}, { 'any-flag': true })).toBe(true)
        expect(shouldIncludeByFlag({}, {})).toBe(true)
    })

    describe("with feature_flag_behavior 'enable' (default)", () => {
        const entry: FlagGated = { feature_flag: 'flag-x' }

        it('includes when flag is on', () => {
            expect(shouldIncludeByFlag(entry, { 'flag-x': true })).toBe(true)
        })

        it('excludes when flag is off', () => {
            expect(shouldIncludeByFlag(entry, { 'flag-x': false })).toBe(false)
        })

        it('excludes when flag is missing from map', () => {
            expect(shouldIncludeByFlag(entry, {})).toBe(false)
        })

        it('excludes when featureFlags is undefined', () => {
            expect(shouldIncludeByFlag(entry, undefined)).toBe(false)
        })
    })

    describe("with feature_flag_behavior 'disable'", () => {
        const entry: FlagGated = { feature_flag: 'flag-sunset', feature_flag_behavior: 'disable' }

        it('excludes when flag is on', () => {
            expect(shouldIncludeByFlag(entry, { 'flag-sunset': true })).toBe(false)
        })

        it('includes when flag is off', () => {
            expect(shouldIncludeByFlag(entry, { 'flag-sunset': false })).toBe(true)
        })

        it('includes when flag is missing from map', () => {
            expect(shouldIncludeByFlag(entry, {})).toBe(true)
        })

        it('includes when featureFlags is undefined', () => {
            expect(shouldIncludeByFlag(entry, undefined)).toBe(true)
        })
    })

    it('supports atomic swap of two entries keyed off the same flag', () => {
        const oldEntry: FlagGated = { feature_flag: 'flag-exp', feature_flag_behavior: 'disable' }
        const newEntry: FlagGated = { feature_flag: 'flag-exp' }

        // Flag on: new wins, old hidden
        expect(shouldIncludeByFlag(oldEntry, { 'flag-exp': true })).toBe(false)
        expect(shouldIncludeByFlag(newEntry, { 'flag-exp': true })).toBe(true)

        // Flag off: old wins, new hidden
        expect(shouldIncludeByFlag(oldEntry, { 'flag-exp': false })).toBe(true)
        expect(shouldIncludeByFlag(newEntry, { 'flag-exp': false })).toBe(false)
    })
})

function buildArchiveZip(resources: unknown[]): ArrayBuffer {
    const manifest = { version: '1.0', resources }
    const files: Record<string, Uint8Array> = {
        'manifest.json': strToU8(JSON.stringify(manifest)),
    }
    for (const res of resources as Array<{ file?: string }>) {
        if (res.file) {
            files[res.file] = strToU8('body')
        }
    }
    const zipped = zipSync(files)
    const buf = new ArrayBuffer(zipped.byteLength)
    new Uint8Array(buf).set(zipped)
    return buf
}

function mockFetchOnceWithZip(archive: ArrayBuffer): void {
    vi.stubGlobal(
        'fetch',
        vi.fn().mockResolvedValue({
            ok: true,
            arrayBuffer: async () => archive,
            statusText: 'OK',
        } as unknown as Response)
    )
}

describe('getRequiredSkillFlags', () => {
    beforeEach(async () => {
        vi.resetModules()
    })

    afterEach(() => {
        vi.unstubAllGlobals()
    })

    it('returns union of declared flag keys', async () => {
        mockFetchOnceWithZip(
            buildArchiveZip([
                makeResource('r1', { feature_flag: 'flag-a' }),
                makeResource('r2', { feature_flag: 'flag-b' }),
                makeResource('r3', { feature_flag: 'flag-a' }),
                makeResource('r4'), // no flag
            ])
        )
        const { getRequiredSkillFlags } = await import('@/resources')
        const flags = await getRequiredSkillFlags(testEnv)
        expect(flags.sort()).toEqual(['flag-a', 'flag-b'])
    })

    it('returns empty array when no resources declare flags', async () => {
        mockFetchOnceWithZip(buildArchiveZip([makeResource('r1'), makeResource('r2')]))
        const { getRequiredSkillFlags } = await import('@/resources')
        expect(await getRequiredSkillFlags(testEnv)).toEqual([])
    })

    it('returns empty array on manifest fetch failure (never throws)', async () => {
        vi.stubGlobal(
            'fetch',
            vi.fn().mockResolvedValue({
                ok: false,
                arrayBuffer: async () => new ArrayBuffer(0),
                statusText: 'Not Found',
            } as unknown as Response)
        )
        const { getRequiredSkillFlags } = await import('@/resources')
        expect(await getRequiredSkillFlags(testEnv)).toEqual([])
    })
})

describe('registerResources flag filtering', () => {
    beforeEach(async () => {
        vi.resetModules()
    })

    afterEach(() => {
        vi.unstubAllGlobals()
    })

    it('skips resources whose flag gate is off', async () => {
        mockFetchOnceWithZip(
            buildArchiveZip([
                makeResource('always'),
                makeResource('gated-on', { feature_flag: 'flag-on' }),
                makeResource('gated-off', { feature_flag: 'flag-off' }),
            ])
        )

        const registered: string[] = []
        const { registerResources } = await import('@/resources')
        await registerResources(fakeServerRecording(registered), testContext, {
            'flag-on': true,
            'flag-off': false,
        })

        expect(registered).toContain('always')
        expect(registered).toContain('gated-on')
        expect(registered).not.toContain('gated-off')
    })

    it('supports atomic swap of a pair of resources on the same flag', async () => {
        mockFetchOnceWithZip(
            buildArchiveZip([
                makeResource('old', { feature_flag: 'flag-exp', feature_flag_behavior: 'disable' }),
                makeResource('new', { feature_flag: 'flag-exp' }),
                makeResource('neutral'),
            ])
        )

        const { registerResources } = await import('@/resources')

        const registeredOn: string[] = []
        await registerResources(fakeServerRecording(registeredOn), testContext, {
            'flag-exp': true,
        })
        expect(registeredOn.sort()).toEqual(['neutral', 'new'])

        const registeredOff: string[] = []
        await registerResources(fakeServerRecording(registeredOff), testContext, {
            'flag-exp': false,
        })
        expect(registeredOff.sort()).toEqual(['neutral', 'old'])
    })

    it('registers unflagged resources when featureFlags is undefined', async () => {
        mockFetchOnceWithZip(
            buildArchiveZip([makeResource('plain'), makeResource('gated', { feature_flag: 'flag-x' })])
        )

        const registered: string[] = []
        const { registerResources } = await import('@/resources')
        await registerResources(fakeServerRecording(registered), testContext)

        expect(registered).toContain('plain')
        expect(registered).not.toContain('gated')
    })
})

function makeResource(
    id: string,
    extras: { feature_flag?: string | null; feature_flag_behavior?: 'enable' | 'disable' | string } = {}
): Record<string, unknown> {
    return {
        id,
        name: id,
        uri: `posthog://${id}`,
        resource: {
            mimeType: 'text/markdown',
            description: `${id} description`,
            text: `# ${id}`,
        },
        ...extras,
    }
}

describe('loadContextMillManifest flag validation', () => {
    function buildManifest(resource: Record<string, unknown>): unknown {
        return { version: '1.0', resources: [resource] }
    }

    it('rejects feature_flag_behavior without feature_flag', () => {
        expect(() =>
            loadContextMillManifest(buildManifest(makeResource('r1', { feature_flag_behavior: 'enable' })))
        ).toThrow(/"feature_flag_behavior" but no "feature_flag"/)
    })

    it('rejects empty-string feature_flag', () => {
        expect(() => loadContextMillManifest(buildManifest(makeResource('r1', { feature_flag: '' })))).toThrow(
            /invalid flag fields/
        )
    })

    it('rejects whitespace-only feature_flag', () => {
        expect(() => loadContextMillManifest(buildManifest(makeResource('r1', { feature_flag: '   ' })))).toThrow(
            /invalid flag fields/
        )
    })

    it('rejects invalid feature_flag_behavior value', () => {
        expect(() =>
            loadContextMillManifest(
                buildManifest(makeResource('r1', { feature_flag: 'flag-x', feature_flag_behavior: 'on' }))
            )
        ).toThrow(/invalid flag fields/)
    })

    it('accepts valid flag + behavior', () => {
        expect(() =>
            loadContextMillManifest(
                buildManifest(makeResource('r1', { feature_flag: 'flag-x', feature_flag_behavior: 'disable' }))
            )
        ).not.toThrow()
    })

    it('accepts flag without behavior (defaults to enable)', () => {
        expect(() =>
            loadContextMillManifest(buildManifest(makeResource('r1', { feature_flag: 'flag-x' })))
        ).not.toThrow()
    })
})
