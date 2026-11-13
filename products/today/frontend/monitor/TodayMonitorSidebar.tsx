import { useActions, useValues } from 'kea'

import { SidebarRowEnter } from '~/layout/today/sidebar/SidebarRowEnter'
import { SidebarSearchList } from '~/layout/today/sidebar/SidebarSearchList'
import { SidebarSection } from '~/layout/today/sidebar/SidebarSection'
import { monitorRecentRowKey } from '~/layout/today/todayMonitor'

import { todayMonitorLogic } from './todayMonitorLogic'
import { TodayMonitorProductRow } from './TodayMonitorProductRow'
import { TodayMonitorRecentRow } from './TodayMonitorRecentRow'

/** The Monitor sub-nav: the tools engineers start from, their pinned and recent issues and log views, then products. */
export function TodayMonitorSidebar(): JSX.Element {
    const {
        matchingTools,
        matchingProducts,
        matchingPinnedRows,
        matchingRecentRows,
        activeRow,
        isSectionOpen,
        isSearching,
        searchQuery,
    } = useValues(todayMonitorLogic)
    const { toggleSection, setSearchQuery } = useActions(todayMonitorLogic)

    const noMatches =
        isSearching &&
        matchingTools.length === 0 &&
        matchingProducts.length === 0 &&
        matchingPinnedRows.length === 0 &&
        matchingRecentRows.length === 0

    return (
        <div className="TodayPane group/colorful-product-icons colorful-product-icons-true" data-quill>
            <SidebarSearchList
                query={searchQuery}
                onQueryChange={setSearchQuery}
                searchLabel="Search Monitor"
                dataAttr="monitor-sidebar-search"
            >
                {matchingTools.length > 0 && (
                    <div className="flex flex-col gap-px pb-2">
                        {matchingTools.map((product) => (
                            <TodayMonitorProductRow
                                key={product.key}
                                product={product}
                                active={activeRow === `product:${product.key}`}
                                dataAttr="monitor-sidebar-tool"
                            />
                        ))}
                    </div>
                )}
                {noMatches && (
                    <div className="px-2 py-1 text-sm text-muted-foreground">
                        Nothing in Monitor matches your search.
                    </div>
                )}
                {matchingPinnedRows.length > 0 && (
                    <SidebarSection
                        label="Pinned"
                        open={isSectionOpen('pinned')}
                        count={matchingPinnedRows.length}
                        showCount={false}
                        onToggle={() => toggleSection('pinned')}
                        divider
                        dataAttr="monitor-section-pinned"
                    >
                        {matchingPinnedRows.map((pin) => (
                            <SidebarRowEnter key={pin.key} pinKey={pin.key}>
                                <TodayMonitorRecentRow
                                    recent={pin}
                                    active={activeRow === monitorRecentRowKey(pin.href)}
                                    dataAttr="monitor-sidebar-pinned"
                                />
                            </SidebarRowEnter>
                        ))}
                    </SidebarSection>
                )}
                {matchingRecentRows.length > 0 && (
                    <SidebarSection
                        label="Recents"
                        open={isSectionOpen('recents')}
                        count={matchingRecentRows.length}
                        showCount={false}
                        onToggle={() => toggleSection('recents')}
                        divider
                        dataAttr="monitor-section-recents"
                    >
                        {matchingRecentRows.map((recent) => (
                            <TodayMonitorRecentRow
                                key={recent.href}
                                recent={recent}
                                active={activeRow === monitorRecentRowKey(recent.href)}
                                dataAttr="monitor-sidebar-recent"
                            />
                        ))}
                    </SidebarSection>
                )}
                {matchingProducts.length > 0 && (
                    <SidebarSection
                        label="Products"
                        open={isSectionOpen('products')}
                        count={matchingProducts.length}
                        showCount={false}
                        onToggle={() => toggleSection('products')}
                        divider
                        dataAttr="monitor-section-products"
                    >
                        {matchingProducts.map((product) => (
                            <TodayMonitorProductRow
                                key={product.key}
                                product={product}
                                active={activeRow === `product:${product.key}`}
                                dataAttr="monitor-sidebar-product"
                            />
                        ))}
                    </SidebarSection>
                )}
            </SidebarSearchList>
        </div>
    )
}
