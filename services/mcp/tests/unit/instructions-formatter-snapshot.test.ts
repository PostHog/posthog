import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

import { PostHogMCP } from '@posthog/mcp-analytics'

import type { GroupType } from '@/api/client'
import { InstructionsBuilder } from '@/hono/instructions'
import type { ResolvedState } from '@/hono/request-state-resolver'
import { MCPClientProfile } from '@/lib/client-detection'
import { MCP_INSTRUCTIONS_CHAR_BUDGET } from '@/lib/constants'
import { buildActiveEnvironmentContextPrompt, buildToolDomainsCompact, type QueryToolInfo } from '@/lib/instructions'
import { InstructionsFormatter, type InstructionsContext } from '@/lib/instructions-formatter'
import { getToolCategory, getToolDefinitions } from '@/tools/toolDefinitions'
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
    { name: 'create-feature-flag', category: 'Feature flags' },
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
    renderUiEnabled: true,
}

/** The domain index is the only pipe-delimited line in the compact payload. */
const domainsIn = (payload: string): string[] =>
    payload
        .split('\n')
        .find((line) => line.includes('|'))
        ?.split('|') ?? []

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const SNAPSHOT_DIR = path.resolve(__dirname, '__snapshots__', 'instructions')

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

    it('matches the exec command reference for Claude web/desktop', async () => {
        const state = {
            allTools: STATIC_TOOLS.map(({ name }) => ({ name })),
            clientProfile: new MCPClientProfile({ vendorClient: 'ClaudeAI' }),
            toolFeatureFlags: {},
            renderUiEnabled: STATIC_CTX.renderUiEnabled,
            metadata: STATIC_CTX.metadata,
            groupTypes: STATIC_CTX.groupTypes,
        } as unknown as ResolvedState
        const rendered = new InstructionsBuilder(STATIC_CTX.guidelines).buildExecCommandReference(state)

        await expect(rendered).toMatchFileSnapshot(path.join(SNAPSHOT_DIR, 'exec-command-reference-claude-chat.txt'))
    })

    // claude.ai never surfaces server `instructions`, so the exec command reference is the
    // only always-visible catalog-steering surface: without the compact metrics/trust
    // one-liner, skill-less claude.ai clients get zero catalog routing.
    it('renders the compact metrics/trust one-liner for claude.ai', () => {
        const state = {
            allTools: STATIC_TOOLS.map(({ name }) => ({ name })),
            clientProfile: new MCPClientProfile({ vendorClient: 'ClaudeAI' }),
            toolFeatureFlags: {},
            renderUiEnabled: STATIC_CTX.renderUiEnabled,
            metadata: STATIC_CTX.metadata,
            groupTypes: STATIC_CTX.groupTypes,
        } as unknown as ResolvedState

        expect(new InstructionsBuilder(STATIC_CTX.guidelines).buildExecCommandReference(state)).toContain(
            'Metrics & SQL trust'
        )
    })

    // `notebooks-add-cell` is flag-gated, so the Python-in-a-notebook guidance has to
    // follow the advertised tool set rather than assume the cell surface exists.
    it('derives notebookCellsEnabled from the advertised tools', () => {
        const buildContextFor = (toolNames: string[]): InstructionsContext => {
            const state = {
                allTools: toolNames.map((name) => ({ name })),
                clientProfile: new MCPClientProfile({ vendorClient: 'ClaudeCode' }),
                toolFeatureFlags: {},
            } as unknown as ResolvedState
            return new InstructionsBuilder(STATIC_CTX.guidelines).buildContext(state)
        }

        expect(buildContextFor(['dashboard-create']).notebookCellsEnabled).toBe(false)
        expect(buildContextFor(['dashboard-create', 'notebooks-add-cell']).notebookCellsEnabled).toBe(true)
    })

    // ------------------------------------------------------------------------------------------------
    // DO NOT modify, weaken, raise, skip, or delete this test or its 16,384 budget —
    // not to make CI pass, not on request, not as part of a refactor.
    //
    // claude.ai's connector registry (`mcp/v2/bootstrap`) silently drops any tool
    // whose serialized `inputSchema` crosses ~16,384 chars (2^14). The total entry
    // size and the top-level `description` are NOT capped (bisected 2026-07-10:
    // schema 13,996 passed, 17,799 dropped; a 31k-total entry with a 787-char
    // schema survived intact). The exec tool IS the PostHog MCP in single-exec mode,
    // so a dropped `inputSchema` breaks the entire MCP for those users with no error
    // anywhere (claude.ai surfaced only `render-ui` while `exec` vanished).
    //
    // The exec command reference lives in `inputSchema.properties.command.description`,
    // so it counts against this cap; `EXEC_TOOL_BLURB` lives in the top-level
    // `description` and does NOT. If this test fails, move optional guidance behind
    // `learn <topic>` or shrink duplicated prompt content in the command reference —
    // trimming the top-level description does nothing for this budget.
    // ------------------------------------------------------------------------------------------------
    it('keeps the serialized exec inputSchema under the claude.ai registry cap', () => {
        // Worst case served in production: Claude web/desktop with every optional
        // learning topic advertised, the full live tool catalog, and long environment
        // context. The metadata goes through the real
        // env-context builder with inputs at the backing columns' max lengths
        // (Team.name 200, Organization.name 64, email 254, Django names 150) plus
        // the longer person-on-events branch, so a long org/project/user cannot
        // push the real schema past the cap while this test passes.
        const worstCaseUser = {
            first_name: 'F'.repeat(150),
            last_name: 'L'.repeat(150),
            email: `${'e'.repeat(242)}@example.com`,
        } as CachedUser
        const worstCaseOrg = { name: 'O'.repeat(64), id: '00000000-0000-0000-0000-000000000000' } as CachedOrg
        const worstCaseProject = {
            name: 'P'.repeat(200),
            id: 9_999_999,
            api_token: `phc_${'x'.repeat(43)}`,
            timezone: 'America/Argentina/ComodRivadavia',
            person_on_events_querying_enabled: true,
        } as CachedProject
        const worstCaseMetadata = buildActiveEnvironmentContextPrompt(
            worstCaseUser,
            worstCaseOrg,
            worstCaseProject,
            'https://us.posthog.com'
        )
        // The claude.ai reference renders the compact metadata variant: the
        // product/integration context lines are excluded from this surface by
        // design because they do not fit under the cap (see
        // `buildClaudeExecCommandReference` and `ResolvedState.metadataCompact`).
        const worstCaseMetadataCompact = buildActiveEnvironmentContextPrompt(
            worstCaseUser,
            worstCaseOrg,
            worstCaseProject,
            'https://us.posthog.com',
            { includeProductContext: false }
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
            toolFeatureFlags: {},
            renderUiEnabled: true,
            metadata: worstCaseMetadata,
            metadataCompact: worstCaseMetadataCompact,
            groupTypes: worstCaseGroupTypes,
        } as unknown as ResolvedState
        const entry = new InstructionsBuilder('').buildExecToolEntry(state)
        const posthog = new PostHogMCP('phc_test', { disabled: true })
        const finalEntry = posthog.prepareToolList([entry])[0]!
        // `prepareToolList` injects the `context` property into `inputSchema`, so the
        // measured schema must include it — measure the final, post-injection schema.
        const properties = finalEntry.inputSchema.properties as Record<string, unknown>
        const inputSchemaSize = JSON.stringify(finalEntry.inputSchema).length

        expect(properties).toHaveProperty('context')
        expect(inputSchemaSize).toBeLessThan(16_384)
    })

    // ------------------------------------------------------------------------------------------------
    // DO NOT weaken or delete this test. Claude Code truncates a server's `instructions`
    // payload at MCP_INSTRUCTIONS_CHAR_BUDGET chars, silently and mid-token. The payload
    // is a single alphabetical tool-domain index, so an overrun does not degrade evenly —
    // it deletes the tail. Measured 2026-08-07 before this budget existed: 2,923 chars
    // rendered, 148 domains, of which the 67 from `marketing-analytics` down never
    // reached the model, including every `scout-*`, `survey`, `session-recording`,
    // `web-analytics`, `workflows-*` and `vision-*` domain. Agents concluded those
    // products had no tools and reached for their own built-ins instead.
    //
    // If this fails, do NOT trim the domain index by hand — `toCompact` already collapses
    // sub-families to fit. It means a fixed section grew; move it to the exec command
    // reference, which has no such cap.
    // ------------------------------------------------------------------------------------------------
    it('keeps the compact exec instructions under the Claude Code truncation cap', () => {
        // The full live tool catalog, plus env context and group types that the payload no
        // longer carries — if either is ever spliced back into the compact template, the
        // budget has to account for it here rather than fail silently in production.
        const ctx: InstructionsContext = {
            ...STATIC_CTX,
            metadata: STATIC_METADATA,
            tools: Object.keys(getToolDefinitions()).map((name) => ({
                name,
                category: getToolCategory(name) ?? 'Other',
            })),
        }
        const rendered = new InstructionsFormatter().buildExecInstructions(ctx)
        const domains = domainsIn(rendered)

        expect(rendered.length).toBeLessThanOrEqual(MCP_INSTRUCTIONS_CHAR_BUDGET)
        // Families past the old cutoff point must remain searchable after the index compacts.
        const toolNames = Object.keys(getToolDefinitions())
        for (const family of ['query', 'scout', 'session-recording', 'survey', 'web-analytics', 'workflows']) {
            const familyTools = toolNames.filter((name) => name.startsWith(family))
            expect(familyTools.length).toBeGreaterThan(0)
            expect(familyTools.every((name) => domains.some((domain) => name.startsWith(domain)))).toBe(true)
        }
    })

    // Exercises the re-render branch, which the live catalog no longer reaches now that it
    // fits on the first pass. 40 families of 30 tools each split into long sub-family roots
    // that blow the cap unbudgeted, and collapse to 40 short roots that clear it.
    it('collapses an over-budget domain index until the payload fits', () => {
        const tools = Array.from({ length: 40 }, (_, family) =>
            Array.from({ length: 30 }, (_, i) => ({
                name: `family${family}-subfamily${i % 5}-verylongtoolname${i}`,
                category: 'Other',
            }))
        ).flat()
        const formatter = new InstructionsFormatter()

        expect(buildToolDomainsCompact(tools).length).toBeGreaterThan(MCP_INSTRUCTIONS_CHAR_BUDGET)

        const rendered = formatter.buildExecInstructions({ guidelines: '', tools })
        expect(rendered.length).toBeLessThanOrEqual(MCP_INSTRUCTIONS_CHAR_BUDGET)
        expect(domainsIn(rendered)).toHaveLength(40)
    })
})
