import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { TodayAutomateRecent, TodayAutomateRecentType } from '~/layout/today/todayAutomateRecents'

import { TodayPinnableRecentRow } from '../TodayPinnableRecentRow'

const RECENT_ICONS: Record<TodayAutomateRecentType, JSX.Element> = {
    workflow: iconForType('workflows'),
    destination: iconForType('data_pipeline'),
    subscription: iconForType('subscriptions'),
}

const RECENT_DESCRIPTIONS: Record<TodayAutomateRecentType, string> = {
    workflow: 'A workflow. Open it to see its steps, runs, and metrics.',
    destination: 'A destination. Open it to see its configuration and the events it sent.',
    subscription: 'A subscription. Open it to see its schedule and delivery history.',
}

export function TodayAutomateRecentRow({
    recent,
    active,
    dataAttr,
}: {
    recent: TodayAutomateRecent
    active: boolean
    dataAttr: string
}): JSX.Element {
    return (
        <TodayPinnableRecentRow
            recent={recent}
            icon={RECENT_ICONS[recent.type]}
            description={RECENT_DESCRIPTIONS[recent.type]}
            active={active}
            dataAttr={dataAttr}
        />
    )
}
