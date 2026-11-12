import type { ViewStyle } from 'react-native'

import { useOverlayPane } from './useOverlayPane'
import { useScreenInsets } from './useScreenInsets'

export function useFloatingMenuStyle(top: number, preferredWidth: number): ViewStyle {
    const pane = useOverlayPane()
    const insets = useScreenInsets()
    const gutter = 14
    const width = Math.max(0, Math.min(preferredWidth, pane.width - gutter * 2))
    const fittedTop = Math.max(pane.y + gutter, Math.min(top, pane.y + pane.height - 120))
    return {
        left: pane.x + pane.width - width - gutter,
        right: undefined,
        top: fittedTop,
        width,
        maxHeight: Math.max(0, pane.y + pane.height - insets.bottom - gutter - fittedTop),
    }
}
