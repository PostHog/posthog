import { RefObject, useEffect } from 'react'

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
