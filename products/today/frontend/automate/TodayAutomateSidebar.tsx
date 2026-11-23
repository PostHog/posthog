import { useActions, useValues } from 'kea'

import { SidebarSearchList } from '~/layout/today/sidebar/SidebarSearchList'
import { TodayPaneProduct } from '~/layout/today/todayPaneProducts'
import { TodayPinnedRecentSections } from '~/layout/today/TodayPinnedRecentSections'
import { recentRowKey } from '~/layout/today/todayRecents'

import { TodayPaneProductRow } from '../TodayPaneProductRow'
import { todayAutomateLogic } from './todayAutomateLogic'
import { TodayAutomateRecentRow } from './TodayAutomateRecentRow'

export function TodayAutomateSidebar(): JSX.Element {
    const { matching, matchingPinnedRows, matchingRecentRows, activeRow, isSectionOpen, noMatches, searchQuery } =
        useValues(todayAutomateLogic)
    const { toggleSection, setSearchQuery } = useActions(todayAutomateLogic)

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
                searchLabel="Search Automate"
                dataAttr="automate-sidebar-search"
            >
                {matching.length > 0 && (
                    <div className="flex flex-col gap-px pb-2">
                        {matching.map((product) => renderProduct(product, 'automate-sidebar-product'))}
                    </div>
                )}
                {noMatches && (
                    <div className="px-2 py-1 text-sm text-muted-foreground">
                        Nothing in Automate matches your search.
                    </div>
                )}
                <TodayPinnedRecentSections
                    pins={matchingPinnedRows}
                    recents={matchingRecentRows}
                    renderPin={(pin) => (
                        <TodayAutomateRecentRow
                            recent={pin}
                            active={activeRow === recentRowKey(pin.href)}
                            dataAttr="automate-sidebar-pinned"
                        />
                    )}
                    renderRecent={(recent) => (
                        <TodayAutomateRecentRow
                            recent={recent}
                            active={activeRow === recentRowKey(recent.href)}
                            dataAttr="automate-sidebar-recent"
                        />
                    )}
                    isSectionOpen={isSectionOpen}
                    onToggleSection={toggleSection}
                    dataAttrPrefix="automate"
                />
            </SidebarSearchList>
        </div>
    )
}
