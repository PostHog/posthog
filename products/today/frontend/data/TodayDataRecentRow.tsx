import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { SidebarPinButton } from '~/layout/today/sidebar/SidebarPinButton'
import { TodayDataRecent, TodayDataRecentType } from '~/layout/today/todayDataRecents'
import { TodayRecentRow } from '~/layout/today/TodayRecentRow'
import { recentRowKey } from '~/layout/today/todayRecents'

const RECENT_ICONS: Record<TodayDataRecentType, JSX.Element> = {
    event_definition: iconForType('event_definition'),
    property_definition: iconForType('property_definition'),
    data_source: iconForType('data_source'),
    data_model: iconForType('data_modeling'),
}

const RECENT_DESCRIPTIONS: Record<TodayDataRecentType, string> = {
    event_definition: 'An event definition. Open it to see its description, properties, and where it is used.',
    property_definition: 'A property definition. Open it to see its type, description, and where it is used.',
    data_source: 'A data source. Open it to see its tables, syncs, and settings.',
    data_model: 'A table or view in your warehouse. Open it to see its columns, lineage, and data quality.',
}

export function TodayDataRecentRow({
    recent,
    active,
    dataAttr,
}: {
    recent: TodayDataRecent
    active: boolean
    dataAttr: string
}): JSX.Element {
    return (
        <TodayRecentRow
            value={recentRowKey(recent.href)}
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
