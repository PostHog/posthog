import { type ChartTheme } from '@posthog/quill-charts'

import { lightenDarkenColor, toOpaqueHex } from 'lib/utils/colors'
import { hashCodeForString } from 'lib/utils/strings'

import antigravityLogo from '../harness-logos/antigravity.png'
import claudeLogo from '../harness-logos/claude.svg'
import coderabbitLogo from '../harness-logos/coderabbit.svg'
import cursorLogo from '../harness-logos/cursor.svg'
import grokLogo from '../harness-logos/grok.svg'
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

const HARNESS_BRAND_COLORS = {
    claude: '#d97757',
    openai: '#74aa9c',
    vscode: '#007acc',
    coderabbit: '#ff570a',
} as const

interface HarnessDescriptor {
    logo?: HarnessLogo
    color?: keyof typeof HARNESS_BRAND_COLORS | 'monochrome'
    // Index into the data-viz palette for harnesses without a brand color.
    colorIndex?: number
    shade?: number
}

// Maps a *resolved* harness label to its logo and chart colour. The label itself is
// produced server-side by the backend classifier (products/mcp_analytics/backend/mcp_harness.py,
// the single source of truth); this map owns only the frontend-specific concerns the backend
// has no opinion on. Keys must match HARNESS_LABELS / harness_label_sql in mcp_harness.py.
// Exported so tests can assert coverage against the backend HARNESS_LABELS tuple.
export const HARNESS_BY_LABEL: Record<string, HarnessDescriptor> = {
    'Claude Desktop': { logo: { src: claudeLogo, alt: 'Claude Desktop logo' }, color: 'claude', shade: -8 },
    'Claude Code (VS Code)': { logo: { src: claudeLogo, alt: 'Claude Code logo' }, color: 'claude', shade: -4 },
    'Claude Agent SDK': { logo: { src: claudeLogo, alt: 'Claude Agent SDK logo' }, color: 'claude', shade: 4 },
    'Claude Code': { logo: { src: claudeLogo, alt: 'Claude Code logo' }, color: 'claude', shade: 0 },
    'Claude.ai': { logo: { src: claudeLogo, alt: 'Claude.ai logo' }, color: 'claude', shade: 8 },
    'Anthropic API': { color: 'claude', shade: -12 },
    Cowork: { logo: { src: claudeLogo, alt: 'Cowork logo' }, color: 'claude', shade: 12 },
    'Claude Design': { logo: { src: claudeLogo, alt: 'Claude Design logo' }, color: 'claude', shade: 16 },
    ChatGPT: { logo: { src: openaiLogo, alt: 'ChatGPT logo' }, color: 'openai', shade: 0 },
    'OpenAI Agent Builder': { logo: { src: openaiLogo, alt: 'OpenAI Agent Builder logo' }, color: 'openai', shade: 4 },
    'OpenAI Responses API': { logo: { src: openaiLogo, alt: 'OpenAI Responses API logo' }, color: 'openai', shade: -4 },
    OpenAI: { logo: { src: openaiLogo, alt: 'OpenAI logo' }, color: 'openai', shade: 8 },
    'OpenAI Codex': { logo: { src: openaiLogo, alt: 'OpenAI Codex logo' }, color: 'openai', shade: -8 },
    Grok: { logo: { src: grokLogo, alt: 'Grok logo' }, color: 'monochrome' },
    Cursor: { logo: { src: cursorLogo, alt: 'Cursor logo' }, color: 'monochrome' },
    'VS Code': { logo: { src: vscodeLogo, alt: 'VS Code logo' }, color: 'vscode' },
    Windsurf: { logo: { src: windsurfLogo, alt: 'Windsurf logo' }, color: 'monochrome' },
    Replit: { logo: { src: replitLogo, alt: 'Replit logo' }, colorIndex: 11, shade: 15 },
    Lovable: { logo: { src: lovableLogo, alt: 'Lovable logo' }, colorIndex: 4 },
    Manus: { logo: { src: manusLogo, alt: 'Manus logo' }, color: 'monochrome' },
    CodeRabbit: { logo: { src: coderabbitLogo, alt: 'CodeRabbit logo' }, color: 'coderabbit' },
    Notion: { logo: { src: notionLogo, alt: 'Notion logo' }, color: 'monochrome' },
    Linear: { logo: { src: linearLogo, alt: 'Linear logo' }, colorIndex: 9 },
    LibreChat: { logo: { src: librechatLogo, alt: 'LibreChat logo' }, colorIndex: 14 },
    Pi: { logo: { src: piLogo, alt: 'Pi logo' }, color: 'monochrome' },
    Antigravity: { logo: { src: antigravityLogo, alt: 'Antigravity logo' }, colorIndex: 7 },
    Poke: {},
    opencode: { logo: { src: opencodeLogo, alt: 'opencode logo' }, color: 'monochrome' },
    Kiro: {},
    'Desktop Commander': {},
    'PostHog CLI': {},
}

export function harnessLogo(label: string): HarnessLogo | undefined {
    return HARNESS_BY_LABEL[label]?.logo
}

export function harnessColor(theme: ChartTheme, label: string): string | undefined {
    if (label === 'Other' || label === 'Unidentified client') {
        return theme.axisColor
    }
    const descriptor = HARNESS_BY_LABEL[label]
    if (descriptor?.color === 'monochrome') {
        return theme.axisColor
    }
    const index = descriptor?.colorIndex ?? hashCodeForString(label)
    const base = descriptor?.color ? HARNESS_BRAND_COLORS[descriptor.color] : theme.colors[index % theme.colors.length]
    if (!base) {
        return theme.axisColor
    }
    const hex = toOpaqueHex(base)
    return descriptor?.shade && /^#[\da-f]{3}([\da-f]{3})?$/i.test(hex)
        ? lightenDarkenColor(hex, descriptor.shade)
        : base
}
