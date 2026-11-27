import type { TextStyle } from 'react-native'

/**
 * The feed draws over video, which is dark in both schemes like the existing player (`media`), so its chrome is a dark
 * translucent glass with white text in both. Sheets and menus opened from it follow the scheme.
 */
export const feedColors = {
    stage: '#000000',
    glass: 'rgba(22,22,26,0.5)',
    glassStrong: 'rgba(22,22,26,0.72)',
    glassBorder: 'rgba(255,255,255,0.16)',
    glassPressed: 'rgba(255,255,255,0.22)',
    text: '#FFFFFF',
    textMuted: 'rgba(255,255,255,0.78)',
    textFaint: 'rgba(255,255,255,0.56)',
    textSoft: 'rgba(255,255,255,0.7)',
    accent: '#F54E00',
    live: '#3FB950',
    track: 'rgba(255,255,255,0.3)',
    fill: '#FFFFFF',
    rage: '#FF8A4C',
    error: '#FF5C5C',
    key: '#F9BD2B',
    custom: '#9DB3FF',
    ambientDim: 'rgba(0,0,0,0.62)',
} as const

export const feedTextShadow: TextStyle = {
    textShadowColor: 'rgba(0,0,0,0.55)',
    textShadowOffset: { width: 0, height: 1 },
    textShadowRadius: 6,
}

export type TickKind = 'rage' | 'error' | 'key' | 'custom'

export const tickColors: Record<TickKind, string> = {
    rage: feedColors.rage,
    error: feedColors.error,
    key: feedColors.key,
    custom: feedColors.custom,
}
