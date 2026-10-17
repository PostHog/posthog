import { Platform, type TextStyle, type ViewStyle } from 'react-native'

import type { Accent } from '@/model/types'

export const colors = {
    ink: '#1F1F1C',
    inkHover: '#2B2B29',
    muted: '#55554F',
    secondary: '#6B6B65',
    tertiary: '#8A8A84',
    disabled: '#B0B0AA',
    dotSeparator: '#A3A39D',
    border: '#D6D6D1',
    hairline: '#E4E4E0',
    rowDivider: '#E6E6E1',
    sunken: '#F0F0ED',
    pressed: '#ECECE9',
    segmentEmpty: '#DADAD5',
    background: '#F6F6F3',
    white: '#FFFFFF',
    page: '#E4E4E0',
    orange: '#F54E00',
    orangeLight: '#F7A07A',
    blue: '#1D4AFF',
    blueLight: '#7C9BFF',
    blueHover: '#1639C9',
    blueHighlight: 'rgba(29,74,255,0.10)',
    yellow: '#F9BD2B',
    diffGreen: '#1A7F37',
    diffRed: '#CF222E',
    purple: '#8250DF',
    diffGreenBorder: 'rgba(26,127,55,0.4)',
    purpleBorder: 'rgba(130,80,223,0.4)',
    darkDivider: '#3A3A3A',
    scrimLight: 'rgba(246,246,243,0.72)',
    scrimDark: 'rgba(31,31,28,0.38)',
    scrimChat: 'rgba(31,31,28,0.45)',
    onAccentTile: 'rgba(255,255,255,0.22)',
    onAccentDivider: 'rgba(255,255,255,0.35)',
    pressOverlay: 'rgba(0,0,0,0.12)',
    footerHairline: 'rgba(31,31,28,0.06)',
} as const

export type ColorToken = keyof typeof colors

export const swipeColors = {
    read: colors.blue,
    unread: colors.ink,
    onAction: colors.white,
} as const

// The app icons for internal builds use the same band colors (scripts/make_variant_icons.py).
export const environmentRibbonColors = {
    development: { background: colors.yellow, text: colors.ink },
    preview: { background: '#7A4DD6', text: colors.white },
} as const

export const avatarPalette = ['#1D4AFF', '#F54E00', '#2F8F5B', '#7A4DD6', '#C2410C', '#0E7490', '#1F1F1C'] as const

export const accentColor: Record<Accent, string> = {
    alert: colors.orange,
    opportunity: colors.blue,
    resolved: colors.ink,
}

const BASE_LINE_HEIGHT = 1.4

export function lineHeight(fontSize: number, ratio: number = BASE_LINE_HEIGHT): number {
    return Math.round(fontSize * ratio * 100) / 100
}

/** React Native letter spacing is in points, so the handoff's em values are converted per size. */
export function letterSpacing(fontSize: number, em: number): number {
    return Math.round(fontSize * em * 100) / 100
}

export const fonts = {
    mono: Platform.select({
        ios: 'Menlo',
        android: 'monospace',
        default: "'SF Mono', Menlo, Consolas, monospace",
    }),
} as const

function text(
    fontSize: number,
    fontWeight: TextStyle['fontWeight'],
    options: { lineHeightRatio?: number; em?: number } = {}
): TextStyle {
    return {
        fontSize,
        fontWeight,
        lineHeight: lineHeight(fontSize, options.lineHeightRatio),
        ...(options.em === undefined ? {} : { letterSpacing: letterSpacing(fontSize, options.em) }),
    }
}

