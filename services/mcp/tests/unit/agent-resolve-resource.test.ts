import { readdirSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

import { AgentResolveResourceSchema } from '@/schema/tool-inputs'
import { PLAYBOOK_IDS, PLAYBOOK_URI_PREFIX, playbookUri } from '@/tools/agentPlatform/playbookIds'
import { PLAYBOOKS } from '@/tools/agentPlatform/playbooks'
import { buildToolSurface, PLAYBOOK_TOOLS } from '@/tools/agentPlatform/playbookTools'
import { resolveResourceHandler } from '@/tools/agentPlatform/resolveResource'
import { getToolDefinitions } from '@/tools/toolDefinitions'
import type { Context } from '@/tools/types'

// Canonical source: the MCP builder-playbooks dir (one `<id>/SKILL.md` per
// playbook). The build copies these into shared/playbooks/ (embedded) — both
// must stay in lockstep with PLAYBOOK_IDS.
const PLAYBOOKS_DIR = resolve(__dirname, '../../playbooks')

// Context whose api key carries the given scopes (drives the live tool surface).
const ctxWithScopes = (scopes: string[]): Context =>
    ({ stateManager: { getApiKey: async () => ({ scopes }) } }) as unknown as Context
// No stateManager → getApiKey throws → handler renders the flat (scope-unknown) surface.
const ctx = {} as Context

describe('agent-resolve-resource', () => {
    describe('AgentResolveResourceSchema', () => {
        it('accepts a bare playbook id', () => {
            expect(AgentResolveResourceSchema.safeParse({ resource: 'editing-agents-safely' }).success).toBe(true)
        })

        it('accepts a full resource URI', () => {
            const uri = `${PLAYBOOK_URI_PREFIX}editing-agents-safely`
            expect(AgentResolveResourceSchema.safeParse({ resource: uri }).success).toBe(true)
        })

        it('rejects a missing / non-string resource', () => {
            expect(AgentResolveResourceSchema.safeParse({}).success).toBe(false)
            expect(AgentResolveResourceSchema.safeParse({ resource: 5 }).success).toBe(false)
        })
    })

    describe('resolveResourceHandler', () => {
        it('returns id, uri, title and markdown content for a bare id', async () => {
            const result = await resolveResourceHandler(ctx, { resource: 'debugging-sessions' })
            expect(result.id).toBe('debugging-sessions')
            expect(result.uri).toBe(`${PLAYBOOK_URI_PREFIX}debugging-sessions`)
            expect(result.title.length).toBeGreaterThan(0)
            expect(result.content.length).toBeGreaterThan(100)
        })

        it('resolves the same playbook whether passed an id or its URI', async () => {
            const byId = await resolveResourceHandler(ctx, { resource: 'reading-an-agent' })
            const byUri = await resolveResourceHandler(ctx, { resource: playbookUri('reading-an-agent') })
            expect(byUri).toEqual(byId)
        })

        it('throws a helpful error on an unknown reference', async () => {
            await expect(resolveResourceHandler(ctx, { resource: 'does-not-exist' })).rejects.toThrow(
                /Unknown playbook/
            )
        })
    })

    describe('playbook inventory', () => {
        it('PLAYBOOK_IDS matches the dirs in the MCP playbooks source', () => {
            const playbookDirs = readdirSync(PLAYBOOKS_DIR, { withFileTypes: true })
                .filter((e) => e.isDirectory())
                .map((e) => e.name)
                .sort()
            expect(playbookDirs).toEqual([...PLAYBOOK_IDS].sort())
        })

        it('every id has embedded, non-empty content', () => {
            for (const id of PLAYBOOK_IDS) {
                expect(PLAYBOOKS[id]?.content.length, id).toBeGreaterThan(100)
            }
        })
    })

    describe('live tool surface', () => {
        it('every tool named in PLAYBOOK_TOOLS resolves to a real tool definition', () => {
            const defs = getToolDefinitions()
            for (const [id, names] of Object.entries(PLAYBOOK_TOOLS)) {
                for (const name of names) {
                    expect(defs[name], `${id} → ${name}`).not.toBeUndefined()
                }
            }
        })

        it('drops tool names absent from the live catalog without throwing', () => {
            // Only one of authoring-new-agents' tools exists in this partial
            // catalog — the rest are silently skipped (ground-truth wins).
            const partial = {
                'agent-applications-create': { title: 'Create', required_scopes: ['agents:write'] },
            } as unknown as Parameters<typeof buildToolSurface>[2]
            const refs = buildToolSurface('authoring-new-agents', ['*'], partial)
            expect(refs.map((r) => r.name)).toEqual(['agent-applications-create'])
        })

        it('classifies the no-source creator as gated without agents:write, callable with it', () => {
            const readOnly = buildToolSurface('authoring-new-agents', ['agents:read'])
            const create = readOnly.find((t) => t.name === 'agent-applications-revisions-create')!
            expect(create.missingScopes).toEqual(['agents:write'])

            const writer = buildToolSurface('authoring-new-agents', ['agents:write'])
            expect(writer.find((t) => t.name === 'agent-applications-revisions-create')!.missingScopes).toEqual([])

            // all-access wildcard satisfies everything
            const star = buildToolSurface('authoring-new-agents', ['*'])
            expect(star.every((t) => t.missingScopes.length === 0)).toBe(true)
        })

        it('appends a scope-aware surface to the returned content', async () => {
            const result = await resolveResourceHandler(ctxWithScopes(['agents:read']), {
                resource: 'authoring-new-agents',
            })
            expect(result.content).toContain('## Tools for this playbook (live)')
            // The creator agents keep "not finding" is named, and shown as scope-gated.
            expect(result.content).toMatch(/agent-applications-revisions-create.*needs: agents:write/)
            expect(result.tools.gated).toContain('agent-applications-revisions-create')
            expect(result.tools.gated).toContain('agent-applications-create') // create needs agents:write
            // a read-scoped tool stays callable under agents:read
            expect(result.tools.callable).toContain('agent-native-tools-list')
        })

        it('with agents:write the creator moves into the callable set', async () => {
            const result = await resolveResourceHandler(ctxWithScopes(['agents:write']), {
                resource: 'authoring-new-agents',
            })
            expect(result.tools.callable).toContain('agent-applications-revisions-create')
            expect(result.tools.gated).not.toContain('agent-applications-revisions-create')
        })

        it('playbooks with no associated tools omit the surface section', async () => {
            const result = await resolveResourceHandler(ctxWithScopes(['*']), { resource: 'platform-mental-model' })
            expect(result.content).not.toContain('Tools for this playbook')
            expect(result.tools.callable).toHaveLength(0)
            expect(result.tools.gated).toHaveLength(0)
        })
    })
})
