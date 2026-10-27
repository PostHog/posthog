import type { TodayRailSeverity } from '~/layout/today/todayRailSeverity'

import { UnreadSummaryApi } from '../generated/api.schemas'

export interface NotificationsRailSignal {
    count: number
    severity: TodayRailSeverity
    ariaLabel: string
}

/** The rail counts what is addressed to the person, shows a dot for the rest, and turns red for anything critical. */
export function notificationsRailSignal(summary: UnreadSummaryApi | null): NotificationsRailSignal {
    if (!summary || summary.count === 0) {
        return { count: 0, severity: 'none', ariaLabel: 'Notifications' }
    }
    const severity: TodayRailSeverity = summary.has_critical ? 'critical' : 'notice'
    const parts = [summary.direct_count > 0 ? `${summary.direct_count} for you` : `${summary.count} unread`]
    if (summary.has_critical) {
        parts.push('including critical')
    }
    return { count: summary.direct_count, severity, ariaLabel: `Notifications, ${parts.join(', ')}` }
}
