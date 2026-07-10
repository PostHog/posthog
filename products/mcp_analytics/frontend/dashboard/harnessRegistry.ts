import { type ChartTheme } from '@posthog/quill-charts'

import antigravityLogo from '../harness-logos/antigravity.png'
import claudeLogo from '../harness-logos/claude.svg'
import coderabbitLogo from '../harness-logos/coderabbit.svg'
import cursorLogo from '../harness-logos/cursor.svg'
import librechatLogo from '../harness-logos/librechat.svg'
import linearLogo from '../harness-logos/linear.svg'
import lovableLogo from '../harness-logos/lovable.png'
import manusLogo from '../harness-logos/manus.svg'
import notionLogo from '../harness-logos/notion.svg'
import openaiLogo from '../harness-logos/openai.svg'
import opencodeLogo from '../harness-logos/opencode.svg'
import piLogo from '../harness-logos/pi.svg'
import replitLogo from '../harness-logos/replit.svg'
import vscodeLogo from '../harness-logos/vscode.svg'
import windsurfLogo from '../harness-logos/windsurf.svg'

export interface HarnessLogo {
    src: string
    alt: string
}

interface HarnessDescriptor {
    logo?: HarnessLogo
    // Index into the data-viz palette, chosen so the logo drawn on top keeps
    // enough contrast against its slice.
    colorIndex?: number
}

// Maps a *resolved* harness label to its logo and slice colour. The label itself is
// produced server-side by the backend classifier (products/mcp_analytics/backend/mcp_harness.py,
// the single source of truth); this map owns only the frontend-specific concerns the backend
// has no opinion on. Keys must match HARNESS_LABELS / harness_label_sql in mcp_harness.py.
// Exported so tests can assert coverage against the backend HARNESS_LABELS tuple.
export const HARNESS_BY_LABEL: Record<string, HarnessDescriptor> = {
    'Claude Desktop': { logo: { src: claudeLogo, alt: 'Claude Desktop logo' }, colorIndex: 5 },
    'Claude Code (VS Code)': { logo: { src: claudeLogo, alt: 'Claude Code logo' }, colorIndex: 6 },
    'Claude Agent SDK': { logo: { src: claudeLogo, alt: 'Claude Agent SDK logo' }, colorIndex: 7 },
    'Claude Code': { logo: { src: claudeLogo, alt: 'Claude Code logo' }, colorIndex: 0 },
    'Claude.ai': { logo: { src: claudeLogo, alt: 'Claude.ai logo' }, colorIndex: 2 },
    'Anthropic API': {},
    Cowork: { logo: { src: claudeLogo, alt: 'Cowork logo' }, colorIndex: 3 },
    'Claude Design': { logo: { src: claudeLogo, alt: 'Claude Design logo' }, colorIndex: 4 },
    ChatGPT: { logo: { src: openaiLogo, alt: 'ChatGPT logo' }, colorIndex: 8 },
    'OpenAI Agent Builder': { logo: { src: openaiLogo, alt: 'OpenAI Agent Builder logo' }, colorIndex: 9 },
    'OpenAI Responses API': { logo: { src: openaiLogo, alt: 'OpenAI Responses API logo' }, colorIndex: 10 },
    OpenAI: { logo: { src: openaiLogo, alt: 'OpenAI logo' }, colorIndex: 1 },
    'OpenAI Codex': { logo: { src: openaiLogo, alt: 'OpenAI Codex logo' }, colorIndex: 13 },
    Grok: { colorIndex: 14 },
    Cursor: { logo: { src: cursorLogo, alt: 'Cursor logo' }, colorIndex: 12 },
    'VS Code': { logo: { src: vscodeLogo, alt: 'VS Code logo' }, colorIndex: 11 },
    Windsurf: { logo: { src: windsurfLogo, alt: 'Windsurf logo' } },
    Replit: { logo: { src: replitLogo, alt: 'Replit logo' } },
    Lovable: { logo: { src: lovableLogo, alt: 'Lovable logo' } },
    Manus: { logo: { src: manusLogo, alt: 'Manus logo' } },
    CodeRabbit: { logo: { src: coderabbitLogo, alt: 'CodeRabbit logo' } },
    Notion: { logo: { src: notionLogo, alt: 'Notion logo' } },
    Linear: { logo: { src: linearLogo, alt: 'Linear logo' } },
    LibreChat: { logo: { src: librechatLogo, alt: 'LibreChat logo' } },
    Pi: { logo: { src: piLogo, alt: 'Pi logo' } },
    Antigravity: { logo: { src: antigravityLogo, alt: 'Antigravity logo' } },
    Poke: {},
    opencode: { logo: { src: opencodeLogo, alt: 'opencode logo' } },
    Kiro: {},
    'Desktop Commander': {},
}

export function harnessLogo(label: string): HarnessLogo | undefined {
    return HARNESS_BY_LABEL[label]?.logo
}

export function harnessSliceColor(theme: ChartTheme, label: string, fallbackIndex: number): string {
    const index = HARNESS_BY_LABEL[label]?.colorIndex ?? fallbackIndex
    return theme.colors[index % theme.colors.length]
}
