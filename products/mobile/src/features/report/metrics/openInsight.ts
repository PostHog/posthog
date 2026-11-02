import { Linking } from 'react-native'

import { track } from '@/lib/analytics'
import { safeHttpsUrl } from '@/lib/urls'

export type InsightSource = 'observation' | 'chart' | 'tile'

/** Opens an insight link in the browser and records where it was opened from. */
export function openInsight(url: string, reportId: string, source: InsightSource): void {
    const safe = safeHttpsUrl(url)
    if (!safe) {
        return
    }
    track('mobile_report_insight_opened', { report_id: reportId, source })
    Linking.openURL(safe).catch(() => undefined)
}

/** The link when the app may open it, else undefined, so a screen hides the control instead of showing a dead one. */
export function insightUrl(url: string | undefined): string | undefined {
    return url ? safeHttpsUrl(url) : undefined
}
