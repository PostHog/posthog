import { useActions, useValues } from 'kea'

import { SidebarSearchList } from '~/layout/today/sidebar/SidebarSearchList'
import { TodayPaneProduct } from '~/layout/today/todayPaneProducts'

import { TodayPaneProductRow } from '../TodayPaneProductRow'
import { todayHomeLogic } from './todayHomeLogic'

/** The Today page already lists single Inbox reports, so this pane links the full Inbox and never lists reports. */
export function TodayHomeSidebar(): JSX.Element {
    const { matching, activeRow, noMatches, searchQuery } = useValues(todayHomeLogic)
    const { setSearchQuery } = useActions(todayHomeLogic)

    const renderProduct = (product: TodayPaneProduct, dataAttr: string): JSX.Element => (
        <TodayPaneProductRow
            key={product.key}
            product={product}
            active={activeRow === `product:${product.key}`}
            dataAttr={dataAttr}
        />
    )

    return (
        <div className="TodayPane group/colorful-product-icons colorful-product-icons-true" data-quill>
            <SidebarSearchList
                query={searchQuery}
                onQueryChange={setSearchQuery}
                searchLabel="Search Home"
                dataAttr="home-sidebar-search"
            >
                {matching.top.length > 0 && (
                    <div className="flex flex-col gap-px pb-2">
                        {matching.top.map((product) => renderProduct(product, 'home-sidebar-top'))}
                    </div>
                )}
                {noMatches && (
                    <div className="px-2 py-1 text-sm text-muted-foreground">Nothing in Home matches your search.</div>
                )}
                {matching.bottom.length > 0 && (
                    <div className="flex flex-col gap-px border-t border-border pt-2 pb-2">
                        {matching.bottom.map((product) => renderProduct(product, 'home-sidebar-settings'))}
                    </div>
                )}
            </SidebarSearchList>
        </div>
    )
}
