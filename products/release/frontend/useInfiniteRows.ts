import { useCallback, useEffect, useRef, useState } from 'react'

const STEP = 50
const LOOKAHEAD = '600px'

export function useInfiniteRows(total: number): { visible: number; sentinel: (node: Element | null) => void } {
    const [count, setCount] = useState(STEP)
    const observer = useRef<IntersectionObserver | null>(null)
    const target = useRef<Element | null>(null)
    const visible = Math.min(count, total)
    const hasMore = visible < total

    const sentinel = useCallback((node: Element | null) => {
        observer.current?.disconnect()
        target.current = node
        if (!node) {
            return
        }
        observer.current = new IntersectionObserver(
            (entries) => {
                if (entries.some((entry) => entry.isIntersecting)) {
                    setCount((current) => current + STEP)
                }
            },
            { rootMargin: LOOKAHEAD }
        )
        observer.current.observe(node)
    }, [])

    useEffect(() => {
        const node = target.current
        if (hasMore && node && observer.current) {
            observer.current.unobserve(node)
            observer.current.observe(node)
        }
    }, [visible, hasMore])

    useEffect(() => () => observer.current?.disconnect(), [])

    return { visible, sentinel }
}
