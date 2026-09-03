import { TeamPublicType, TeamType } from '~/types'

// Every heatmap screenshot request carries this header, so a bot protection rule can permit our
// render without permitting headless browsers broadly. The name is a public contract: a rename
// breaks every customer rule that matches it. Keep both constants in step with
// products/web_analytics/backend/tasks/heatmap_screenshot.py.
export const HEATMAP_SCREENSHOT_HEADER = 'X-PostHog-Heatmap-Screenshot'
export const HEATMAP_SCREENSHOT_HEADER_DEFAULT_VALUE = '1'

/** The header value this project's screenshots carry: its own secret, or the public default. */
export function heatmapScreenshotHeaderValue(team: TeamType | TeamPublicType | null): string {
    const secret = team && 'heatmaps_screenshot_secret' in team ? team.heatmaps_screenshot_secret : null
    return secret ?? HEATMAP_SCREENSHOT_HEADER_DEFAULT_VALUE
}
