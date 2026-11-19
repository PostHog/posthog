import { useCallback, useEffect, useState } from 'react'

export function useNearTableEnd(
    root: HTMLElement | null,
    rootMargin: string
): { ref: (node: Element | null) => void; inView: boolean } {
    const [target, setTarget] = useState<Element | null>(null)
    const [inView, setInView] = useState(false)
    const ref = useCallback((node: Element | null) => setTarget(node), [])

    useEffect(() => {
        if (!root || !target) {
            setInView(false)
            return
        }
        const observer = new IntersectionObserver(
            (entries) => setInView(entries.some((entry) => entry.isIntersecting)),
            { root, rootMargin }
        )
        observer.observe(target)
        return () => observer.disconnect()
    }, [root, target, rootMargin])

    return { ref, inView }
}
