import { RefObject, useLayoutEffect, useRef, useState } from 'react'

import { ADVENT_PICTURE } from './adventGraph'

const PHONE_STAGE_WIDTH = 480

export interface AdventStageFit {
    ref: RefObject<HTMLDivElement>
    stage: { width: number; height: number }
    zoom: number
    box: { left: number; top: number; width: number; height: number }
    scrollsSideways: boolean
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

    const scrollsSideways = stage.width < PHONE_STAGE_WIDTH && stage.height > stage.width
    const fillHeight = stage.height / ADVENT_PICTURE.height
    const zoom = scrollsSideways ? fillHeight : Math.min(stage.width / ADVENT_PICTURE.width, fillHeight)
    const width = ADVENT_PICTURE.width * zoom
    const height = ADVENT_PICTURE.height * zoom

    return {
        ref,
        stage,
        zoom,
        box: { left: Math.max(0, (stage.width - width) / 2), top: (stage.height - height) / 2, width, height },
        scrollsSideways,
    }
}
