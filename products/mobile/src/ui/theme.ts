import { type ImageStyle, Platform, StyleSheet, type TextStyle, useColorScheme, type ViewStyle } from 'react-native'
import type { Accent } from '@/model/types'
import { resolveColorScheme, useAppearanceStore } from '@/ui/appearanceStore'

import { DARK_CHART_PALETTE, LIGHT_CHART_PALETTE } from './chart/palette'

export type ColorScheme = 'light' | 'dark'

export const lightColors = {
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
    /** Cards, pills, sheets, floating cards, text fields and menus. */
    surface: '#FFFFFF',
    onInk: '#FFFFFF',
    onAccent: '#FFFFFF',
    /** Literal white in both schemes: initials on avatar colors and the brand lockup only. */
    white: '#FFFFFF',
    page: '#E4E4E0',
    /** The primary call-to-action fill. Warnings, failures and destructive actions use `orange`. */
    accent: '#F54E00',
    accentHover: '#D94400',
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
    /** A neutral avatar fill behind `white` initials, such as the viewer's own avatar. */
    avatarNeutral: '#1F1F1C',
    /** The stack trace and code block card, dark in both schemes. */
    terminal: '#1F1F1C',
    onTerminal: '#F6F6F3',
    onTerminalMuted: '#B0B0AA',
    /** The outline of a `terminal` card. Light needs none, dark needs one to lift the card off the page. */
    terminalBorder: 'rgba(0,0,0,0)',
    switchOn: '#1F1F1C',
    switchOff: '#D6D6D1',
    /** The ring of an unselected radio button or checkbox. */
    control: '#D6D6D1',
    disabledFill: '#D6D6D1',
    onDisabled: '#FFFFFF',
    /** The bars of a single-series bar chart, which draws gray and highlights the selected bar. */
    barNeutral: '#D6D6D1',
} as const

export type ThemeColors = { readonly [K in keyof typeof lightColors]: string }

// Cool neutrals and an amber call to action, after the web app's dark theme.
export const darkColors: ThemeColors = {
    ink: '#F4F4F2',
    inkHover: '#E2E2DF',
    muted: '#C9CACD',
    secondary: '#B4B5BA',
    tertiary: '#8C8E95',
    disabled: '#5E6068',
    dotSeparator: '#6F727A',
    border: '#3A3C44',
    hairline: '#2E3139',
    rowDivider: '#30333B',
    sunken: '#1A1C22',
    pressed: '#2B2E37',
    segmentEmpty: '#3F4046',
    background: '#1D1F27',
    surface: '#23262E',
    onInk: '#1D1F27',
    onAccent: '#1D1F27',
    white: '#FFFFFF',
    page: '#15171D',
    accent: '#F7A503',
    accentHover: '#FFB21F',
    orange: '#FF6B35',
    orangeLight: '#FFA585',
    blue: '#6B8AFF',
    blueLight: '#9DB3FF',
    blueHover: '#86A0FF',
    blueHighlight: 'rgba(107,138,255,0.16)',
    yellow: '#F9BD2B',
    diffGreen: '#3FB950',
    diffRed: '#F85149',
    purple: '#A371F7',
    diffGreenBorder: 'rgba(63,185,80,0.45)',
    purpleBorder: 'rgba(163,113,247,0.45)',
    darkDivider: '#4A4C52',
    scrimLight: 'rgba(29,31,39,0.72)',
    scrimDark: 'rgba(0,0,0,0.55)',
    scrimChat: 'rgba(0,0,0,0.60)',
    onAccentTile: 'rgba(29,31,39,0.16)',
    onAccentDivider: 'rgba(29,31,39,0.28)',
    pressOverlay: 'rgba(255,255,255,0.12)',
    footerHairline: 'rgba(255,255,255,0.08)',
    avatarNeutral: '#8A8D96',
    terminal: '#101218',
    onTerminal: '#F4F4F2',
    onTerminalMuted: '#8C8E95',
    terminalBorder: '#2E3139',
    // The amber accent, like the web app's dark toggles.
    switchOn: '#F7A503',
    switchOff: '#3F4046',
    control: '#5E6068',
    disabledFill: '#3F4046',
    onDisabled: '#8C8E95',
    barNeutral: '#5E6068',
}

export type Shadow = Pick<
    ViewStyle,
    'shadowColor' | 'shadowOffset' | 'shadowOpacity' | 'shadowRadius' | 'elevation' | 'boxShadow'
>

export type ShadowName =
    | 'floatingBar'
    | 'fab'
    | 'actionPill'
    | 'card'
    | 'floatingSheet'
    | 'bottomSheet'
    | 'chip'
    | 'popover'

export type Shadows = Readonly<Record<ShadowName, Shadow>>

