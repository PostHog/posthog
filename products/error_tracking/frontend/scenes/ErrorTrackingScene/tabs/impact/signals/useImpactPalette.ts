import { useMemo } from 'react'

import { useChartTheme } from 'lib/charts/hooks'
import { hexToRGBA } from 'lib/utils/colors'

// The kinds of marks a signal draws, from a broken flow to likely noise.
export type ImpactColorRole = 'broken' | 'hurting' | 'audience' | 'related' | 'noise'

export interface ImpactPalette extends Record<ImpactColorRole, string> {
    // Marks for "what usually happens", drawn behind the lens color so the lens color reads as the change.
    neutral: string
    // Text-strength marks such as a baseline tick, so they stay visible over a colored bar.
    ink: string
    // The surface behind the marks, for the ring that keeps overlapping dots apart.
    surface: string
}

// Lens marks are chart marks, so they take the chart palette and follow it between light and dark themes.
export function useImpactPalette(): ImpactPalette {
    const theme = useChartTheme()
    return useMemo(
        () => ({
            broken: theme.colors[4],
            hurting: theme.colors[11],
            audience: theme.colors[0],
            related: theme.colors[1],
            noise: theme.colors[9],
            neutral: theme.gridColor ?? theme.axisLineColor ?? theme.colors[9],
            ink: theme.axisColor ?? theme.colors[9],
            surface: theme.backgroundColor ?? theme.colors[9],
        }),
        [theme]
    )
}

// Canvas charts take a color string, not an opacity, so a lighter part needs the opacity in the color itself.
// Theme series colors are hex; the other theme colors may not be, so those fall back to color-mix.
export function fade(color: string, opacity: number): string {
    if (/^#[0-9a-fA-F]{6}$/.test(color)) {
        return hexToRGBA(color, opacity)
    }
    return `color-mix(in srgb, ${color} ${Math.round(opacity * 100)}%, transparent)`
}
