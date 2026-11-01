export const screenLayout = {
    top: 58,
    rowHeight: 46,
    bottomPadding: 10,
    titleGap: 20,
} as const

export const SCREEN_CHROME_BOTTOM = screenLayout.top + screenLayout.rowHeight + screenLayout.bottomPadding
export const SCREEN_CONTENT_TOP = screenLayout.top + screenLayout.rowHeight + screenLayout.titleGap
