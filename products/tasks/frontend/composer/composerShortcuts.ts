import { RefObject, useEffect, useRef } from 'react'

import type { SessionConfigOption } from '../conversation/acp-types'
import { cycleModeOption } from './configOptions'

export interface ComposerShortcutsOptions {
    /** Escape only cancels while the agent is actively working. */
    agentBusy: boolean
    onCancel: () => void
    modeOption: SessionConfigOption | undefined
    onModeChange: (value: string) => void
    allowBypassPermissions?: boolean
    disabled?: boolean
}

export const cycleModeAndCancelGuards = {
    /**
     * Returns the next mode value when Shift+Tab should cycle the mode,
     * or undefined when the shortcut must not fire.
     */
    shouldCycleModeOnShiftTab(
        targetIsTextarea: boolean,
        modeOption: SessionConfigOption | undefined,
        disabled: boolean,
        allowBypassPermissions: boolean
    ): string | undefined {
        if (disabled || !targetIsTextarea) {
            return undefined
        }
        return cycleModeOption(modeOption, { allowBypassPermissions })
    },

    shouldCancelOnEscape(agentBusy: boolean): boolean {
        return agentBusy
    },
}

function isShiftTab(event: KeyboardEvent): boolean {
    return event.key === 'Tab' && event.shiftKey && !event.ctrlKey && !event.metaKey && !event.altKey
}

function isPlainEscape(event: KeyboardEvent): boolean {
    return event.key === 'Escape' && !event.shiftKey && !event.ctrlKey && !event.metaKey && !event.altKey
}

export function handleComposerKeyDown(event: KeyboardEvent, options: ComposerShortcutsOptions): void {
    if (isPlainEscape(event)) {
        if (!cycleModeAndCancelGuards.shouldCancelOnEscape(options.agentBusy)) {
            return
        }
        // Swallow the event entirely so surrounding modals/menus don't also close.
        event.preventDefault()
        event.stopPropagation()
        options.onCancel()
        return
    }

    if (isShiftTab(event)) {
        const nextMode = cycleModeAndCancelGuards.shouldCycleModeOnShiftTab(
            event.target instanceof HTMLTextAreaElement,
            options.modeOption,
            options.disabled ?? false,
            options.allowBypassPermissions ?? false
        )
        if (nextMode === undefined) {
            return
        }
        // Prevent default before dispatch so focus never jumps backwards.
        event.preventDefault()
        options.onModeChange(nextMode)
    }
}

/**
 * Composer keyboard shortcuts: Shift+Tab (textarea focused) cycles the mode,
 * Escape (agent busy) stops the in-flight turn. Attaches a single keydown
 * listener to the composer container; options are read through a ref so the
 * listener never goes stale and never needs re-attaching.
 */
export function useComposerShortcuts(
    containerRef: RefObject<HTMLElement | null>,
    options: ComposerShortcutsOptions
): void {
    const optionsRef = useRef(options)
    optionsRef.current = options

    useEffect(() => {
        const container = containerRef.current
        if (!container) {
            return
        }
        const onKeyDown = (event: KeyboardEvent): void => handleComposerKeyDown(event, optionsRef.current)
        container.addEventListener('keydown', onKeyDown)
        return () => container.removeEventListener('keydown', onKeyDown)
    }, [containerRef])
}
