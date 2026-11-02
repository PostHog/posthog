import { useRef } from 'react'
import type { AccessibilityActionInfo, View } from 'react-native'

import type { RowAnchor } from '@/features/inbox/contextMenuPlacement'
import type { RowMenuTrigger } from '@/features/inbox/useRowMenuTrigger'
import { haptic } from '@/lib/haptics'

// The inbox's `useRowMenuTrigger` takes an `InboxItem` and names its action "Show report actions", so the Views rows
// use this copy of it for their own items and words.

const ACTIONS: AccessibilityActionInfo[] = [{ name: 'longpress', label: 'Show actions' }]

/** Opens a row's context menu from a long press or the screen reader's "Show actions", anchored to the row. */
export function useMenuTrigger<T>(item: T, onOpen: (item: T, anchor: RowAnchor) => void): RowMenuTrigger {
    const ref = useRef<View>(null)
    const open = (): void => {
        ref.current?.measureInWindow((x, y, width, height) => onOpen(item, { x, y, width, height }))
    }
    return {
        ref,
        onLongPress: () => {
            haptic('light')
            open()
        },
        accessibilityActions: ACTIONS,
        onAccessibilityAction: (event) => {
            if (event.nativeEvent.actionName === 'longpress') {
                open()
            }
        },
    }
}
