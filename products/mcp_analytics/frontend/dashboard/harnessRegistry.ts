import { type ChartTheme } from '@posthog/quill-charts'

import { hashCodeForString } from 'lib/utils/strings'

import { type AiLab } from '../aiLabs'
import { labColor, shadeColor } from '../colors'
import antigravityLogo from '../harness-logos/antigravity.png'
import claudeLogo from '../harness-logos/claude.svg'
import coderabbitLogo from '../harness-logos/coderabbit.svg'
import cursorLogo from '../harness-logos/cursor.svg'
import grokLogo from '../harness-logos/grok.svg'
import kimchiLogo from '../harness-logos/kimchi.svg'
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
    vscode: '#007acc',
    coderabbit: '#ff570a',
    kimchi: '#ff521d',
} as const

type HarnessBrand = keyof typeof HARNESS_BRAND_COLORS

interface HarnessDescriptor {
    logo?: HarnessLogo
    brand?: AiLab | HarnessBrand | 'monochrome'
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
    'Claude Desktop': { logo: { src: claudeLogo, alt: 'Claude Desktop logo' }, brand: 'Anthropic', shade: -8 },
    'Claude Code (VS Code)': { logo: { src: claudeLogo, alt: 'Claude Code logo' }, brand: 'Anthropic', shade: -4 },
    'Claude Agent SDK': { logo: { src: claudeLogo, alt: 'Claude Agent SDK logo' }, brand: 'Anthropic', shade: 4 },
    'Claude Code': { logo: { src: claudeLogo, alt: 'Claude Code logo' }, brand: 'Anthropic', shade: 0 },
    'Claude.ai': { logo: { src: claudeLogo, alt: 'Claude.ai logo' }, brand: 'Anthropic', shade: 8 },
    'Anthropic API': { brand: 'Anthropic', shade: -12 },
    Cowork: { logo: { src: claudeLogo, alt: 'Cowork logo' }, brand: 'Anthropic', shade: 12 },
    'Claude Design': { logo: { src: claudeLogo, alt: 'Claude Design logo' }, brand: 'Anthropic', shade: 16 },
    ChatGPT: { logo: { src: openaiLogo, alt: 'ChatGPT logo' }, brand: 'OpenAI', shade: 0 },
    'OpenAI Agent Builder': { logo: { src: openaiLogo, alt: 'OpenAI Agent Builder logo' }, brand: 'OpenAI', shade: 4 },
    'OpenAI Responses API': { logo: { src: openaiLogo, alt: 'OpenAI Responses API logo' }, brand: 'OpenAI', shade: -4 },
    OpenAI: { logo: { src: openaiLogo, alt: 'OpenAI logo' }, brand: 'OpenAI', shade: 8 },
    'OpenAI Codex': { logo: { src: openaiLogo, alt: 'OpenAI Codex logo' }, brand: 'OpenAI', shade: -8 },
    Grok: { logo: { src: grokLogo, alt: 'Grok logo' }, brand: 'xAI' },
    Cursor: { logo: { src: cursorLogo, alt: 'Cursor logo' }, brand: 'Cursor' },
    'VS Code': { logo: { src: vscodeLogo, alt: 'VS Code logo' }, brand: 'vscode' },
    Windsurf: { logo: { src: windsurfLogo, alt: 'Windsurf logo' }, brand: 'monochrome' },
    Replit: { logo: { src: replitLogo, alt: 'Replit logo' }, colorIndex: 11, shade: 15 },
    Lovable: { logo: { src: lovableLogo, alt: 'Lovable logo' }, colorIndex: 4 },
    Manus: { logo: { src: manusLogo, alt: 'Manus logo' }, brand: 'monochrome' },
    CodeRabbit: { logo: { src: coderabbitLogo, alt: 'CodeRabbit logo' }, brand: 'coderabbit' },
    Notion: { logo: { src: notionLogo, alt: 'Notion logo' }, brand: 'monochrome' },
    Linear: { logo: { src: linearLogo, alt: 'Linear logo' }, colorIndex: 9 },
    LibreChat: { logo: { src: librechatLogo, alt: 'LibreChat logo' }, colorIndex: 14 },
    Pi: { logo: { src: piLogo, alt: 'Pi logo' }, brand: 'monochrome' },
    Kimchi: { logo: { src: kimchiLogo, alt: 'Kimchi logo' }, brand: 'kimchi' },
    Antigravity: { logo: { src: antigravityLogo, alt: 'Antigravity logo' }, colorIndex: 7 },
    Poke: {},
    opencode: { logo: { src: opencodeLogo, alt: 'opencode logo' }, brand: 'monochrome' },
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
    const brand = descriptor?.brand
    if (brand === 'monochrome') {
        return theme.axisColor
    }
    const index = descriptor?.colorIndex ?? hashCodeForString(label)
    const base = !brand
        ? theme.colors[index % theme.colors.length]
        : brand in HARNESS_BRAND_COLORS
          ? HARNESS_BRAND_COLORS[brand as HarnessBrand]
          : labColor(theme, brand)
    if (!base) {
        return theme.axisColor
    }
    return descriptor?.shade ? shadeColor(base, descriptor.shade) : base
}
