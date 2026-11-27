import { RefObject, useLayoutEffect, useRef, useState } from 'react'

import { ADVENT_PICTURE } from './adventGraph'

export interface AdventStageFit {
    ref: RefObject<HTMLDivElement>
    stage: { width: number; height: number }
    zoom: number
    box: { left: number; top: number; width: number; height: number }
}

export function useAdventStageFit(): AdventStageFit {
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

    const zoom = Math.min(stage.width / ADVENT_PICTURE.width, stage.height / ADVENT_PICTURE.height)
    const width = ADVENT_PICTURE.width * zoom
    const height = ADVENT_PICTURE.height * zoom

    return {
        ref,
        stage,
        zoom,
        box: { left: (stage.width - width) / 2, top: (stage.height - height) / 2, width, height },
    }
}
