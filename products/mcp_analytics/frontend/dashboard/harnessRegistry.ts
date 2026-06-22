import { type ChartTheme } from '@posthog/quill-charts'

import claudeLogo from '../harness-logos/claude.svg'
import coderabbitLogo from '../harness-logos/coderabbit.svg'
import cursorLogo from '../harness-logos/cursor.svg'
import linearLogo from '../harness-logos/linear.svg'
import lovableLogo from '../harness-logos/lovable.png'
import manusLogo from '../harness-logos/manus.svg'
import notionLogo from '../harness-logos/notion.svg'
import openaiLogo from '../harness-logos/openai.svg'
import opencodeLogo from '../harness-logos/opencode.svg'
import replitLogo from '../harness-logos/replit.svg'
import vscodeLogo from '../harness-logos/vscode.svg'
import windsurfLogo from '../harness-logos/windsurf.svg'

export interface HarnessLogo {
    src: string
    alt: string
}

interface HarnessDescriptor {
    category: string
    // Matches against the normalized client token: lowercased, with the
    // "(via mcp-remote …)" suffix stripped (see categorizeHarness).
    match: (normalized: string) => boolean
    logo?: HarnessLogo
    // Index into the data-viz palette, chosen so the logo drawn on top keeps
    // enough contrast against its slice.
    colorIndex?: number
}

// Single source of truth for harness identity — how a normalized client token maps
// to a display category, its logo, and its slice colour. Adding a new harness is one
// entry here. Categories were derived from sampling the top distinct client
// identifiers seen in production (clientInfo.name, the x-anthropic-client vendor
// header, and User-Agent product tokens) over the past 30 days. The bucket list
// mirrors the HogQL in products/posthog_ai/skills/querying-posthog-data/references/models-mcp.md
// — keep the two in sync until a materialized $mcp_harness property exists.
//
// The normalized token can carry a surface suffix the query lifts out of the
// User-Agent's parenthetical, e.g. "claude-code cli", "claude-code claude-desktop",
// "openai-mcp chatgpt". List surface-specific entries before the generic prefix
// match so they win; clients whose parenthetical is platform/arch noise (e.g.
// "cursor darwin arm64") still fold to one bucket via the generic startsWith.
const HARNESS_REGISTRY: HarnessDescriptor[] = [
    {
        category: 'Claude Desktop',
        match: (n) => n === 'claude-code claude-desktop',
        logo: { src: claudeLogo, alt: 'Claude Desktop logo' },
        colorIndex: 5,
    },
    {
        category: 'Claude Code (VS Code)',
        match: (n) => n === 'claude-code claude-vscode',
        logo: { src: claudeLogo, alt: 'Claude Code logo' },
        colorIndex: 6,
    },
    {
        category: 'Claude Agent SDK',
        match: (n) => n.startsWith('claude-code sdk'),
        logo: { src: claudeLogo, alt: 'Claude Agent SDK logo' },
        colorIndex: 7,
    },
    {
        category: 'Claude Code',
        match: (n) => n.startsWith('claude-code'),
        logo: { src: claudeLogo, alt: 'Claude Code logo' },
        colorIndex: 0,
    },
    {
        category: 'Claude.ai',
        match: (n) => n === 'claude-ai' || n === 'anthropic/claudeai' || n === 'claude-user',
        logo: { src: claudeLogo, alt: 'Claude.ai logo' },
        colorIndex: 2,
    },
    { category: 'Anthropic API', match: (n) => n === 'anthropic/api' },
    { category: 'Cowork', match: (n) => n === 'cowork', logo: { src: claudeLogo, alt: 'Cowork logo' }, colorIndex: 3 },
    {
        category: 'Claude Design',
        match: (n) => n === 'claude-design',
        logo: { src: claudeLogo, alt: 'Claude Design logo' },
        colorIndex: 4,
    },
    {
        category: 'ChatGPT',
        match: (n) => n === 'openai-mcp chatgpt',
        logo: { src: openaiLogo, alt: 'ChatGPT logo' },
        colorIndex: 8,
    },
    {
        category: 'OpenAI Agent Builder',
        match: (n) => n === 'openai-mcp agent builder',
        logo: { src: openaiLogo, alt: 'OpenAI Agent Builder logo' },
        colorIndex: 9,
    },
    {
        category: 'OpenAI Responses API',
        match: (n) => n === 'openai-mcp responses api',
        logo: { src: openaiLogo, alt: 'OpenAI Responses API logo' },
        colorIndex: 10,
    },
    {
        category: 'OpenAI',
        match: (n) => n.startsWith('openai-mcp'),
        logo: { src: openaiLogo, alt: 'OpenAI logo' },
        colorIndex: 1,
    },
    {
        category: 'OpenAI Codex',
        match: (n) => n.startsWith('codex'),
        logo: { src: openaiLogo, alt: 'OpenAI Codex logo' },
        colorIndex: 13,
    },
    {
        category: 'Cursor',
        match: (n) => n.startsWith('cursor'),
        logo: { src: cursorLogo, alt: 'Cursor logo' },
        colorIndex: 12,
    },
    {
        category: 'VS Code',
        match: (n) => n.startsWith('visual studio code'),
        logo: { src: vscodeLogo, alt: 'VS Code logo' },
        colorIndex: 11,
    },
    { category: 'Windsurf', match: (n) => n === 'windsurf', logo: { src: windsurfLogo, alt: 'Windsurf logo' } },
    { category: 'Replit', match: (n) => n.startsWith('replit'), logo: { src: replitLogo, alt: 'Replit logo' } },
    { category: 'Lovable', match: (n) => n.startsWith('lovable'), logo: { src: lovableLogo, alt: 'Lovable logo' } },
    { category: 'Manus', match: (n) => n === 'manus', logo: { src: manusLogo, alt: 'Manus logo' } },
    { category: 'CodeRabbit', match: (n) => n === 'coderabbit', logo: { src: coderabbitLogo, alt: 'CodeRabbit logo' } },
    { category: 'Notion', match: (n) => n.startsWith('notion'), logo: { src: notionLogo, alt: 'Notion logo' } },
    { category: 'Linear', match: (n) => n.startsWith('linear'), logo: { src: linearLogo, alt: 'Linear logo' } },
    { category: 'Poke', match: (n) => n === 'poke' },
    { category: 'opencode', match: (n) => n === 'opencode', logo: { src: opencodeLogo, alt: 'opencode logo' } },
    { category: 'Kiro', match: (n) => n.startsWith('kiro') },
    { category: 'Desktop Commander', match: (n) => n.startsWith('desktop-commander') },
]

const HARNESS_BY_CATEGORY: Record<string, HarnessDescriptor> = Object.fromEntries(
    HARNESS_REGISTRY.map((entry) => [entry.category, entry])
)

export function categorizeHarness(raw: string): string {
    const stripped = raw
        .replace(/\s*\(via mcp-remote[^)]*\)\s*/i, '')
        .trim()
        .toLowerCase()
    if (!stripped) {
        return 'Other'
    }
    return HARNESS_REGISTRY.find((entry) => entry.match(stripped))?.category ?? 'Other'
}

export function harnessLogo(category: string): HarnessLogo | undefined {
    return HARNESS_BY_CATEGORY[category]?.logo
}

export function harnessSliceColor(theme: ChartTheme, category: string, fallbackIndex: number): string {
    const index = HARNESS_BY_CATEGORY[category]?.colorIndex ?? fallbackIndex
    return theme.colors[index % theme.colors.length]
}
