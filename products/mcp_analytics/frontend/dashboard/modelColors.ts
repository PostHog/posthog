import type { ChartTheme } from '@posthog/quill-charts'

import { lightenDarkenColor, toOpaqueHex } from 'lib/utils/colors'
import { hashCodeForString } from 'lib/utils/strings'

const FAMILY_COLOR_INDEX: Record<string, number> = {
    claude: 11,
    gpt: 0,
    chatgpt: 0,
    o1: 0,
    o3: 0,
    o4: 0,
    gemini: 2,
    grok: 1,
    glm: 3,
    composer: 5,
    deepseek: 7,
    kimi: 6,
    llama: 10,
    mistral: 12,
    qwen: 14,
}

const FAMILY_PATTERN = new RegExp(`(?:^|[/.:-])(${Object.keys(FAMILY_COLOR_INDEX).join('|')})(?=$|[-.0-9])`)

export function modelColor(theme: ChartTheme, model: string): string | undefined {
    const normalized = model
        .trim()
        .toLowerCase()
        .replace(/[\s_]+/g, '-')
    if (normalized === 'unknown' || normalized === 'other') {
        return theme.axisColor
    }

    const match = FAMILY_PATTERN.exec(normalized)
    const name = match ? normalized.slice(match.index + match[0].length - match[1].length) : normalized
    const hash = hashCodeForString(name)
    const index = match ? FAMILY_COLOR_INDEX[match[1]] : hash
    const base = theme.colors[index % theme.colors.length]
    if (!base) {
        return theme.axisColor
    }
    const hex = toOpaqueHex(base)
    return /^#[\da-f]{3}([\da-f]{3})?$/i.test(hex) ? lightenDarkenColor(hex, (hash % 5) * 8) : base
}
