import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

import type { GroupType } from '@/api/client'
import type { QueryToolInfo } from '@/lib/instructions'
import { InstructionsFormatter, type InstructionsContext } from '@/lib/instructions-formatter'

// Static, deterministic context shared by all snapshots — mirrors the realistic
// values used in `instructions-formatter.test.ts` so the rendered prompts cover
// guidelines, group types, metadata, tool domains, and query tools.
const STATIC_GROUP_TYPES: GroupType[] = [
    { group_type: 'organization', group_type_index: 0, name_singular: null, name_plural: null },
    { group_type: 'project', group_type_index: 1, name_singular: null, name_plural: null },
]
const STATIC_TOOLS = [
    { name: 'dashboard-create', category: 'Dashboards' },
    { name: 'dashboard-get', category: 'Dashboards' },
    { name: 'feature-flag-create', category: 'Feature flags' },
    { name: 'feature-flag-get-all', category: 'Feature flags' },
    { name: 'execute-sql', category: 'SQL' },
]
const STATIC_QUERY_TOOLS: QueryToolInfo[] = [
    { name: 'query-funnel', title: 'Funnel', systemPromptHint: 'conversion rate' },
    { name: 'query-trends', title: 'Trends', systemPromptHint: 'time series' },
]
const STATIC_METADATA = [
    'You are currently in project "My App" (id: 1) within organization "Acme" (id: org_1).',
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
}

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const SNAPSHOT_DIR = path.resolve(__dirname, '__snapshots__', 'instructions')

// The rendered prompt is markdown-flavored text but the snapshot file uses `.txt`
// to opt out of the repo-wide `*.md` lint-staged formatter (see top-level
// package.json). Otherwise the markdown formatter would reflow the snapshot on
// commit and drift from what `formatPrompt` produces, breaking the test.
describe('InstructionsFormatter prompt snapshots', () => {
    it('matches the v1 (legacy) prompt', async () => {
        const formatter = new InstructionsFormatter()
        const rendered = formatter.buildV1Instructions()
        await expect(rendered).toMatchFileSnapshot(path.join(SNAPSHOT_DIR, 'tools-v1-instructions.txt'))
    })

    it('matches the v1 (legacy) prompt with metadata appended', async () => {
        const formatter = new InstructionsFormatter()
        const rendered = formatter.buildV1Instructions(STATIC_METADATA)
        await expect(rendered).toMatchFileSnapshot(path.join(SNAPSHOT_DIR, 'tools-v1-instructions-with-metadata.txt'))
    })

    it('matches the v2 (tools-mode) prompt', async () => {
        const formatter = new InstructionsFormatter()
        const rendered = formatter.buildV2Instructions(STATIC_CTX)
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
})
