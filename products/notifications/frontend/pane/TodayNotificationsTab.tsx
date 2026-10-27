import { useValues } from 'kea'

import { IconBell } from '@posthog/icons'

import { TodayTabBarTab } from '~/layout/today/TodayTabBarTab'

import { notificationsPaneLogic } from './notificationsPaneLogic'
import { notificationsRailSignal } from './notificationsRailSignal'
import { NOTIFICATIONS_RAIL_LABEL } from './TodayNotificationsRailTile'

export function TodayNotificationsTab({ active, onClick }: { active: boolean; onClick: () => void }): JSX.Element {
    const { summary } = useValues(notificationsPaneLogic)
    const signal = notificationsRailSignal(summary)
    return (
        <TodayTabBarTab
            label={NOTIFICATIONS_RAIL_LABEL}
            icon={<IconBell />}
            active={active}
            aria-current={active ? 'page' : undefined}
            aria-label={signal.ariaLabel}
            severity={signal.severity}
            dataAttr="today-rail-notifications"
            onClick={onClick}
        />
    )
}
