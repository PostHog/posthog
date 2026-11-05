import { useContext } from 'react'
import { useDisplayRegions } from '@/ui/displayRegionContext'

import { type DisplayRect, overlayPane } from './displayRegions'
import { OverlayFrameContext } from './overlayFrame'
import { useSceneDimensions } from './useSceneDimensions'

export function useOverlayPane(anchor?: DisplayRect): DisplayRect {
    const scene = useSceneDimensions()
    const frame = useContext(OverlayFrameContext)
    const { width, height } = frame ?? scene
    const regions = useDisplayRegions()
    const localAnchor = anchor && { ...anchor, x: anchor.x - (frame?.x ?? 0), y: anchor.y - (frame?.y ?? 0) }
    return overlayPane({ x: 0, y: 0, width, height }, regions, localAnchor)
}
