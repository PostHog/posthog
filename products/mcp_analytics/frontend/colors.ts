import type { ChartTheme } from '@posthog/quill-charts'

import { AI_LAB_SHADES, type AiLab, MAIN_LAB_SHADE } from 'lib/components/BrandMark/aiLabShades'
import { RGBToHex, hexToRGB, lightenDarkenColor, toOpaqueHex } from 'lib/utils/colors'
import { hashCodeForString } from 'lib/utils/strings'

import { otherModelsLabel, seriesLab } from './aiLabs'

// Neighboring shades are at most 0.12 apart in lightness (4/3 of a ramp step), so a lab with few models
// stays close to its main shade instead of stretching to the darkest and lightest ends.
const MAX_SHADE_STEP = 4 / 3

const NEUTRAL_LABELS = new Set(['Unknown', 'Other', otherModelsLabel('Other')])

export function labColor(theme: ChartTheme, lab: string): string | undefined {
    return AI_LAB_SHADES[lab as AiLab]?.[MAIN_LAB_SHADE] ?? theme.axisColor
}

/**
 * Colors every model shown on one page. Pass the models in display order, with every model that any
 * chart on the page shows, so that a model has the same color in every chart. Each lab's models spread
 * around its main shade, darkest first. Models without a lab use the theme palette.
 */
export function modelColors(theme: ChartTheme, models: string[]): Map<string, string | undefined> {
    const unique = [...new Set(models)]
    const modelsByLab = new Map<AiLab, string[]>()
    const colors = new Map<string, string | undefined>()
    for (const model of unique) {
        const lab = seriesLab(model)
        if (NEUTRAL_LABELS.has(model)) {
            colors.set(model, theme.axisColor)
        } else if (lab === 'Other') {
            colors.set(model, theme.colors[hashCodeForString(model) % theme.colors.length] ?? theme.axisColor)
        } else {
            modelsByLab.set(lab, [...(modelsByLab.get(lab) ?? []), model])
        }
    }
    for (const [lab, labModels] of modelsByLab) {
        const shades = AI_LAB_SHADES[lab]
        const gaps = labModels.length - 1
        const step = gaps > 0 ? Math.min((shades.length - 1) / gaps, MAX_SHADE_STEP) : 0
        const first = MAIN_LAB_SHADE - (step * gaps) / 2
        labModels.forEach((model, rank) => colors.set(model, shadeAt(shades, first + step * rank)))
    }
    return colors
}

function shadeAt(shades: readonly string[], position: number): string {
    const clamped = Math.min(Math.max(position, 0), shades.length - 1)
    const lower = Math.floor(clamped)
    const fraction = clamped - lower
    if (fraction === 0) {
        return shades[lower]
    }
    const from = hexToRGB(shades[lower])
    const to = hexToRGB(shades[lower + 1])
    const mix = (a: number, b: number): number => Math.round(a + (b - a) * fraction)
    return RGBToHex(`rgb(${mix(from.r, to.r)},${mix(from.g, to.g)},${mix(from.b, to.b)})`)
}

export function shadeColor(base: string | undefined, pct: number): string | undefined {
    if (!base) {
        return undefined
    }
    const hex = toOpaqueHex(base)
    return /^#[\da-f]{3}([\da-f]{3})?$/i.test(hex) ? lightenDarkenColor(hex, pct) : base
}
