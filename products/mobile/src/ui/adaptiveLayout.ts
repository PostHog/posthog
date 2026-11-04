import type { ReservedRegion } from 'react-native-reserved-regions'
import { displayPanes } from './displayRegions'
export const NAV_RAIL_WIDTH = 80
export const INBOX_PANE_WIDTH = 300
export const REPORT_MIN_WIDTH = 440
export const READING_WIDTH = 720

export function adaptiveLayout(
    width: number,
    height: number,
    left: number,
    right: number,
    regions: readonly ReservedRegion[] = [],
    nativeNavigation = false
): {
    rail: boolean
    railSide: 'left' | 'right'
    contentWidth: number
    paired: boolean
    reportNavigation: boolean
    inboxExtent: number
    paneGap: number
    paneAxis: 'row' | 'column'
} {
    const safeWidth = Math.max(0, width - left - right)
    const enoughHeight = height >= 480
    const rail =
        !nativeNavigation &&
        enoughHeight &&
        safeWidth >= 600 &&
        (Math.max(left, right) >= 44 || (safeWidth >= 840 && safeWidth > height))
    const contentWidth = Math.max(0, safeWidth - (rail ? NAV_RAIL_WIDTH : 0))
    const panes = displayPanes(
        { x: 0, y: 0, width: contentWidth, height },
        regions.filter((region) => region.kind === 'division')
    )
    const primary = panes[0]
    const detail = panes[1]
    const vertical = !!detail && detail.x > (primary?.x ?? 0)
    const foldPair =
        !!primary &&
        !!detail &&
        (vertical
            ? primary.width >= 280 && detail.width >= 320 && enoughHeight
            : contentWidth >= 320 && primary.height >= 240 && detail.height >= 300)
    return {
        rail,
        railSide: left > right ? 'left' : 'right',
        contentWidth,
        paired: detail ? foldPair : enoughHeight && contentWidth >= INBOX_PANE_WIDTH + REPORT_MIN_WIDTH,
        reportNavigation: !nativeNavigation && enoughHeight && (rail || contentWidth >= 600),
        inboxExtent: foldPair && primary ? (vertical ? primary.width : primary.height) : INBOX_PANE_WIDTH,
        paneGap: foldPair && primary && detail ? (vertical ? detail.x - primary.width : detail.y - primary.height) : 0,
        paneAxis: foldPair && !vertical ? 'column' : 'row',
    }
}
