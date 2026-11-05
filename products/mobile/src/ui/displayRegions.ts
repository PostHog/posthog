import type { ReservedRegion } from 'react-native-reserved-regions'

export interface DisplayRect {
    x: number
    y: number
    width: number
    height: number
}

export function displayPanes(bounds: DisplayRect, regions: readonly ReservedRegion[]): DisplayRect[] {
    let panes = [bounds]
    for (const region of regions) {
        const frame = region.frame
        panes = panes.flatMap((pane) => {
            const left = Math.max(pane.x, frame.x)
            const right = Math.min(pane.x + pane.width, frame.x + frame.width)
            const top = Math.max(pane.y, frame.y)
            const bottom = Math.min(pane.y + pane.height, frame.y + frame.height)
            if (left > right || top > bottom || (region.kind !== 'division' && (left === right || top === bottom)))
                return [pane]
            const candidates =
                region.kind === 'division'
                    ? frame.height > frame.width
                        ? [
                              { ...pane, width: left - pane.x },
                              { ...pane, x: right, width: pane.x + pane.width - right },
                          ]
                        : [
                              { ...pane, height: top - pane.y },
                              { ...pane, y: bottom, height: pane.y + pane.height - bottom },
                          ]
                    : [
                          { ...pane, width: left - pane.x },
                          { ...pane, x: right, width: pane.x + pane.width - right },
                          { ...pane, height: top - pane.y },
                          { ...pane, y: bottom, height: pane.y + pane.height - bottom },
                      ]
            const available = candidates.filter((candidate) => candidate.width > 0 && candidate.height > 0)
            return region.kind === 'division'
                ? available
                : available.sort((a, b) => b.width * b.height - a.width * a.height).slice(0, 1)
        })
    }
    return panes
}

export function overlayPane(
    bounds: DisplayRect,
    regions: readonly ReservedRegion[],
    anchor?: DisplayRect
): DisplayRect {
    const panes = displayPanes(bounds, regions)
    const center = anchor && { x: anchor.x + anchor.width / 2, y: anchor.y + anchor.height / 2 }
    return (
        (center &&
            panes.find(
                (pane) =>
                    center.x >= pane.x &&
                    center.x <= pane.x + pane.width &&
                    center.y >= pane.y &&
                    center.y <= pane.y + pane.height
            )) ||
        panes.at(-1) ||
        bounds
    )
}
