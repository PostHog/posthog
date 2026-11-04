import { Platform } from 'react-native'
import { useSafeAreaInsets } from 'react-native-safe-area-context'

import { layout } from './tokens'

export interface ScreenInsets {
    top: number
    bottom: number
    left: number
    right: number
}

// The web build has no insets, so it uses the prototype frame's status bar and home indicator to look like a phone.
export function useScreenInsets(): ScreenInsets {
    const insets = useSafeAreaInsets()
    if (Platform.OS === 'web') {
        return {
            left: insets.left,
            right: insets.right,
            top: Math.max(insets.top, layout.designStatusBar),
            bottom: Math.max(insets.bottom, layout.designHomeIndicator),
        }
    }
    return insets
}

export function topOffset(insets: Pick<ScreenInsets, 'top'>, designTop: number): number {
    return Math.max(insets.top, layout.minTopInset) + designTop - layout.designStatusBar
}

export function bottomOffset(insets: Pick<ScreenInsets, 'bottom'>, designBottom: number): number {
    return Math.max(insets.bottom + designBottom - layout.designHomeIndicator, layout.minBottomPadding)
}

export function tabBottomOffset(insets: Pick<ScreenInsets, 'bottom'>): number {
    return Platform.OS === 'ios' ? insets.bottom + layout.minBottomPadding : bottomOffset(insets, 120)
}
