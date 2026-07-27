import { useMemo } from 'react'

import { type ChartTheme, useChartTheme } from '@posthog/quill-charts'

import type { LifecycleStatus } from '../types'

// PostHog brand palette. Canvas can't read CSS custom properties, so we hand the
// chart concrete hexes. The chart picks one per series by index; legends use the
// same array to stay in sync. Mirrors the web's --data-color-1..15 (light mode) in
// frontend/src/styles/base.scss so MCP charts match the product and series with many
// categories (e.g. retention cohorts) get distinct colors before wrapping.
export const CHART_COLORS = [
    '#1d4aff',
    '#621da6',
    '#42827e',
    '#ce0e74',
    '#f14f58',
    '#7c440e',
    '#529a0a',
    '#0476fb',
    '#fe729e',
    '#35416b',
    '#41cbc4',
    '#b64b02',
    '#e4a604',
    '#a56eff',
    '#30d5c8',
]

// Picks a palette color by index, wrapping when there are more series than colors.
export const colorAt = (index: number): string => CHART_COLORS[index % CHART_COLORS.length]!

// Single brand blue for every funnel step's converted bar — the bar height already encodes
// conversion, so distinct per-step colors would only add noise.
export const FUNNEL_COLOR = '#1d4aff'

// Conventional lifecycle bucket colors — mirrors --color-lifecycle-* in frontend/src/styles/base.scss.
export const LIFECYCLE_COLORS: Record<LifecycleStatus, string> = {
    new: '#1d4aff',
    returning: '#388600',
    resurrecting: '#a56eff',
    dormant: '#db3707',
}

export const lifecycleColor = (status: string | undefined): string =>
    LIFECYCLE_COLORS[(status ?? 'new') as LifecycleStatus] ?? LIFECYCLE_COLORS.new

// Static light fallback. Components should use useMcpChartTheme() so the canvas tracks the host theme.
export const CHART_THEME: ChartTheme = {
    colors: CHART_COLORS,
    backgroundColor: '#ffffff',
    axisColor: '#6b7280',
    gridColor: 'rgba(128, 128, 128, 0.2)',
    crosshairColor: 'rgba(128, 128, 128, 0.5)',
    tooltipBackground: '#ffffff',
    tooltipColor: '#111827',
}

// Background/axis/grid/tooltip track the host's light/dark CSS vars (bridged to quill's graph
// tokens in tailwind.css); series colors stay on the curated brand palette.
export function useMcpChartTheme(): ChartTheme {
    const base = useChartTheme()
    return useMemo(() => ({ ...base, colors: CHART_COLORS }), [base])
}
