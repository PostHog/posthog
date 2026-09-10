import type { HeatmapScreenshotSettingsApi } from '../generated/api.schemas'

export const HEATMAP_SCREENSHOT_COOKIE_NAME = '__ph_heatmap_render'

export function screenshotAccessNotice(
    url: string | null,
    settings: HeatmapScreenshotSettingsApi | null
): string | null {
    if (!url || !settings) {
        return null
    }
    try {
        const parsed = new URL(url)
        if (!['http:', 'https:'].includes(parsed.protocol)) {
            return null
        }
        if (parsed.protocol !== 'https:') {
            return 'This screenshot will run without a bypass cookie because the page uses HTTP. Use an approved HTTPS hostname if the page needs a bot protection exception.'
        }
        if (!settings.has_secret || !settings.allowed_hostnames.includes(parsed.hostname)) {
            return 'This screenshot will run without a bypass cookie. If bot protection blocks the page, ask a project admin to approve this hostname and configure the screenshot cookie.'
        }
    } catch {
        return null
    }
    return null
}

export function screenshotHostnameSuggestions(appUrls: string[]): string[] {
    return [
        ...new Set(
            appUrls.flatMap((url) => {
                try {
                    const { hostname, protocol } = new URL(url)
                    return ['http:', 'https:'].includes(protocol) &&
                        /^[a-z0-9-]+(?:\.[a-z0-9-]+)*\.[a-z][a-z0-9-]*$/.test(hostname)
                        ? [hostname]
                        : []
                } catch {
                    return []
                }
            })
        ),
    ].sort()
}
