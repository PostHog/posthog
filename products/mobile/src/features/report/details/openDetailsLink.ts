import { Linking } from 'react-native'

import { track } from '@/lib/analytics'
import { safeHttpsUrl } from '@/lib/urls'

/** `web` is Open in PostHog, `replay` a signal's Watch session, `link` a link inside the summary or a signal. */
export type DetailsLinkTarget = 'web' | 'replay' | 'link'

/** Opens a link from the full report in the browser. Only `https://` links open, as for insight links. */
export function openDetailsLink(url: string, reportId: string, target: DetailsLinkTarget): void {
    const safe = safeHttpsUrl(url)
    if (!safe) {
        return
    }
    track('mobile_report_details_link_opened', { report_id: reportId, target })
    Linking.openURL(safe).catch(() => undefined)
}
