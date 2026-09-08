import type { RefObject } from 'react'

import { useKeyboardHotkeys } from 'lib/hooks/useKeyboardHotkeys'

export function ComposerSteerShortcut({
    textAreaRef,
    onSteer,
    disabled,
}: {
    textAreaRef: RefObject<HTMLTextAreaElement>
    onSteer: () => void
    disabled: boolean
}): null {
    useKeyboardHotkeys({
        escape: {
            disabled,
            willHandleEvent: true,
            action: (event) => {
                if (
                    event.defaultPrevented ||
                    event.repeat ||
                    event.isComposing ||
                    event.metaKey ||
                    event.ctrlKey ||
                    event.altKey ||
                    event.shiftKey ||
                    event.target !== textAreaRef.current ||
                    textAreaRef.current?.closest('[hidden], [inert]') ||
                    textAreaRef.current?.closest('form')?.querySelector('[data-attr="run-queue-editor"]') ||
                    [...document.querySelectorAll('[role="menu"], [role="dialog"], [role="listbox"]')].some(
                        (overlay) =>
                            !overlay.closest('[hidden], [inert], [aria-hidden="true"]') &&
                            overlay.getClientRects().length > 0 &&
                            getComputedStyle(overlay).visibility !== 'hidden'
                    )
                ) {
                    return
                }
                event.preventDefault()
                onSteer()
            },
        },
    })
    return null
}
