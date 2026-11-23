import { SidebarPinButton } from '~/layout/today/sidebar/SidebarPinButton'
import { TodayRecentRow } from '~/layout/today/TodayRecentRow'
import { recentRowKey } from '~/layout/today/todayRecents'

export function TodayPinnableRecentRow({
    recent,
    icon,
    description,
    active,
    dataAttr,
}: {
    recent: { type: string; name: string; href: string; ref?: string }
    icon: JSX.Element
    description: string
    active: boolean
    dataAttr: string
}): JSX.Element {
    return (
        <TodayRecentRow
            value={recentRowKey(recent.href)}
            name={recent.name}
            href={recent.href}
            icon={icon}
            description={description}
            active={active}
            action={
                <SidebarPinButton
                    target={{ type: recent.type, ref: recent.ref, name: recent.name, href: recent.href }}
                    dataAttr={`${dataAttr}-pin`}
                />
            }
            dataAttr={dataAttr}
        />
    )
}
