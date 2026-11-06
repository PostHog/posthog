const INSIGHT_PAGE_DISPLAYS = new Set<unknown>([
    'ActionsLineGraph',
    'ActionsBar',
    'ActionsUnstackedBar',
    'ActionsAreaGraph',
    'ActionsStackedBar',
])

export function insightPageShowsStory(display: unknown): boolean {
    return display === undefined || display === null || INSIGHT_PAGE_DISPLAYS.has(display)
}
