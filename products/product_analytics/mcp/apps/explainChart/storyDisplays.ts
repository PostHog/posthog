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

// The highlight draws on the vertical steps chart only.
export function insightPageShowsFunnelStory(funnelsFilter: Record<string, unknown> | null | undefined): boolean {
    const vizType = funnelsFilter?.funnelVizType
    const layout = funnelsFilter?.layout
    return (vizType === undefined || vizType === null || vizType === 'steps') && (!layout || layout === 'vertical')
}
