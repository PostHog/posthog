import { useEffect } from 'react'

export function useElementHeight(node: HTMLElement | null, onHeight: (height: number) => void): void {
    useEffect(() => {
        if (!node) {
            return
        }
        const observer = new ResizeObserver(() => onHeight(node.offsetHeight))
        observer.observe(node)
        return () => {
            observer.disconnect()
            onHeight(0)
        }
    }, [node, onHeight])
}
