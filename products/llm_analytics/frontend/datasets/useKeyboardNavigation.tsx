import { createRef, useEffect, useRef, useState } from 'react'

export function useKeyboardNavigation<R extends HTMLElement = HTMLElement, I extends HTMLElement = HTMLElement>(
    itemCount: number,
    defaultFocusedItemIndex: number = 0,
    { enabled = true } = {}
): {
    referenceRef: React.RefObject<R>
    itemsRef: React.RefObject<React.RefObject<I>[]>
    focusedItemIndex: number
} {
    const [focusedItemIndex, setFocusedItemIndex] = useState(-1)
    const referenceRef = useRef<R>(null)
    const itemsRef = useRef(Array.from({ length: itemCount }, () => createRef<I>()))

    useEffect(() => {
        setFocusedItemIndex(defaultFocusedItemIndex)
    }, [defaultFocusedItemIndex])

    const stableListener = useRef<(e: KeyboardEvent) => void>(() => {})
    useEffect(() => {
        function focus(newIndex: number): void {
            itemsRef.current[newIndex].current?.focus()
        }

        stableListener.current = (e: KeyboardEvent) => {
            if (e.key === 'ArrowDown') {
                if (focusedItemIndex < itemCount - 1) {
                    focus(focusedItemIndex + 1)
                    setFocusedItemIndex(focusedItemIndex + 1)
                    e.preventDefault() // Prevents scroll
                }
            } else if (e.key === 'ArrowUp') {
                if (focusedItemIndex > 0) {
                    focus(focusedItemIndex - 1)
                    setFocusedItemIndex(focusedItemIndex - 1)
                    e.preventDefault() // Prevents scroll
                }
            }
        }
    }, [itemCount, focusedItemIndex, setFocusedItemIndex])

    useEffect(() => {
        if (!enabled) {
            return
        }
        const handleKeyDown = (e: KeyboardEvent): void => {
            stableListener.current(e)
        }
        referenceRef.current?.addEventListener('keydown', handleKeyDown)
        return () => {
            referenceRef.current?.removeEventListener('keydown', handleKeyDown)
        }
    }, [enabled])

    return { referenceRef, itemsRef, focusedItemIndex }
}
