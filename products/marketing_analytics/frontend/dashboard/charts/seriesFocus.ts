import { ChartTheme } from '@posthog/quill-charts'

/** Low enough to recede, high enough that the line is still traceable. */
const DIMMED_ALPHA = 0.18

/** The chart hands colours to the canvas unresolved, so an explicit colour has to be concrete. */
export function dimColor(color: string, alpha: number): string {
    const hex = color.trim()
    const match = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(hex)
    if (match) {
        const body = match[1]
        const full = body.length === 3 ? [...body].map((char) => char + char).join('') : body
        const [r, g, b] = [0, 2, 4].map((offset) => parseInt(full.slice(offset, offset + 2), 16))
        return `rgba(${r}, ${g}, ${b}, ${alpha})`
    }
    const rgb = /^rgba?\(([^)]+)\)$/i.exec(hex)
    if (rgb) {
        const [r, g, b] = rgb[1].split(',').map((part) => part.trim())
        return `rgba(${r}, ${g}, ${b}, ${alpha})`
    }
    return color
}

export function focusedSeries(
    focused: string | null,
    name: string,
    index: number,
    theme: ChartTheme
): { color: string } | null {
    if (!focused) {
        return null
    }
    const palette = theme.colors ?? []
    const color = palette[index % Math.max(palette.length, 1)]
    if (!color) {
        return null
    }
    return { color: focused === name ? color : dimColor(color, DIMMED_ALPHA) }
}
