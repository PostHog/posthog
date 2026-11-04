import { useContext, useLayoutEffect, useRef } from 'react'
import { useReservedRegions } from 'react-native-reserved-regions'

import { overlayPane } from '@/ui/displayRegions'
import { OverlayFrameContext } from '@/ui/overlayFrame'
import { useSceneDimensions } from '@/ui/useSceneDimensions'
import { useScreenInsets } from '@/ui/useScreenInsets'

import { placeAnchoredMenu, type RowAnchor } from './contextMenuPlacement'

export function useContextMenuLayout(
    anchor: RowAnchor,
    visible: boolean,
    onClose: () => void,
    width: number,
    height: number
): ReturnType<typeof placeAnchoredMenu> {
    const scene = useSceneDimensions()
    const host = useContext(OverlayFrameContext)
    const frame = host ?? { x: 0, y: 0, width: scene.width, height: scene.height }
    const regions = useReservedRegions()
    const insets = useScreenInsets()
    const close = useRef(onClose)
    close.current = onClose
    const layoutKey = JSON.stringify([frame, regions, insets])
    const previous = useRef(layoutKey)
    useLayoutEffect(() => {
        if (previous.current !== layoutKey && visible) close.current()
        previous.current = layoutKey
    }, [layoutKey, visible])
    const bounds = {
        x: 0,
        y: insets.top,
        width: frame.width,
        height: Math.max(0, frame.height - insets.top - insets.bottom),
    }
    const localAnchor = { ...anchor, x: anchor.x - frame.x, y: anchor.y - frame.y }
    const pane = overlayPane(bounds, regions, localAnchor)
    return placeAnchoredMenu({ anchor, frame, pane, width, height })
}
