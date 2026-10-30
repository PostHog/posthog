import { type RefObject, useRef } from 'react'
import type { AccessibilityActionEvent, AccessibilityActionInfo, View } from 'react-native'

import { haptic } from '@/lib/haptics'
import type { InboxItem } from '@/model/types'

import type { RowAnchor } from './contextMenuPlacement'

const ROW_ACCESSIBILITY_ACTIONS: AccessibilityActionInfo[] = [{ name: 'longpress', label: 'Show report actions' }]

export interface RowMenuTrigger {
    ref: RefObject<View | null>
    onLongPress: () => void
    accessibilityActions: AccessibilityActionInfo[]
    onAccessibilityAction: (event: AccessibilityActionEvent) => void
}

/** Opens the row's context menu from a long press or the screen reader's "Show report actions", anchored to the row. */
export function useRowMenuTrigger(
    item: InboxItem,
    onOpen: (item: InboxItem, anchor: RowAnchor) => void
): RowMenuTrigger {
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
        accessibilityActions: ROW_ACCESSIBILITY_ACTIONS,
        onAccessibilityAction: (event) => {
            if (event.nativeEvent.actionName === 'longpress') {
                open()
            }
        },
    }
}
