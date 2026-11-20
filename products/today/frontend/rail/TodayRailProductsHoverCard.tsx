import { useValues } from 'kea'

import { NavProductIcon } from '~/layout/panel-layout/navbar/tabs/NavProductIcon'
import { pinnedNavProducts } from '~/layout/panel-layout/navbar/tabs/navProductItems'
import { productsItemName } from '~/layout/panel-layout/navbar/tabs/productsCatalog'
import { todayProductsLogic, resolveStarredProducts } from '~/layout/today/todayProductsLogic'
import { recentItemsModel } from '~/models/recentItemsModel'

import { railPreviewItems, railRecentItems } from './todayRailPreviewItems'
import { TodayRailPreviewList } from './TodayRailPreviewList'

export function TodayRailProductsHoverCard({ onAction }: { onAction: () => void }): JSX.Element {
    const { products, shortcutData, shortcutDataLoading } = useValues(todayProductsLogic)
    const { recents, recentsLoading } = useValues(recentItemsModel)
    const pins = [
        ...new Map(
            [...pinnedNavProducts(products, ''), ...resolveStarredProducts(shortcutData, products)].map((item) => [
                item.href,
                item,
            ])
        ).values(),
    ].flatMap((item) =>
        item.href
            ? [
                  {
                      name: productsItemName(item),
                      href: item.href,
                      icon: <NavProductIcon item={item} />,
                  },
              ]
            : []
    )

    return (
        <TodayRailPreviewList
            title="Products"
            pins={pins}
            recents={railRecentItems(railPreviewItems(recents, 'products'), pins)}
            loading={shortcutDataLoading || recentsLoading}
            onAction={onAction}
        />
    )
}
