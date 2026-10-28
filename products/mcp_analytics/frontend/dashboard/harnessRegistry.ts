import { type ChartTheme } from '@posthog/quill-charts'

import { hashCodeForString } from 'lib/utils/strings'

import { type AiLab } from '../aiLabs'
import { type BrandMarkName } from '../brandMarks'
import { labColor, shadeColor } from '../colors'

const HARNESS_BRAND_COLORS = {
    vscode: '#007acc',
    coderabbit: '#ff570a',
    kimchi: '#ff521d',
    posthog: '#f54e00',
} as const

type HarnessBrand = keyof typeof HARNESS_BRAND_COLORS

interface HarnessDescriptor {
    mark?: BrandMarkName
    brand?: AiLab | HarnessBrand | 'monochrome'
    // Index into the data-viz palette for harnesses without a brand color.
    colorIndex?: number
    shade?: number
}

// Maps a *resolved* harness label to its brand mark and chart colour. The label itself is
// produced server-side by the backend classifier (products/mcp_analytics/backend/mcp_harness.py,
// the single source of truth); this map owns only the frontend-specific concerns the backend
// has no opinion on. Keys must match HARNESS_LABELS / harness_label_sql in mcp_harness.py.
// Exported so tests can assert coverage against the backend HARNESS_LABELS tuple.
export const HARNESS_BY_LABEL: Record<string, HarnessDescriptor> = {
    'Claude Desktop': { mark: 'Claude', brand: 'Anthropic', shade: -8 },
    'Claude Code (VS Code)': { mark: 'Claude', brand: 'Anthropic', shade: -4 },
    'Claude Agent SDK': { mark: 'Claude', brand: 'Anthropic', shade: 4 },
    'Claude Code': { mark: 'Claude', brand: 'Anthropic', shade: 0 },
    'Claude.ai': { mark: 'Claude', brand: 'Anthropic', shade: 8 },
    'Anthropic API': { mark: 'Anthropic', brand: 'Anthropic', shade: -12 },
    Cowork: { mark: 'Claude', brand: 'Anthropic', shade: 12 },
    'Claude Design': { mark: 'Claude', brand: 'Anthropic', shade: 16 },
    ChatGPT: { mark: 'OpenAI', brand: 'OpenAI', shade: 0 },
    'OpenAI Agent Builder': { mark: 'OpenAI', brand: 'OpenAI', shade: 4 },
    'OpenAI Responses API': { mark: 'OpenAI', brand: 'OpenAI', shade: -4 },
    OpenAI: { mark: 'OpenAI', brand: 'OpenAI', shade: 8 },
    'OpenAI Codex': { mark: 'OpenAI', brand: 'OpenAI', shade: -8 },
    Grok: { mark: 'Grok', brand: 'xAI' },
    Cursor: { mark: 'Cursor', brand: 'Cursor' },
    'VS Code': { mark: 'VS Code', brand: 'vscode' },
    Windsurf: { mark: 'Windsurf', brand: 'monochrome' },
    Replit: { mark: 'Replit', colorIndex: 11, shade: 15 },
    Lovable: { mark: 'Lovable', colorIndex: 4 },
    Manus: { mark: 'Manus', brand: 'monochrome' },
    CodeRabbit: { mark: 'CodeRabbit', brand: 'coderabbit' },
    Notion: { mark: 'Notion', brand: 'monochrome' },
    Linear: { mark: 'Linear', colorIndex: 9 },
    LibreChat: { mark: 'LibreChat', colorIndex: 14 },
    Pi: { mark: 'Pi', brand: 'monochrome' },
    Kimchi: { mark: 'Kimchi', brand: 'kimchi' },
    Antigravity: { mark: 'Antigravity', colorIndex: 7 },
    Poke: { mark: 'Poke' },
    opencode: { mark: 'opencode', brand: 'monochrome' },
    Kiro: { mark: 'Kiro' },
    'Desktop Commander': { mark: 'Desktop Commander' },
    'PostHog CLI': { mark: 'PostHog', brand: 'posthog' },
    // Not backend labels: clients the classifier does not recognize keep their own name, and these
    // two names are common enough to get a mark.
    'PostHog AI': { mark: 'PostHog', brand: 'posthog' },
    Slack: { mark: 'Slack' },
}

export function harnessMark(label: string): BrandMarkName {
    if (label === 'Unidentified client') {
        return 'Unidentified client'
    }
    return HARNESS_BY_LABEL[label]?.mark ?? 'Other harnesses'
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
