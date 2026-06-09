import { type ChartTheme } from '@posthog/quill-charts'

import type { LifecycleStatus } from '../types'

// PostHog brand palette. Canvas can't read CSS custom properties, so we hand the
// chart concrete hexes. The chart picks one per series by index; legends use the
// same array to stay in sync.
export const CHART_COLORS = [
    '#1d4aff', // PostHog blue
    '#621da6', // PostHog purple
    '#00d683', // PostHog green
    '#f54e00', // PostHog orange
    '#f7a501', // PostHog yellow
    '#dc2626', // red
]

// Single brand blue for every funnel step's converted band — the bar length already encodes
// conversion, so distinct per-step colors would only add noise.
export const FUNNEL_COLOR = '#1d4aff'
// Light grey drop-off filler — matches the web chart's `--color-border-primary` fallback.
export const FILLER_COLOR = 'rgba(0, 0, 0, 0.08)'

// Conventional lifecycle bucket colors — mirrors --color-lifecycle-* in frontend/src/styles/base.scss.
export const LIFECYCLE_COLORS: Record<LifecycleStatus, string> = {
    new: '#1d4aff',
    returning: '#388600',
    resurrecting: '#a56eff',
    dormant: '#db3707',
}

export const lifecycleColor = (status: string | undefined): string =>
    LIFECYCLE_COLORS[(status ?? 'new') as LifecycleStatus] ?? LIFECYCLE_COLORS.new

// Single mid-gray for axis labels — readable on both light and dark hosts. Claude
// Desktop's iframe doesn't set `prefers-color-scheme`, so we can't detect the host
// theme and adapt at runtime.
export const CHART_THEME: ChartTheme = {
    colors: CHART_COLORS,
    backgroundColor: '#ffffff',
    axisColor: '#9ca3af',
    gridColor: 'rgba(128, 128, 128, 0.2)',
    crosshairColor: 'rgba(128, 128, 128, 0.5)',
    tooltipBackground: '#ffffff',
    tooltipColor: '#111827',
}
