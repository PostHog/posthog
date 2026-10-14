import { colors } from '@/ui/tokens'

// The web's light-theme `--data-color-1..15` (frontend/src/styles/base.scss), so series N has the same color on the
// phone and in the browser.
const CHART_PALETTE = [
    '#1D4AFF',
    '#621DA6',
    '#42827E',
    '#CE0E74',
    '#F14F58',
    '#7C440E',
    '#529A0A',
    '#0476FB',
    '#FE729E',
    '#35416B',
    '#41CBC4',
    '#B64B02',
    '#E4A604',
    '#A56EFF',
    '#30D5C8',
] as const

export function seriesColor(index: number): string {
    return CHART_PALETTE[((index % CHART_PALETTE.length) + CHART_PALETTE.length) % CHART_PALETTE.length] ?? colors.blue
}

/** The previous period draws gray, so it never competes with the current series for attention. */
export const PREVIOUS_PERIOD_COLOR = colors.disabled
