import { RefObject, useEffect } from 'react'

// Today's glow pulses a few times each time the stage comes into view or its tab is shown again, then rests,
// so a stage left open costs nothing on the compositor. The attribute is set on the element itself, so waking
// the stage re-renders nothing.
export function useAdventFlowWake(stage: RefObject<HTMLElement>): void {
    useEffect(() => {
        const root = stage.current
        if (!root) {
            return
        }
        let isInView = false
        const update = (): void => {
            root.dataset.awake = String(isInView && !document.hidden)
        }
        const observer = new IntersectionObserver(([entry]) => {
            isInView = entry.isIntersecting
            update()
        })
        observer.observe(root)
        document.addEventListener('visibilitychange', update)
        return () => {
            observer.disconnect()
            document.removeEventListener('visibilitychange', update)
        }
    }, [stage])
}
