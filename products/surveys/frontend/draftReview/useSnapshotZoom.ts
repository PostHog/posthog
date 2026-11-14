import { useState } from 'react'

import type { ReadySiteSnapshot } from './surveySiteSnapshotLogic'

const MAX_SCALE = 2
// Zooming out by steps lands a hair above the fit scale in floating point, which still counts as fit.
const FIT_TOLERANCE = 1.001

export interface SnapshotZoom {
    // null until the page image has loaded and the frame has a size.
    scale: number | null
    pageHeight: number | null
    isFit: boolean
    isMax: boolean
    zoomBy: (factor: number) => void
    zoomTo: (target: number | 'fit') => void
    onPageLoad: (image: HTMLImageElement) => void
}

function clampZoom(next: number, fitScale: number): number | 'fit' {
    const clamped = Math.min(MAX_SCALE, next)
    return clamped <= fitScale * FIT_TOLERANCE ? 'fit' : clamped
}

// Page size and zoom belong to one image, so a new snapshot starts from its own size at fit.
export function useSnapshotZoom(
    snapshot: ReadySiteSnapshot | null,
    frame: { width: number; height: number }
): SnapshotZoom {
    const [loadedPage, setLoadedPage] = useState<{ imageUrl: string; height: number } | null>(null)
    const [zoomState, setZoomState] = useState<{ imageUrl: string; zoom: number | 'fit' } | null>(null)

    const imageUrl = snapshot?.imageUrl
    const pageWidth = snapshot?.viewportWidth ?? 0
    const pageHeight = imageUrl && loadedPage?.imageUrl === imageUrl ? loadedPage.height : null
    const zoom = imageUrl && zoomState?.imageUrl === imageUrl ? zoomState.zoom : 'fit'
    const fitScale =
        pageWidth && pageHeight && frame.width ? Math.min(frame.width / pageWidth, frame.height / pageHeight, 1) : null
    const scale = fitScale === null ? null : zoom === 'fit' ? fitScale : Math.max(fitScale, zoom)

    return {
        scale,
        pageHeight,
        isFit: scale === fitScale,
        isMax: scale !== null && scale >= MAX_SCALE,
        zoomTo: (target) => {
            if (imageUrl && fitScale !== null) {
                setZoomState({ imageUrl, zoom: target === 'fit' ? 'fit' : clampZoom(target, fitScale) })
            }
        },
        zoomBy: (factor) => {
            if (imageUrl && fitScale !== null) {
                setZoomState((previous) => {
                    const current =
                        previous?.imageUrl === imageUrl && previous.zoom !== 'fit'
                            ? Math.max(fitScale, previous.zoom)
                            : fitScale
                    return { imageUrl, zoom: clampZoom(current * factor, fitScale) }
                })
            }
        },
        onPageLoad: (image) => {
            if (imageUrl) {
                setLoadedPage({ imageUrl, height: (pageWidth * image.naturalHeight) / image.naturalWidth })
            }
        },
    }
}
