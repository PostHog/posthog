import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { SidebarPinButton } from '~/layout/today/sidebar/SidebarPinButton'
import { TodayMonitorRecent, TodayMonitorRecentType, monitorRecentRowKey } from '~/layout/today/todayMonitor'
import { TodayRecentRow } from '~/layout/today/TodayRecentRow'

const RECENT_ICONS: Record<TodayMonitorRecentType, JSX.Element> = {
    error_tracking_issue: iconForType('error_tracking'),
    logs_view: iconForType('logs'),
}

const RECENT_DESCRIPTIONS: Record<TodayMonitorRecentType, string> = {
    error_tracking_issue: 'An error tracking issue. Open it to see its stack trace, events, and affected users.',
    logs_view: 'A saved logs view. Open it to see the logs that match its filters.',
}

export function TodayMonitorRecentRow({
    recent,
    active,
    dataAttr,
}: {
    recent: TodayMonitorRecent
    active: boolean
    dataAttr: string
}): JSX.Element {
    return (
        <TodayRecentRow
            value={monitorRecentRowKey(recent.href)}
            name={recent.name}
            href={recent.href}
            icon={RECENT_ICONS[recent.type]}
            description={RECENT_DESCRIPTIONS[recent.type]}
            active={active}
            action={
                <SidebarPinButton
                    target={{ type: recent.type, name: recent.name, href: recent.href }}
                    dataAttr={`${dataAttr}-pin`}
                />
            }
            dataAttr={dataAttr}
        />
    )
}
