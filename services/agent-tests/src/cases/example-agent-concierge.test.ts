/**
 * Example bundle wiring check — `services/agent-tests/src/examples/agent-concierge/`.
 *
 * Post-PR-7: the concierge spec now uses the platform's discriminated
 * `McpRefSchema` shape (`kind: 'external'`, `tools[]` carrying inline
 * `requires_approval` + `approval_policy`). `seed.py` no longer strips
 * `mcps[]`, so the bundle deploys end-to-end. This case still pins the
 * wiring net (skill paths exist, MCP tools match the authoring MCP
 * catalog, approval gating intact on destructive tools) — drift here
 * means the bundle is broken regardless of platform readiness, so it's
 * worth catching before review.
 */

import { readdir, readFile } from 'node:fs/promises'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import { AgentSpecSchema } from '@posthog/agent-shared'

const __dirname = dirname(fileURLToPath(import.meta.url))
const BUNDLE_ROOT = resolve(__dirname, '../examples/agent-concierge')
const AGENT_STACK_YAML = resolve(__dirname, '../../../mcp/definitions/agent_platform.yaml')

type ConciergeMcpToolEntry =
    | string
    | {
          name: string
          requires_approval?: boolean
          approval_policy?: { approvers: string[]; ttl_ms?: number }
      }

type ConciergeMcpRef =
    | { kind: 'agent'; slug: string }
    | {
          kind: 'external'
          id: string
          url: string
          secrets?: string[]
          tools?: ConciergeMcpToolEntry[]
      }

interface ConciergeSpec {
    model: string
    triggers: Array<{ type: string }>
    tools: Array<{
        kind: string
        id?: string
        from_native?: string
        description?: string
        args_schema?: Record<string, unknown>
        required?: boolean
        timeout_ms?: number
    }>
    mcps: ConciergeMcpRef[]
    skills: Array<{ id: string; path: string; description: string }>
    integrations: string[]
    secrets: string[]
    limits: { max_turns: number; max_tool_calls: number; max_wall_seconds: number }
    auth: {
        modes?: Array<Record<string, unknown> & { type: string }>
    }
    reasoning?: string
    resume?: { enabled: boolean; max_completed_age_ms: number }
}

function toolEntryName(entry: ConciergeMcpToolEntry): string {
    return typeof entry === 'string' ? entry : entry.name
}

async function loadBundle(): Promise<{ spec: ConciergeSpec; files: Record<string, string> }> {
    const spec = JSON.parse(await readFile(join(BUNDLE_ROOT, 'spec.json'), 'utf-8')) as ConciergeSpec
    const files: Record<string, string> = {}
    files['agent.md'] = await readFile(join(BUNDLE_ROOT, 'agent.md'), 'utf-8')
    files['README.md'] = await readFile(join(BUNDLE_ROOT, 'README.md'), 'utf-8')
    const skillFiles = await readdir(join(BUNDLE_ROOT, 'skills'))
    for (const sf of skillFiles) {
        files[`skills/${sf}`] = await readFile(join(BUNDLE_ROOT, 'skills', sf), 'utf-8')
    }
    return { spec, files }
}

async function loadAgentPlatformToolIds(): Promise<Set<string>> {
    // The yaml has shape `tools:\n    foo-bar:\n        operation: ...`.
    // Pulling the tool keys with a regex is cheaper than adding a yaml dep
    // for one assertion — the keys are stable, indented exactly 4 spaces.
    const raw = await readFile(AGENT_STACK_YAML, 'utf-8')
    const matches = raw.matchAll(/^ {4}([a-z][a-z0-9-]+):$/gm)
    return new Set(Array.from(matches, (m) => m[1]))
}

