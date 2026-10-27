const NEXT_ROW_KEYS = new Set(['ArrowDown', 'j'])
const PREVIOUS_ROW_KEYS = new Set(['ArrowUp', 'k'])

export type NotificationRowCommand = 'archive' | 'undo_archive' | 'toggle_read'

/** The row index a key moves focus to, or null when the key does not move it. */
export function nextRowIndex(current: number, count: number, key: string): number | null {
    if (count === 0) {
        return null
    }
    if (NEXT_ROW_KEYS.has(key)) {
        return Math.min(current + 1, count - 1)
    }
    if (PREVIOUS_ROW_KEYS.has(key)) {
        return Math.max(current - 1, 0)
    }
    return null
}

export function rowCommandForKey(key: string, shiftKey: boolean): NotificationRowCommand | null {
    if (key.toLowerCase() === 'e') {
        return shiftKey ? 'undo_archive' : 'archive'
    }
    if (key.toLowerCase() === 'u' && !shiftKey) {
        return 'toggle_read'
    }
    return null
}
