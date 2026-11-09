export const NAV_RAIL_WIDTH = 80
export const INBOX_PANE_WIDTH = 300
export const REPORT_MIN_WIDTH = 440
export const READING_WIDTH = 720

export function adaptiveLayout(
    width: number,
    height: number,
    left: number,
    right: number
): {
    rail: boolean
    railSide: 'left' | 'right'
    contentWidth: number
    paired: boolean
    reportNavigation: boolean
} {
    const safeWidth = Math.max(0, width - left - right)
    const enoughHeight = height >= 480
    const rail =
        enoughHeight && safeWidth >= 600 && (Math.max(left, right) >= 44 || (safeWidth >= 840 && safeWidth > height))
    const contentWidth = Math.max(0, safeWidth - (rail ? NAV_RAIL_WIDTH : 0))
    return {
        rail,
        railSide: left > right ? 'left' : 'right',
        contentWidth,
        paired: enoughHeight && contentWidth >= INBOX_PANE_WIDTH + REPORT_MIN_WIDTH,
        reportNavigation: enoughHeight && (rail || contentWidth >= 600),
    }
}
