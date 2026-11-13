import { useMemo } from 'react'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { SidebarPinButton } from '~/layout/today/sidebar/SidebarPinButton'
import { SidebarRow } from '~/layout/today/sidebar/SidebarRow'
import { TodayMonitorRecent, TodayMonitorRecentType, monitorRecentRowKey } from '~/layout/today/todayMonitor'
import { TodayExplainerPreview } from '~/layout/today/todayPreviewCards'
import { TodayPreviewTrigger } from '~/layout/today/TodayPreviewTrigger'

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
    // The shared card stores the payload, so it must keep its identity between renders.
    const preview = useMemo<TodayExplainerPreview>(
        () => ({
            kind: 'explainer',
            label: recent.name,
            icon: RECENT_ICONS[recent.type],
            description: RECENT_DESCRIPTIONS[recent.type],
        }),
        [recent.name, recent.type]
    )
    return (
        <TodayPreviewTrigger payload={preview}>
            <SidebarRow
                value={monitorRecentRowKey(recent.href)}
                label={recent.name}
                icon={RECENT_ICONS[recent.type]}
                to={recent.href}
                active={active}
                action={
                    <SidebarPinButton
                        target={{ type: recent.type, name: recent.name, href: recent.href }}
                        dataAttr={`${dataAttr}-pin`}
                    />
                }
                dataAttr={dataAttr}
            />
        </TodayPreviewTrigger>
    )
}
