import { type ReactNode, type RefObject, useLayoutEffect, useRef } from 'react'

import { useEventListener } from 'lib/hooks/useEventListener'
import posthog from 'lib/posthog-typed'

// The optimistic and attached views remount; keep ancestor-focus ownership through that swap.
const lastChatFocus = new WeakMap<Document, { key: string; ownsFocus: boolean }>()

function isVisible(element: Element | null): boolean {
    return (
        !!element &&
        !element.closest('[hidden], [inert], [aria-hidden="true"]') &&
        element.getClientRects().length > 0 &&
        getComputedStyle(element).visibility !== 'hidden'
    )
}

export interface RunEscapeBoundaryProps {
    scope: 'chat' | 'composer'
    focusKey?: string
    textAreaRef?: RefObject<HTMLTextAreaElement>
    onEscape: () => void
    disabled?: boolean
    className?: string
    children: ReactNode
}

export function RunEscapeBoundary({
    scope,
    focusKey,
    textAreaRef,
    onEscape,
    disabled = false,
    className,
    children,
}: RunEscapeBoundaryProps): JSX.Element {
    const containerRef = useRef<HTMLDivElement>(null)
    const ownsAncestorFocus = useRef(false)

    useLayoutEffect(() => {
        // The submitted composer must unmount before we inspect where its focus landed.
        const previousFocus = lastChatFocus.get(document)
        ownsAncestorFocus.current =
            scope === 'chat' &&
            document.activeElement === document.body &&
            (!focusKey || previousFocus?.key !== focusKey || previousFocus.ownsFocus)
    }, [focusKey, scope])

    const recordFocus = (target: EventTarget | null): void => {
        ownsAncestorFocus.current = target instanceof Node && !!containerRef.current?.contains(target)
        if (focusKey && scope === 'chat') {
            lastChatFocus.set(document, { key: focusKey, ownsFocus: ownsAncestorFocus.current })
        }
    }

    useEventListener('pointerdown', (event) => {
        recordFocus(event.target)
    })
    useEventListener('focusin', (event) => {
        // Clicking noninteractive transcript text can focus a tabindex ancestor outside this boundary.
        if (event.target instanceof Node && !event.target.contains(containerRef.current)) {
            recordFocus(event.target)
        }
    })
    useEventListener('keydown', (event) => {
        const container = containerRef.current
        const target = event.target
        if (
            event.key !== 'Escape' ||
            disabled ||
            !container ||
            !(target instanceof HTMLElement) ||
            target.closest('.hotkey-block') ||
            event.defaultPrevented ||
            event.repeat ||
            event.isComposing ||
            event.metaKey ||
            event.ctrlKey ||
            event.altKey ||
            event.shiftKey ||
            !isVisible(container) ||
            isVisible(container.querySelector('[data-attr="run-queue-editor"]')) ||
            [...document.querySelectorAll('[role="menu"], [role="dialog"], [role="listbox"]')].some(isVisible)
        ) {
            return
        }
        const composerFocused =
            !!textAreaRef?.current?.closest('form')?.contains(target) && !target.closest('[hidden], [inert]')
        const approvalFocused = container.contains(target) && !!target.closest('[data-attr="run-approval"]')
        if (
            (target !== textAreaRef?.current &&
                target.closest(
                    'input, textarea, select, [contenteditable]:not([contenteditable="false"]), .monaco-editor'
                )) ||
            (scope === 'composer'
                ? !composerFocused && !approvalFocused
                : !container.contains(target) && !(target.contains(container) && ownsAncestorFocus.current))
        ) {
            return
        }
        event.preventDefault()
        if (posthog.__loaded) {
            posthog.capture('keybind triggered', { keybind: 'escape', mechanism: 'hotkey' })
        }
        onEscape()
    })

    return (
        <div ref={containerRef} data-run-escape-scope={scope} className={className}>
            {children}
        </div>
    )
}
