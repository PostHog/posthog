// The web's light-theme `--data-color-1..15` (frontend/src/styles/base.scss), so series N has the same color on the
// phone and in the browser.
export const LIGHT_CHART_PALETTE = [
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

// The web's dark theme overrides colors 2-6 and 10, which are too dark to read on a dark background. Color 1 is the
// dark theme's `blue` instead, because the brand blue has about 2:1 contrast on the dark background.
export const DARK_CHART_PALETTE: readonly string[] = [
    '#6B8AFF',
    '#7F26D9',
    '#3E7A76',
    '#BF0D6C',
    '#F0474F',
    '#B36114',
    '#529A0A',
    '#0476FB',
    '#FE729E',
    '#6576B3',
    '#41CBC4',
    '#B64B02',
    '#E4A604',
    '#A56EFF',
    '#30D5C8',
]

/** Series `index` in `palette` (the current theme's `chartPalette`), wrapping after the last color. */
export function seriesColor(index: number, palette: readonly string[]): string {
    return palette[((index % palette.length) + palette.length) % palette.length] ?? LIGHT_CHART_PALETTE[0]
}