describe('example: agent-concierge bundle', () => {
    it('every skill path in spec.skills[] exists as a bundle file', async () => {
        const { spec, files } = await loadBundle()
        for (const skill of spec.skills) {
            expect(files[skill.path]).not.toBeUndefined()
            // Each skill description is the only signal the model gets for
            // when to load it — guard against empty / placeholder descriptions.
            expect(skill.description).toBeTruthy()
            expect(skill.description.length).toBeGreaterThan(30)
        }
    })

    it('agent.md is present and non-trivial', async () => {
        const { files } = await loadBundle()
        expect(files['agent.md']).not.toBeUndefined()
        // The concierge agent.md is intentionally short (defers to skills) but
        // not THIS short. <500 chars means something got truncated.
        expect(files['agent.md'].length).toBeGreaterThan(500)
    })

    it('every MCP tool the concierge declares matches the authoring MCP catalog', async () => {
        const { spec } = await loadBundle()
        const catalog = await loadAgentPlatformToolIds()
        const posthog = spec.mcps.find((m): m is Extract<ConciergeMcpRef, { kind: 'external' }> => {
            return m.kind === 'external' && m.id === 'posthog'
        })
        expect(posthog).toBeTruthy()
        for (const entry of posthog!.tools ?? []) {
            expect(catalog.has(toolEntryName(entry))).toBe(true)
        }
    })

    it('declares both chat and mcp triggers (the two production surfaces)', async () => {
        const { spec } = await loadBundle()
        const triggerTypes = spec.triggers.map((t) => t.type)
        expect(triggerTypes).toContain('chat')
        expect(triggerTypes).toContain('mcp')
    })

    it('declares the client tools the agent-console implements', async () => {
        const { spec } = await loadBundle()
        // Author-defined inline shape (id, description, args_schema) —
        // the platform doesn't ship a registry of well-known UI tools.
        // Console dock's handlers register against these ids; runner
        // dispatches via the bus + ingress POST round-trip.
        const clientTools = spec.tools.filter((t) => t.kind === 'client')
        const ids = clientTools.map((t) => t.id).sort()
        expect(ids).toEqual([
            'focus_file',
            'focus_revision',
            'focus_session',
            'focus_spec_section',
            'focus_tab',
            'get_context',
            'set_secret',
            'toast',
        ])
        for (const t of clientTools) {
            expect(t.id, `${t.id}: id`).toBeTruthy()
            expect(t.description, `${t.id}: description`).toBeTruthy()
            expect((t.description ?? '').length, `${t.id}: description length`).toBeGreaterThan(40)
            expect(t.args_schema, `${t.id}: args_schema`).toBeTruthy()
            expect(typeof t.args_schema, `${t.id}: args_schema is object`).toBe('object')
        }
    })

    it('accepts oauth + pat + posthog_internal on the same revision', async () => {
        const { spec } = await loadBundle()
        // Shared deployment serves console (posthog_internal), MCP clients
        // (oauth), and scripted access (pat). Each mode is a discriminated
        // variant in the new `auth.modes[]` shape.
        const modeTypes = (spec.auth.modes ?? []).map((m) => m.type)
        expect(modeTypes).toEqual(expect.arrayContaining(['oauth', 'pat', 'posthog_internal']))
        const oauthMode = (spec.auth.modes ?? []).find((m) => m.type === 'oauth')
        expect(oauthMode?.issuer).toBe('posthog')
    })

    it('enables resume so multi-step flows can span days', async () => {
        const { spec } = await loadBundle()
        // Real edit-debug flows are multi-turn over hours. Default 24h sweep
        // would close them mid-thought.
        expect(spec.resume?.enabled).toBe(true)
        expect(spec.resume?.max_completed_age_ms).toBeGreaterThanOrEqual(7 * 24 * 60 * 60 * 1000)
    })

    it('declares approval policies for destructive MCP tools', async () => {
        const { spec } = await loadBundle()
        // Promote / set-env / destroy are gated at the platform layer, not just
        // in the prompt. Post-PR-7 the gating lives inline on `tools[]` object
        // entries with `requires_approval: true` + `approval_policy.approvers`.
        const posthog = spec.mcps.find((m): m is Extract<ConciergeMcpRef, { kind: 'external' }> => {
            return m.kind === 'external' && m.id === 'posthog'
        })
        expect(posthog).toBeTruthy()
        const gatedNames = new Set(
            (posthog!.tools ?? [])
                .filter(
                    (e): e is Exclude<ConciergeMcpToolEntry, string> =>
                        typeof e === 'object' && e.requires_approval === true
                )
                .map((e) => e.name)
        )
        for (const required of [
            'agent-applications-revisions-promote-create',
            'agent-applications-set-env-create',
            'agent-applications-destroy',
        ]) {
            expect(gatedNames.has(required), `${required} should be gated`).toBe(true)
        }
        // session_principal — the concierge wires every gated tool to the
        // session owner via the per-asker fast-path (decision B1 + C1 in the
        // PR 7 plan).
        for (const entry of posthog!.tools ?? []) {
            if (typeof entry === 'object' && entry.requires_approval) {
                expect(entry.approval_policy?.approvers).toEqual(['session_principal'])
            }
        }
    })

    it('every bundle/tests/*.json case parses and declares the required fields', async () => {
        const testsDir = join(BUNDLE_ROOT, 'tests')
        const entries = await readdir(testsDir)
        const jsonFiles = entries.filter((f) => f.endsWith('.json'))
        // Insurance against a future commit dropping all the cases by mistake.
        expect(jsonFiles.length).toBeGreaterThanOrEqual(5)
        for (const f of jsonFiles) {
            const body = JSON.parse(await readFile(join(testsDir, f), 'utf-8')) as {
                name?: string
                description?: string
                trigger?: { type: string; messages?: Array<{ role: string; content: string }> }
                expected?: Record<string, unknown>
            }
            expect(body.name, `${f}: name`).toBeTruthy()
            expect(body.description, `${f}: description`).toBeTruthy()
            expect(body.trigger?.type, `${f}: trigger.type`).toBeTruthy()
            expect(body.expected, `${f}: expected`).toBeTruthy()
        }
    })

    it('the spec parses through AgentSpecSchema — runner accepts it as-is', async () => {
        // The runner reads `revision.spec` via zod. Before PR 7 the
        // concierge spec couldn't be deployed because `seed.py` had to
        // strip `mcps[]` (the flat shape pre-dated the runtime-mcps
        // schema). After PR 7 the spec uses `kind: 'external'` +
        // `tools[]` and parses cleanly — this assertion pins that contract
        // so a future schema tightening doesn't silently re-break the
        // bundle.
        const { spec } = await loadBundle()
        const parsed = AgentSpecSchema.parse(spec)
        expect(parsed.mcps).toHaveLength(1)
        const posthog = parsed.mcps[0]
        if (posthog.kind !== 'external') {
            throw new Error('expected external posthog mcp')
        }
        // Spot-check that the destructive entries arrived as object form
        // with their approval policy populated.
        const promote = posthog.tools?.find(
            (t): t is Exclude<typeof t, string> =>
                typeof t === 'object' && t.name === 'agent-applications-revisions-promote-create'
        )
        expect(promote).not.toBeUndefined()
        expect(promote!.requires_approval).toBe(true)
        expect(promote!.approval_policy.approvers).toEqual(['session_principal'])
        expect(promote!.approval_policy.ttl_ms).toBe(900_000)
    })

    it('seed.py script exists and is executable as Python', async () => {
        const scriptPath = join(BUNDLE_ROOT, 'scripts', 'seed.py')
        const src = await readFile(scriptPath, 'utf-8')
        // Two things that would silently break the deploy if removed:
        // - shebang for direct exec
        // - per_file_sha256 powers the no-op idempotency check
        // PR 7 removed the `spec["mcps"] = []` strip — the bundle now ships
        // `mcps[]` in the discriminated union shape the platform accepts.
        expect(src.startsWith('#!/usr/bin/env python3')).toBe(true)
        expect(src).toContain('def load_v0_spec()')
        expect(src).toContain('def per_file_sha256(')
        expect(src).not.toContain('spec["mcps"] = []')
    })
})
