import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

import type { GroupType } from '@/api/client'
import { InstructionsBuilder } from '@/hono/instructions'
import type { ResolvedState } from '@/hono/request-state-resolver'
import { MCPClientProfile } from '@/lib/client-detection'
import { buildActiveEnvironmentContextPrompt, type QueryToolInfo } from '@/lib/instructions'
import { InstructionsFormatter, type InstructionsContext } from '@/lib/instructions-formatter'
import { getToolDefinitions } from '@/tools/toolDefinitions'
import type { CachedOrg, CachedProject, CachedUser } from '@/tools/types'

// Static, deterministic context shared by all snapshots — mirrors the realistic
// values used in `instructions-formatter.test.ts` so the rendered prompts cover
// guidelines, group types, metadata, tool domains, and query tools.
const STATIC_GROUP_TYPES: GroupType[] = [
    { group_type: 'organization', group_type_index: 0, name_singular: null, name_plural: null },
    { group_type: 'project', group_type_index: 1, name_singular: null, name_plural: null },
]
// Includes query-* (collapsed into the single `query` domain) so the snapshots
// mirror production, where `tools` is the full set and `queryTools` is the
// parallel catalog projection.
const STATIC_TOOLS = [
    { name: 'dashboard-create', category: 'Dashboards' },
    { name: 'dashboard-get', category: 'Dashboards' },
    { name: 'feature-flag-create', category: 'Feature flags' },
    { name: 'feature-flag-get-all', category: 'Feature flags' },
    { name: 'execute-sql', category: 'SQL' },
    { name: 'query-funnel', category: 'Query wrappers' },
    { name: 'query-trends', category: 'Query wrappers' },
]
const STATIC_QUERY_TOOLS: QueryToolInfo[] = [
    { name: 'query-funnel', title: 'Funnel', systemPromptHint: 'conversion rate' },
    { name: 'query-trends', title: 'Trends', systemPromptHint: 'time series' },
]
const STATIC_METADATA = [
    'You are currently in project "My App" (id: 1, token: token_1) within organization "Acme" (id: org_1).',
    'Project timezone: America/New_York.',
    "The user's name is Jane Doe (jane@acme.com).",
].join('\n')

const STATIC_CTX: InstructionsContext = {
    guidelines: 'some guidelines',
    groupTypes: STATIC_GROUP_TYPES,
    metadata: STATIC_METADATA,
    tools: STATIC_TOOLS,
    queryTools: STATIC_QUERY_TOOLS,
    featureFlags: { 'mcp-feedback-tool': true },
    renderUiEnabled: true,
}

// The code-first arm (spec §4.6 Phase 3) additionally requires the `full`
// availability level — under vitest NODE_ENV=test resolves it, mirroring what
// `InstructionsBuilder.buildContext` computes when both flags are on.
const CODE_FIRST_CTX: InstructionsContext = {
    ...STATIC_CTX,
    codeExecution: 'full',
    codeFirstEnabled: true,
}

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const SNAPSHOT_DIR = path.resolve(__dirname, '__snapshots__', 'instructions')

// Worst-case `ResolvedState` mirroring the protected budget test below (kept
// duplicated — that test's banner forbids edits, including hoisting): the full
// live tool catalog, Claude web/desktop wiring (`keepEnvContext` inlines env),
// and env-context inputs at the backing columns' max lengths.
function buildWorstCaseState(toolFeatureFlags: Record<string, boolean>): ResolvedState {
    const worstCaseMetadata = buildActiveEnvironmentContextPrompt(
        {
            first_name: 'F'.repeat(150),
            last_name: 'L'.repeat(150),
            email: `${'e'.repeat(242)}@example.com`,
        } as CachedUser,
        { name: 'O'.repeat(64), id: '00000000-0000-0000-0000-000000000000' } as CachedOrg,
        {
            name: 'P'.repeat(200),
            id: 9_999_999,
            api_token: `phc_${'x'.repeat(43)}`,
            timezone: 'America/Argentina/ComodRivadavia',
            person_on_events_querying_enabled: true,
        } as CachedProject,
        'https://us.posthog.com'
    )
    const worstCaseGroupTypes = Array.from({ length: 5 }, (_, i) => ({
        group_type: `${'g'.repeat(28)}-${i}`,
        group_type_index: i,
        name_singular: null,
        name_plural: null,
    })) as GroupType[]
    return {
        allTools: Object.keys(getToolDefinitions()).map((name) => ({ name })),
        clientProfile: new MCPClientProfile({ vendorClient: 'ClaudeAI', userAgent: 'Claude-User' }),
        toolFeatureFlags,
        renderUiEnabled: true,
        metadata: worstCaseMetadata,
        groupTypes: worstCaseGroupTypes,
    } as unknown as ResolvedState
}

