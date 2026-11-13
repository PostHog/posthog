import { useMemo } from 'react'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { SidebarRow } from '~/layout/today/sidebar/SidebarRow'
import { MonitorProduct } from '~/layout/today/todayMonitor'
import { productPreview } from '~/layout/today/todayPreviewCards'
import { TodayPreviewTrigger } from '~/layout/today/TodayPreviewTrigger'
import { FileSystemIconType } from '~/queries/schema/schema-general'

export function TodayMonitorProductRow({
    product,
    active,
    dataAttr,
}: {
    product: MonitorProduct
    active: boolean
    dataAttr: string
}): JSX.Element {
    // The shared card stores the payload, so it must keep its identity between renders.
    const preview = useMemo(() => productPreview(product.label, product.item), [product.label, product.item])
    return (
        <TodayPreviewTrigger payload={preview}>
            <SidebarRow
                value={`product:${product.key}`}
                label={product.label}
                icon={iconForType(
                    (product.item.iconType ?? product.item.type) as FileSystemIconType,
                    product.item.iconColor
                )}
                to={product.href}
                active={active}
                dataAttr={`${dataAttr}-${product.key}`}
            />
        </TodayPreviewTrigger>
    )
}
