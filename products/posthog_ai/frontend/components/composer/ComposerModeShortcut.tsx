import { useEffect } from 'react'

export interface ComposerModeShortcutProps {
    /** Fired on Shift+Tab — cycle to the next permission mode. */
    onCycle: () => void
}

/**
 * Renderless window-level Shift+Tab shortcut for cycling the composer's permission mode, matching `/code`
 * where the shortcut is global. Mount it inside the composer subtree so it detaches with the composer —
 * e.g. while a pending plan approval replaces the composer slot, whose selector owns Tab itself. Yields to
 * anything that already handled the key (`defaultPrevented`) and to open menus/dialogs, which own Tab for
 * their internal focus order.
 */
export function ComposerModeShortcut({ onCycle }: ComposerModeShortcutProps): null {
    // No dep array on purpose: re-attaching keeps the listener's `onCycle` closure current (callers pass
    // inline arrows over the selected mode) — same pattern as the plan-approval selector's shortcuts.
    useEffect(() => {
        const handleKeyDown = (e: KeyboardEvent): void => {
            if (e.key !== 'Tab' || !e.shiftKey || e.defaultPrevented) {
                return
            }
            if (e.target instanceof HTMLElement && e.target.closest('[role="menu"],[role="dialog"]')) {
                return
            }
            e.preventDefault()
            onCycle()
        }
        window.addEventListener('keydown', handleKeyDown)
        return () => window.removeEventListener('keydown', handleKeyDown)
    })
    return null
}
