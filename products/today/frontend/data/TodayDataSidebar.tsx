import { useActions, useValues } from 'kea'

import { SidebarSearchList } from '~/layout/today/sidebar/SidebarSearchList'
import { SidebarSection } from '~/layout/today/sidebar/SidebarSection'
import { TodayPaneProduct } from '~/layout/today/todayPaneProducts'
import { TodayPinnedRecentSections } from '~/layout/today/TodayPinnedRecentSections'
import { recentRowKey } from '~/layout/today/todayRecents'

import { TodayPaneProductRow } from '../TodayPaneProductRow'
import { TodayDataSection, todayDataLogic } from './todayDataLogic'
import { TodayDataRecentRow } from './TodayDataRecentRow'

const PRODUCT_SECTIONS: { section: Extract<TodayDataSection, 'warehouse' | 'definitions' | 'setup'>; label: string }[] =
    [
        { section: 'warehouse', label: 'Warehouse' },
        { section: 'definitions', label: 'Definitions' },
        { section: 'setup', label: 'Setup' },
    ]

export function TodayDataSidebar(): JSX.Element {
    const { matching, matchingPinnedRows, matchingRecentRows, activeRow, isSectionOpen, noMatches, searchQuery } =
        useValues(todayDataLogic)
    const { toggleSection, setSearchQuery } = useActions(todayDataLogic)

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
                searchLabel="Search Data"
                dataAttr="data-sidebar-search"
            >
                {matching.pipeline.length > 0 && (
                    <div className="flex flex-col gap-px pb-2">
                        {matching.pipeline.map((product) => renderProduct(product, 'data-sidebar-pipeline'))}
                    </div>
                )}
                {noMatches && (
                    <div className="px-2 py-1 text-sm text-muted-foreground">Nothing in Data matches your search.</div>
                )}
                <TodayPinnedRecentSections
                    pins={matchingPinnedRows}
                    recents={matchingRecentRows}
                    renderPin={(pin) => (
                        <TodayDataRecentRow
                            recent={pin}
                            active={activeRow === recentRowKey(pin.href)}
                            dataAttr="data-sidebar-pinned"
                        />
                    )}
                    renderRecent={(recent) => (
                        <TodayDataRecentRow
                            recent={recent}
                            active={activeRow === recentRowKey(recent.href)}
                            dataAttr="data-sidebar-recent"
                        />
                    )}
                    isSectionOpen={isSectionOpen}
                    onToggleSection={toggleSection}
                    dataAttrPrefix="data"
                />
                {PRODUCT_SECTIONS.map(
                    ({ section, label }) =>
                        matching[section].length > 0 && (
                            <SidebarSection
                                key={section}
                                label={label}
                                open={isSectionOpen(section)}
                                count={matching[section].length}
                                showCount={false}
                                onToggle={() => toggleSection(section)}
                                divider
                                dataAttr={`data-section-${section}`}
                            >
                                {matching[section].map((product) => renderProduct(product, `data-sidebar-${section}`))}
                            </SidebarSection>
                        )
                )}
            </SidebarSearchList>
        </div>
    )
}
