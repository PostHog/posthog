import { RefObject, useEffect } from 'react'

export function useRaisedNode(ref: RefObject<HTMLElement>, raised: boolean): void {
    useEffect(() => {
        const node = ref.current?.closest<HTMLElement>('.react-flow__node')
        if (!node || !raised) {
            return
        }
        const previous = node.style.zIndex
        node.style.zIndex = '1000'
        return () => {
            node.style.zIndex = previous
        }
    }, [ref, raised])
}
