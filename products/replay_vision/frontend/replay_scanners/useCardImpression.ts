import { RefObject, useEffect, useRef } from 'react'

// Half the card for a second: enough that the reader could have read the title, so a card scrolled past
// at speed does not count as shown and then as ignored.
const VISIBLE_RATIO = 0.5
const VISIBLE_FOR_MS = 1000

export function useCardImpression(ref: RefObject<HTMLElement | null>, onSeen: () => void): void {
    const onSeenRef = useRef(onSeen)
    onSeenRef.current = onSeen

    useEffect(() => {
        const element = ref.current
        if (!element || typeof IntersectionObserver === 'undefined') {
            return
        }
        let timer: ReturnType<typeof setTimeout> | null = null
        const observer = new IntersectionObserver(
            ([entry]) => {
                if (entry.intersectionRatio >= VISIBLE_RATIO) {
                    timer ??= setTimeout(() => {
                        observer.disconnect()
                        onSeenRef.current()
                    }, VISIBLE_FOR_MS)
                } else if (timer) {
                    clearTimeout(timer)
                    timer = null
                }
            },
            { threshold: [0, VISIBLE_RATIO] }
        )
        observer.observe(element)
        return () => {
            observer.disconnect()
            if (timer) {
                clearTimeout(timer)
            }
        }
    }, [ref])
}
