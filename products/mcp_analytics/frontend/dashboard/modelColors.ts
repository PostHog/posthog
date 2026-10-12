import type { ChartTheme } from '@posthog/quill-charts'

import { lightenDarkenColor, toOpaqueHex } from 'lib/utils/colors'
import { hashCodeForString } from 'lib/utils/strings'

import { type ModelLab, modelLab } from '../leaderboardHome/leaderboardShares'
import { MCP_ANALYTICS_COLORS } from './mcpAnalyticsColors'

export const AI_LAB_COLORS: Record<Exclude<ModelLab, 'Other'>, string> = {
    Anthropic: MCP_ANALYTICS_COLORS.anthropic,
    OpenAI: MCP_ANALYTICS_COLORS.openai,
    Google: MCP_ANALYTICS_COLORS.google,
    xAI: MCP_ANALYTICS_COLORS.xai,
    Cursor: MCP_ANALYTICS_COLORS.cursor,
    'Open weights': MCP_ANALYTICS_COLORS.openWeights,
}

const MODEL_FAMILY_PATTERN =
    /(?:^|[/.:-])(claude|gpt|chatgpt|o[134]|gemini|grok|glm|composer|deepseek|kimi|llama|mistral|qwen)(?=$|[-.0-9])/

export function labColor(theme: ChartTheme, lab: string): string | undefined {
    return AI_LAB_COLORS[lab as keyof typeof AI_LAB_COLORS] ?? theme.axisColor
}

export function modelColor(theme: ChartTheme, model: string): string | undefined {
    const normalized = model
        .trim()
        .toLowerCase()
        .replace(/[\s_]+/g, '-')
    if (normalized === 'unknown' || normalized === 'other') {
        return theme.axisColor
    }

    const match = MODEL_FAMILY_PATTERN.exec(normalized)
    const name = match ? normalized.slice(match.index + match[0].length - match[1].length) : normalized
    const hash = hashCodeForString(name)
    const lab = modelLab(normalized)
    const base = lab === 'Other' ? theme.colors[hash % theme.colors.length] : labColor(theme, lab)
    return shadeColor(base, ((hash % 5) - 2) * 8) ?? theme.axisColor
}

export function shadeColor(base: string | undefined, pct: number): string | undefined {
    if (!base) {
        return undefined
    }
    const hex = toOpaqueHex(base)
    return /^#[\da-f]{3}([\da-f]{3})?$/i.test(hex) ? lightenDarkenColor(hex, pct) : base
}