export const type = {
    screenTitle: text(28, '700', { em: -0.015 }),
    headline: text(22, '700', { lineHeightRatio: 1.25, em: -0.02 }),
    sheetTitle: text(18, '700', { em: -0.01 }),
    sheetTitleLarge: text(20, '700', { em: -0.01 }),
    sectionHeader: text(17, '600', { em: -0.01 }),
    rowTitle: text(16, '600', { lineHeightRatio: 1.3 }),
    body: text(16, '400'),
    bodyStrong: text(16, '600'),
    bodySmall: text(15, '400', { lineHeightRatio: 1.45 }),
    bodySmallStrong: text(15, '600'),
    label: text(16, '400'),
    input: text(16, '400'),
    meta: text(13, '400', { lineHeightRatio: 1.3 }),
    metaSmall: text(14, '400'),
    eyebrow: text(12, '600', { em: 0.08 }),
    mono: { ...text(12, '400', { lineHeightRatio: 1.6 }), fontFamily: fonts.mono },
    monoSmall: { ...text(11, '400'), fontFamily: fonts.mono },
    button: text(16, '600'),
    buttonLarge: text(17, '600'),
    buttonSmall: text(15, '600'),
    menuRow: text(16, '500'),
} as const satisfies Record<string, TextStyle>

export const iconSizes = {
    small: 14,
    inline: 16,
    control: 20,
    navigation: 24,
    empty: 28,
} as const

export const space = {
    2: 2,
    3: 3,
    4: 4,
    6: 6,
    8: 8,
    10: 10,
    12: 12,
    14: 14,
    16: 16,
    18: 18,
    20: 20,
    24: 24,
    28: 28,
    36: 36,
} as const

export const radii = {
    pill: 999,
    sheet: 22,
    floating: 28,
    card: 12,
    softCard: 22,
    menuRow: 18,
    option: 14,
    tile: 10,
    markSmall: 6,
    markLarge: 9,
} as const

export const layout = {
    inboxGutter: 14,
    detailGutter: 20,
    actionBarGutter: 16,
    minTapTarget: 44,
    /** Status bar height in the prototype frame. Top paddings in the handoff include it. */
    designStatusBar: 54,
    /** Home indicator height in the prototype frame. Bottom paddings in the handoff include it. */
    designHomeIndicator: 34,
    /** Smallest bottom padding, for devices with a home button, where the safe-area inset is 0. */
    minBottomPadding: 16,
    /** Opacity of the background tint over the blur behind floating chrome, so the blurred content shows through. */
    chromeTint: 0.72,
} as const

type Shadow = Pick<
    ViewStyle,
    'shadowColor' | 'shadowOffset' | 'shadowOpacity' | 'shadowRadius' | 'elevation' | 'boxShadow'
>

// CSS blur is roughly twice an iOS shadow radius, so the radius is half the handoff's blur. The web build gets the
// exact CSS value because react-native-web halves the look of shadowRadius.
function shadow(y: number, blur: number, opacity: number, elevation: number): Shadow {
    if (Platform.OS === 'web') {
        return { boxShadow: `0px ${y}px ${blur}px rgba(31,31,28,${opacity})` }
    }
    return {
        shadowColor: colors.ink,
        shadowOffset: { width: 0, height: y },
        shadowOpacity: opacity,
        shadowRadius: blur / 2,
        elevation,
    }
}

export const shadows = {
    floatingBar: shadow(8, 24, 0.1, 6),
    fab: shadow(8, 24, 0.18, 8),
    actionPill: shadow(6, 24, 0.1, 6),
    card: shadow(10, 32, 0.14, 10),
    floatingSheet: shadow(18, 60, 0.18, 16),
    bottomSheet: shadow(-12, 40, 0.18, 16),
    chip: shadow(2, 10, 0.08, 2),
    popover: shadow(8, 28, 0.12, 8),
} as const

// Text fields draw their own container, so the web build removes the browser focus ring. Only `outline-style: none`
// does that, and React Native's style types do not list `none`.
export const inputReset: TextStyle = Platform.OS === 'web' ? ({ outlineStyle: 'none' } as unknown as TextStyle) : {}

// Keeps the last line of headlines from being a single word. iOS gets this from `lineBreakStrategyIOS="standard"`;
// the web build gets CSS `text-wrap: pretty`, which React Native's style types do not list.
export const prettyWrap: TextStyle = Platform.OS === 'web' ? ({ textWrap: 'pretty' } as TextStyle) : {}

export const motion = {
    fade: 180,
    sheet: 200,
    chevron: 200,
    menu: 220,
    emphasizedBezier: [0.2, 0.8, 0.2, 1] as const,
    easeOutBezier: [0, 0, 0.58, 1] as const,
} as const
