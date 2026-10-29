import { Platform, type TextStyle } from 'react-native'

import { lightColors } from './theme'

// Brand bands, the same in both schemes. The app icons for internal builds use the same colors
// (scripts/make_variant_icons.py).
export const environmentRibbonColors = {
    development: { background: lightColors.yellow, text: lightColors.ink },
    preview: { background: '#7A4DD6', text: lightColors.white },
} as const

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
