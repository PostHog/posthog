import { useValues } from 'kea'

import { IconBell } from '@posthog/icons'

import { TodayRailTile } from '~/layout/today/TodayRailTile'

import { notificationsPaneLogic } from './notificationsPaneLogic'
import { notificationsRailSignal } from './notificationsRailSignal'

export const NOTIFICATIONS_RAIL_LABEL = 'Updates'

export function TodayNotificationsRailTile({ active, onClick }: { active: boolean; onClick: () => void }): JSX.Element {
    const { summary } = useValues(notificationsPaneLogic)
    const signal = notificationsRailSignal(summary)
    return (
        <TodayRailTile
            label={NOTIFICATIONS_RAIL_LABEL}
            aria-label={signal.ariaLabel}
            icon={<IconBell />}
            active={active}
            onClick={onClick}
            count={signal.count}
            severity={signal.severity}
            dataAttr="today-rail-notifications"
        />
    )
}
