import { useContext } from 'react'

import type { DisplayRect } from './displayRegions'
import { OverlayFrameContext } from './overlayFrame'
import { useSceneDimensions } from './useSceneDimensions'

export function useOverlayFrame(): DisplayRect {
    const frame = useContext(OverlayFrameContext)
    const { width, height } = useSceneDimensions()
    return frame ?? { x: 0, y: 0, width, height }
}
