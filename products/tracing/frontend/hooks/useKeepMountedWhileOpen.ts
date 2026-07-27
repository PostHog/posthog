import { useEffect, useRef, useState } from 'react'

// react-modal (under LemonModal/LemonDrawer) mounts a portal container the moment it
// renders, even when closed, and React 18 binds its full delegated event surface to that
// container. A modal that's rendered-but-closed therefore leaks that container + listeners
// every time it mounts/unmounts (e.g. on navigation). Gate the modal on this so a
// never-opened modal mounts no portal at all. Keep it mounted for `graceMs` after close so
// react-modal's closeTimeoutMS exit animation can finish before we unmount.
// Duplicated from products/logs/frontend/hooks (product isolation); promote to lib/hooks if a
// third product needs it.
export function useKeepMountedWhileOpen(isOpen: boolean, graceMs = 300): boolean {
    const [shouldRender, setShouldRender] = useState(isOpen)
    const timeoutRef = useRef<number | null>(null)

    useEffect(() => {
        if (timeoutRef.current !== null) {
            clearTimeout(timeoutRef.current)
            timeoutRef.current = null
        }
        if (isOpen) {
            setShouldRender(true)
            return
        }
        timeoutRef.current = window.setTimeout(() => {
            setShouldRender(false)
            timeoutRef.current = null
        }, graceMs)
        return () => {
            if (timeoutRef.current !== null) {
                clearTimeout(timeoutRef.current)
                timeoutRef.current = null
            }
        }
    }, [isOpen, graceMs])

    return shouldRender
}
