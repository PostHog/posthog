import { Platform } from 'react-native'
import { useSafeAreaInsets } from 'react-native-safe-area-context'

import { layout } from './tokens'

export interface ScreenInsets {
    top: number
    bottom: number
}

// The web build has no insets, so it uses the prototype frame's status bar and home indicator to look like a phone.
export function useScreenInsets(): ScreenInsets {
    const insets = useSafeAreaInsets()
    if (Platform.OS === 'web') {
        return {
            top: Math.max(insets.top, layout.designStatusBar),
            bottom: Math.max(insets.bottom, layout.designHomeIndicator),
        }
    }
    return { top: insets.top, bottom: insets.bottom }
}

export function topOffset(insets: ScreenInsets, designTop: number): number {
    return insets.top + designTop - layout.designStatusBar
}

export function bottomOffset(insets: ScreenInsets, designBottom: number): number {
    return Math.max(insets.bottom + designBottom - layout.designHomeIndicator, layout.minBottomPadding)
}
