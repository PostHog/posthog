/**
 * Example bundle wiring check — `services/agent-tests/src/examples/agent-concierge/`.
 *
 * The concierge authors + operates other agents entirely through native
 * `@posthog/agent-applications-*` tools — there is NO external MCP server
 * in `spec.mcps[]` (removed so a transient MCP outage can't strip the
 * agent's write path). Destructive native tools (`promote`, `archive`)
 * carry inline `requires_approval` + `approval_policy` so the platform —
 * not just the prompt — gates them. This case pins the wiring net (skill
 * paths exist, no MCP server, native tools resolve, approval gating
 * intact) — drift here means the bundle is broken regardless of platform
 * readiness, so it's worth catching before review.
 */

import { readdir, readFile } from 'node:fs/promises'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import { AgentSpecSchema } from '@posthog/agent-shared'
import { listNativeTools } from '@posthog/agent-tools'

const __dirname = dirname(fileURLToPath(import.meta.url))
const BUNDLE_ROOT = resolve(__dirname, '../examples/agent-concierge')

interface ConciergeSpec {
    model: string
    triggers: Array<{
        type: string
        config?: { name?: string; prompt?: string; [k: string]: unknown }
        auth?: { modes?: Array<{ type: string }> }
    }>
    tools: Array<{
        kind: string
        id?: string
        from_native?: string
        description?: string
        args_schema?: Record<string, unknown>
        required?: boolean
        timeout_ms?: number
        requires_approval?: boolean
        approval_policy?: { approvers: string[]; ttl_ms?: number }
    }>
    mcps: unknown[]
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

async function loadBundle(): Promise<{ spec: ConciergeSpec; files: Record<string, string> }> {
    const spec = JSON.parse(await readFile(join(BUNDLE_ROOT, 'spec.json'), 'utf-8')) as ConciergeSpec
    const files: Record<string, string> = {}
    files['agent.md'] = await readFile(join(BUNDLE_ROOT, 'agent.md'), 'utf-8')
    files['README.md'] = await readFile(join(BUNDLE_ROOT, 'README.md'), 'utf-8')
    const skillDirs = await readdir(join(BUNDLE_ROOT, 'skills'))
    for (const id of skillDirs) {
        const p = `skills/${id}/SKILL.md`
        files[p] = await readFile(join(BUNDLE_ROOT, p), 'utf-8')
    }
    return { spec, files }
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

    it('declares no external MCP server and every native tool resolves in the native catalog', async () => {
        const { spec } = await loadBundle()
        // The concierge authors via native tools only — no MCP server, so a
        // transient MCP outage can never strip its write path (the bug this
        // replaced). Every declared native id must exist in the registry, or
        // freeze/validate would reject the revision.
        expect(spec.mcps).toHaveLength(0)
        const catalog = new Set(listNativeTools().map((t) => t.id))
        const nativeIds = spec.tools.filter((t) => t.kind === 'native').map((t) => t.id!)
        expect(nativeIds.length).toBeGreaterThan(0)
        for (const id of nativeIds) {
            expect(catalog.has(id), `${id} should be a known native tool`).toBe(true)
        }
    })

    it('declares both chat and mcp triggers (the two production surfaces)', async () => {
        const { spec } = await loadBundle()
        const triggerTypes = spec.triggers.map((t) => t.type)
        expect(triggerTypes).toContain('chat')
        expect(triggerTypes).toContain('mcp')
    })

    it('wires the nightly-fleet-audit cron with its durable-output tools + skill', async () => {
        const { spec, files } = await loadBundle()
        // The unattended audit is a cron trigger — no human, no client tools.
        // Its only durable outputs are memory + Slack, so those native tools
        // and the SLACK_BOT_TOKEN secret must be present, and the orchestration
        // skill it loads on the first turn must exist as a bundle file.
        const cron = spec.triggers.find((t) => t.type === 'cron')
        expect(cron, 'a cron trigger should be declared').not.toBeUndefined()
        expect(cron!.config?.name).toBe('nightly-fleet-audit')
        // The cron's prompt is the entire instruction set for an unattended run —
        // empty/placeholder here means the nightly job does nothing useful.
        expect((cron!.config?.prompt ?? '').length).toBeGreaterThan(80)

        const nativeIds = new Set(spec.tools.filter((t) => t.kind === 'native').map((t) => t.id))
        for (const id of [
            '@posthog/memory-search',
            '@posthog/memory-read',
            '@posthog/memory-write',
            '@posthog/slack-post-message',
        ]) {
            expect(nativeIds.has(id), `${id} should be wired for the audit's report output`).toBe(true)
        }
        // slack-post-message reads the agent's own SLACK_BOT_TOKEN (per-app, not
        // a team integration) — so the secret has to be declared.
        expect(spec.secrets).toContain('SLACK_BOT_TOKEN')

        const auditSkill = spec.skills.find((s) => s.id === 'auditing-the-fleet')
        expect(auditSkill, 'auditing-the-fleet skill should be declared').not.toBeUndefined()
        expect(files[auditSkill!.path]).not.toBeUndefined()
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

    it('accepts posthog + posthog_internal auth on its chat and mcp triggers', async () => {
        const { spec } = await loadBundle()
        // Auth is per-trigger now. The chat + mcp triggers each serve a human /
        // MCP client via a PostHog credential (`posthog`) and scripted /
        // server-to-server access (`posthog_internal`).
        const modesFor = (type: string): string[] =>
            spec.triggers.find((t) => t.type === type)?.auth?.modes?.map((m) => m.type) ?? []
        expect(modesFor('chat')).toEqual(expect.arrayContaining(['posthog', 'posthog_internal']))
        expect(modesFor('mcp')).toEqual(expect.arrayContaining(['posthog', 'posthog_internal']))
    })

    it('enables resume so multi-step flows can span days', async () => {
        const { spec } = await loadBundle()
        // Real edit-debug flows are multi-turn over hours. Default 24h sweep
        // would close them mid-thought.
        expect(spec.resume?.enabled).toBe(true)
        expect(spec.resume?.max_completed_age_ms).toBeGreaterThanOrEqual(7 * 24 * 60 * 60 * 1000)
    })

    it('gates destructive native tools (promote / archive) with session_principal approval', async () => {
        const { spec } = await loadBundle()
        // Destructive ops are gated at the platform layer, not just in the
        // prompt — the gating lives inline on the native `tools[]` entries via
        // `requires_approval: true` + `approval_policy.approvers`.
        const gated = new Map(
            spec.tools.filter((t) => t.kind === 'native' && t.requires_approval === true).map((t) => [t.id!, t])
        )
        for (const required of [
            '@posthog/agent-applications-revisions-promote-create',
            '@posthog/agent-applications-revisions-archive-create',
        ]) {
            expect(gated.has(required), `${required} should be gated`).toBe(true)
        }
        // session_principal — the concierge wires every gated tool to the
        // session owner via the per-asker fast-path, so the user who asked can
        // approve their own destructive call without a team-admin round-trip.
        for (const [, t] of gated) {
            expect(t.approval_policy?.approvers).toEqual(['session_principal'])
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
        // The runner reads `revision.spec` via zod. The concierge declares no
        // MCP server (native-only) and gates its destructive native tools
        // inline. This assertion pins that contract so a future schema
        // tightening doesn't silently re-break the bundle.
        const { spec } = await loadBundle()
        const parsed = AgentSpecSchema.parse(spec)
        expect(parsed.mcps).toHaveLength(0)
        // Spot-check that the destructive native entry kept its approval policy.
        const promote = parsed.tools.find(
            (t): t is Extract<typeof t, { kind: 'native' }> =>
                t.kind === 'native' && t.id === '@posthog/agent-applications-revisions-promote-create'
        )
        expect(promote).not.toBeUndefined()
        expect(promote!.requires_approval).toBe(true)
        expect(promote!.approval_policy.approvers).toEqual(['session_principal'])
        expect(promote!.approval_policy.ttl_ms).toBe(900_000)
    })

    it('the shared example seeder deploys this bundle without stripping mcps', async () => {
        // The concierge deploys via the shared generic seeder
        // (services/agent-tests/src/examples/seed.py), which auto-discovers
        // any dir with spec.json + agent.md. Things that would silently break
        // the deploy if removed:
        // - shebang for direct exec
        // - per_file_sha256 powers the no-op idempotency check
        // - the seeder must NOT strip `mcps[]` — the bundle ships it in the
        //   discriminated union shape the platform accepts.
        const scriptPath = resolve(__dirname, '../examples/seed.py')
        const src = await readFile(scriptPath, 'utf-8')
        expect(src.startsWith('#!/usr/bin/env python3')).toBe(true)
        expect(src).toContain('def load_v0_spec(')
        expect(src).toContain('def per_file_sha256(')
        expect(src).not.toContain('spec["mcps"] = []')
    })
})
