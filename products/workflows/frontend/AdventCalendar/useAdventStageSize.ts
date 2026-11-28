import { RefObject, useLayoutEffect, useRef, useState } from 'react'

export interface AdventStageSize {
    ref: RefObject<HTMLDivElement>
    stage: { width: number; height: number }
}

export function useAdventStageSize(): AdventStageSize {
    const ref = useRef<HTMLDivElement>(null)
    const [stage, setStage] = useState({ width: 0, height: 0 })

    useLayoutEffect(() => {
        const element = ref.current
        if (!element) {
            return
        }
        const measure = (): void => {
            const { width, height } = element.getBoundingClientRect()
            setStage((current) => (current.width === width && current.height === height ? current : { width, height }))
        }
        measure()
        const observer = new ResizeObserver(measure)
        observer.observe(element)
        return () => observer.disconnect()
    }, [])

    return { ref, stage }
}