export interface Theme {
    scheme: ColorScheme
    colors: ThemeColors
    shadows: Shadows
    avatarPalette: readonly string[]
    accentColor: Readonly<Record<Accent, string>>
    swipeColors: { read: string; unread: string; onAction: string }
    /** Chart series colors; pass it to `seriesColor(index, palette)`. */
    chartPalette: readonly string[]
    /** The previous period draws gray, so it never competes with the current series for attention. */
    previousPeriodColor: string
}

const SHADOW_SPECS: Record<ShadowName, { y: number; blur: number; opacity: number; elevation: number }> = {
    floatingBar: { y: 8, blur: 24, opacity: 0.1, elevation: 6 },
    fab: { y: 8, blur: 24, opacity: 0.18, elevation: 8 },
    actionPill: { y: 6, blur: 24, opacity: 0.1, elevation: 6 },
    card: { y: 10, blur: 32, opacity: 0.14, elevation: 10 },
    floatingSheet: { y: 18, blur: 60, opacity: 0.18, elevation: 16 },
    bottomSheet: { y: -12, blur: 40, opacity: 0.18, elevation: 16 },
    chip: { y: 2, blur: 10, opacity: 0.08, elevation: 2 },
    popover: { y: 8, blur: 28, opacity: 0.12, elevation: 8 },
}

// A dark background hides a light shadow, so dark shadows are black and stronger.
const DARK_SHADOW_OPACITY_SCALE = 1.8
const DARK_SHADOW_MAX_OPACITY = 0.6

// CSS blur is roughly twice an iOS shadow radius, so the radius is half the handoff's blur. The web build gets the
// exact CSS value because react-native-web halves the look of shadowRadius.
function shadow(y: number, blur: number, opacity: number, elevation: number, scheme: ColorScheme): Shadow {
    const dark = scheme === 'dark'
    const alpha = dark ? Math.min(opacity * DARK_SHADOW_OPACITY_SCALE, DARK_SHADOW_MAX_OPACITY) : opacity
    if (Platform.OS === 'web') {
        return { boxShadow: `0px ${y}px ${blur}px ${dark ? `rgba(0,0,0,${alpha})` : `rgba(31,31,28,${alpha})`}` }
    }
    return {
        shadowColor: dark ? '#000000' : lightColors.ink,
        shadowOffset: { width: 0, height: y },
        shadowOpacity: alpha,
        shadowRadius: blur / 2,
        elevation,
    }
}

function shadowsFor(scheme: ColorScheme): Shadows {
    const entries = Object.entries(SHADOW_SPECS).map(([name, { y, blur, opacity, elevation }]) => [
        name,
        shadow(y, blur, opacity, elevation, scheme),
    ])
    return Object.fromEntries(entries) as Record<ShadowName, Shadow>
}

function buildTheme(
    scheme: ColorScheme,
    colors: ThemeColors,
    avatarPalette: readonly string[],
    chartPalette: readonly string[]
): Theme {
    return {
        scheme,
        colors,
        shadows: shadowsFor(scheme),
        avatarPalette,
        accentColor: { alert: colors.orange, opportunity: colors.blue, resolved: colors.ink },
        // `onInk` reads on both the blue and the ink fill in either scheme.
        swipeColors: { read: colors.blue, unread: colors.ink, onAction: colors.onInk },
        chartPalette,
        previousPeriodColor: colors.disabled,
    }
}

export const themes: Record<ColorScheme, Theme> = {
    light: buildTheme(
        'light',
        lightColors,
        ['#1D4AFF', '#F54E00', '#2F8F5B', '#7A4DD6', '#C2410C', '#0E7490', '#1F1F1C'],
        LIGHT_CHART_PALETTE
    ),
    dark: buildTheme(
        'dark',
        darkColors,
        ['#6B8AFF', '#FF6B35', '#3FB166', '#A371F7', '#E0612D', '#2AA7C2', '#8A8D96'],
        DARK_CHART_PALETTE
    ),
}

export function useColorSchemeName(): ColorScheme {
    const deviceScheme = useColorScheme()
    const appearance = useAppearanceStore((state) => state.appearance)
    return resolveColorScheme(appearance, deviceScheme)
}

export function useTheme(): Theme {
    return themes[useColorSchemeName()]
}

export function useColors(): ThemeColors {
    return useTheme().colors
}

type NamedStyles<T> = { [P in keyof T]: ViewStyle | TextStyle | ImageStyle }

/**
 * Builds a StyleSheet per scheme, once, and returns a hook that picks the current one. Call it at module level, like
 * `StyleSheet.create`; the factory must be pure because it runs once per scheme for the life of the app.
 */
export function createStyles<T extends NamedStyles<T>>(factory: (theme: Theme) => T): () => T {
    const sheets: Partial<Record<ColorScheme, T>> = {}
    return function useStyles(): T {
        const scheme = useColorSchemeName()
        let sheet = sheets[scheme]
        if (sheet === undefined) {
            sheet = StyleSheet.create(factory(themes[scheme]))
            sheets[scheme] = sheet
        }
        return sheet
    }
}