// The rendered prompt is markdown-flavored text but the snapshot file uses `.txt`
// to opt out of the repo-wide `*.md` lint-staged formatter (see top-level
// package.json). Otherwise the markdown formatter would reflow the snapshot on
// commit and drift from what `formatPrompt` produces, breaking the test.
describe('InstructionsFormatter prompt snapshots', () => {
    it('matches the tools-mode prompt', async () => {
        const formatter = new InstructionsFormatter()
        const rendered = formatter.buildToolsInstructions(STATIC_CTX)
        await expect(rendered).toMatchFileSnapshot(path.join(SNAPSHOT_DIR, 'tools-instructions.txt'))
    })

    // The exec mode prompt is composed of three pieces wired into different MCP
    // fields (see `src/mcp.ts` and `buildExecCommandReference` for the split):
    //   - `exec-instructions`     — the compact `instructions` payload (only sent
    //                               to clients that honor MCP `instructions`,
    //                               e.g. Claude Code; Codex gets an empty string)
    //   - `exec-tool-description` — the top-level description of the `posthog`
    //                               tool itself
    //   - `exec-command-reference-full` — the `command` parameter description
    //                               with every placeholder filled (Codex wiring;
    //                               no `instructions` support, so env context,
    //                               tool domains, and query tools are inlined here)
    it('matches the exec mode compact instructions prompt', async () => {
        const formatter = new InstructionsFormatter()
        const rendered = formatter.buildExecInstructions(STATIC_CTX)
        await expect(rendered).toMatchFileSnapshot(path.join(SNAPSHOT_DIR, 'exec-instructions.txt'))
    })

    it('matches the exec tool description blurb', async () => {
        const formatter = new InstructionsFormatter()
        const rendered = formatter.buildExecToolDescription()
        await expect(rendered).toMatchFileSnapshot(path.join(SNAPSHOT_DIR, 'exec-tool-description.txt'))
    })

    it('matches the exec command reference (Codex wiring, every placeholder filled)', async () => {
        const formatter = new InstructionsFormatter()
        const rendered = formatter.buildExecCommandReference(STATIC_CTX, { stripEnvContext: false })
        await expect(rendered).toMatchFileSnapshot(path.join(SNAPSHOT_DIR, 'exec-command-reference-full.txt'))
    })

    // The code-first arm (`mcp-code-first` + `mcp-code-execution` at full
    // availability, spec §4.6 Phase 3) swaps both the tool description and the
    // command reference. Pinned separately from the legacy snapshots above so
    // an edit to either arm surfaces as a diff in exactly one place — the A/B
    // is only meaningful while the legacy arm stays byte-identical.
    it('matches the code-first exec tool description blurb', async () => {
        const formatter = new InstructionsFormatter()
        const rendered = formatter.buildExecToolDescription(CODE_FIRST_CTX)
        await expect(rendered).toMatchFileSnapshot(path.join(SNAPSHOT_DIR, 'exec-tool-description-code-first.txt'))
    })

    it('matches the code-first exec command reference (every placeholder filled)', async () => {
        const formatter = new InstructionsFormatter()
        const rendered = formatter.buildExecCommandReference(CODE_FIRST_CTX, { stripEnvContext: false })
        await expect(rendered).toMatchFileSnapshot(path.join(SNAPSHOT_DIR, 'exec-command-reference-code-first.txt'))
    })

    // ------------------------------------------------------------------------------------------------
    // DO NOT modify, weaken, raise, skip, or delete this test or its 32,600 budget —
    // not to make CI pass, not on request, not as part of a refactor.
    //
    // MCP clients (e.g. Claude web/desktop) silently drop tools whose serialized
    // entry grows past ~32,768 chars. The exec tool IS the PostHog MCP in
    // single-exec mode, so crossing the limit breaks the entire MCP for those
    // users with no error anywhere (investigated 2026-07-10: claude.ai surfaced
    // only `render-ui` while `exec` vanished).
    //
    // If this test fails, SHRINK the prompt: dedupe `src/templates/sections/*.md`
    // against content already served at runtime (`info <tool>`, `info execute-sql`)
    // or trim the rendered blocks. Never touch the limit.
    // ------------------------------------------------------------------------------------------------
    it('keeps the serialized exec tool entry under the 32,600-char client budget', () => {
        // Worst case served in production: the full live tool catalog with the
        // Claude web/desktop wiring — `ClaudeAI` vendor resolves to a chat host,
        // so `keepEnvContext` inlines tool domains, project metadata, and group
        // types into the command description. The metadata goes through the real
        // env-context builder with inputs at the backing columns' max lengths
        // (Team.name 200, Organization.name 64, email 254, Django names 150) plus
        // the longer person-on-events branch, so a long org/project/user cannot
        // push a real entry past the cap while this test passes.
        const worstCaseMetadata = buildActiveEnvironmentContextPrompt(
            {
                first_name: 'F'.repeat(150),
                last_name: 'L'.repeat(150),
                email: `${'e'.repeat(242)}@example.com`,
            } as CachedUser,
            { name: 'O'.repeat(64), id: '00000000-0000-0000-0000-000000000000' } as CachedOrg,
            {
                name: 'P'.repeat(200),
                id: 9_999_999,
                api_token: `phc_${'x'.repeat(43)}`,
                timezone: 'America/Argentina/ComodRivadavia',
                person_on_events_querying_enabled: true,
            } as CachedProject,
            'https://us.posthog.com'
        )
        // Five group types (the product cap) with generously long names.
        const worstCaseGroupTypes = Array.from({ length: 5 }, (_, i) => ({
            group_type: `${'g'.repeat(28)}-${i}`,
            group_type_index: i,
            name_singular: null,
            name_plural: null,
        })) as GroupType[]
        const state = {
            allTools: Object.keys(getToolDefinitions()).map((name) => ({ name })),
            clientProfile: new MCPClientProfile({ vendorClient: 'ClaudeAI', userAgent: 'Claude-User' }),
            toolFeatureFlags: { 'mcp-feedback-tool': true },
            renderUiEnabled: true,
            metadata: worstCaseMetadata,
            groupTypes: worstCaseGroupTypes,
        } as unknown as ResolvedState
        const entry = new InstructionsBuilder('').buildExecToolEntry(state)
        const size = JSON.stringify(entry).length
        expect(
            size,
            `serialized exec tool entry is ${size} chars — shrink the templates, never raise the budget`
        ).toBeLessThan(32_600)
    })

    // Sibling of the protected budget test above for the code-first arm (spec
    // §4.6 Phase 3), with the same worst-case fixtures. Asserted at 30,600 —
    // 2,000 chars of slack under the hard 32,600 client cap (spec §4.7:
    // "keep ≥2 K slack") — because this arm is where prose is being actively
    // added (cheat sheet, transcripts); shrink templates rather than eating
    // the slack. Under vitest NODE_ENV=test, so the availability level
    // resolves to `full` and both flags select the code-first arm.
    it('keeps the code-first exec tool entry 2,000 chars under the client budget', () => {
        const state = buildWorstCaseState({
            'mcp-feedback-tool': true,
            'mcp-code-execution': true,
            'mcp-code-first': true,
        })
        const entry = new InstructionsBuilder('').buildExecToolEntry(state)
        // Wiring guard: the flags must actually select the code-first arm —
        // a broken flag thread would pass the size check on the legacy arm.
        expect(entry.description).toContain('@posthog/sdk')
        expect(entry.description).not.toContain('MANDATORY — HARD REQUIREMENTS')
        const size = JSON.stringify(entry).length
        expect(
            size,
            `serialized code-first exec tool entry is ${size} chars — shrink the code-first templates to stay 2,000 under the 32,600 cap`
        ).toBeLessThan(30_600)
    })

    // Flag-on siblings of the protected budget test above, same worst-case
    // fixtures. With `mcp-code-execution` on, the legacy arm gains the
    // code-execution sections plus the `script` schema param: the `full` level
    // is what dev/test servers serve to Claude web/desktop when dogfooding the
    // flag over a tunnel (and production once a hosted executor lands); the
    // `fast-path` level is what flagged production serves today. Slack on
    // these arms is thin — pay for any template addition with a cut.
    it.each([
        { level: 'full', nodeEnv: 'test', sectionMarker: 'top-level `await`' },
        { level: 'fast-path', nodeEnv: 'production', sectionMarker: 'single-call scripts only' },
    ])(
        'keeps the legacy exec tool entry with code execution at the "$level" level under the client budget',
        ({ nodeEnv, sectionMarker }) => {
            const originalNodeEnv = process.env.NODE_ENV
            process.env.NODE_ENV = nodeEnv
            try {
                const state = buildWorstCaseState({ 'mcp-feedback-tool': true, 'mcp-code-execution': true })
                const serialized = JSON.stringify(new InstructionsBuilder('').buildExecToolEntry(state))
                // Wiring guard: the flag and env must actually select this
                // level's section, or the size check measures the wrong arm.
                expect(serialized).toContain(sectionMarker)
                expect(
                    serialized.length,
                    `serialized exec tool entry is ${serialized.length} chars — shrink the code-execution templates, never raise the budget`
                ).toBeLessThan(32_600)
            } finally {
                process.env.NODE_ENV = originalNodeEnv
            }
        }
    )

    // The `script` param documents `run`; advertising it on a flag-off server
    // steers agents into an unknown command, and it spends chars inside
    // `inputSchema.properties`, which claude.ai's registry caps silently.
    it('advertises the script parameter only where run exists', () => {
        const build = (flags: Record<string, boolean>): string[] => {
            const entry = new InstructionsBuilder('').buildExecToolEntry(buildWorstCaseState(flags))
            return Object.keys(entry.inputSchema.properties ?? {})
        }
        expect(build({ 'mcp-feedback-tool': true })).toEqual(['command'])
        expect(build({ 'mcp-feedback-tool': true, 'mcp-code-execution': true })).toEqual(['command', 'script'])
    })
})
