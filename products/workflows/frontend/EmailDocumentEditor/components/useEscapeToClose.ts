import { useEffect } from 'react'

/** Popovers don't close on Escape, and the fullscreen editor would otherwise take the key at the window and close. */
export function useEscapeToClose(open: boolean, close: () => void): void {
    useEffect(() => {
        if (!open) {
            return
        }
        const onKeyDown = (event: KeyboardEvent): void => {
            if (event.key === 'Escape') {
                event.preventDefault()
                event.stopImmediatePropagation()
                close()
            }
        }
        window.addEventListener('keydown', onKeyDown, true)
        return () => window.removeEventListener('keydown', onKeyDown, true)
    }, [open, close])
}
