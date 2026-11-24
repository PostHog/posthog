import { useActions, useValues } from 'kea'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { SidebarSearchList } from '~/layout/today/sidebar/SidebarSearchList'
import { SidebarSection } from '~/layout/today/sidebar/SidebarSection'
import type { TodayPaneGroup, TodayPaneProduct, TodayProductPaneKey } from '~/layout/today/todayPaneProducts'
import { TodayPinnedRecentSections } from '~/layout/today/TodayPinnedRecentSections'
import { TodayRecentRow } from '~/layout/today/TodayRecentRow'
import { recentRowKey } from '~/layout/today/todayRecents'

import { TodayPaneProductRow } from '../TodayPaneProductRow'
import { todayProductPaneLogic } from './todayProductPaneLogic'

export function TodayProductPaneSidebar({ pane }: { pane: TodayProductPaneKey }): JSX.Element {
    const logic = todayProductPaneLogic({ pane })
    const {
        config,
        matching,
        matchingPinnedRows,
        matchingRecentRows,
        activeRow,
        isSectionOpen,
        noMatches,
        searchQuery,
    } = useValues(logic)
    const { toggleSection, setSearchQuery } = useActions(logic)

    const renderProducts = (group: TodayPaneGroup, products: TodayPaneProduct[]): JSX.Element[] =>
        products.map((product) => (
            <TodayPaneProductRow
                key={product.key}
                product={product}
                active={activeRow === `product:${product.key}`}
                dataAttr={group.rowDataAttr}
            />
        ))
    const renderRecent = (recent: { type: string; name: string; href: string }, dataAttr: string): JSX.Element => (
        <TodayRecentRow
            recent={recent}
            icon={iconForType(config.recentTypeInfo[recent.type].iconType)}
            typeCopy={config.recentTypeInfo[recent.type]}
            active={activeRow === recentRowKey(recent.href)}
            dataAttr={dataAttr}
        />
    )

    return (
        <div className="TodayPane group/colorful-product-icons colorful-product-icons-true" data-quill>
            <SidebarSearchList
                query={searchQuery}
                onQueryChange={setSearchQuery}
                searchLabel={`Search ${config.label}`}
                // pinned: autocapture `data-attr`, such as `monitor-sidebar-search`.
                dataAttr={`${pane}-sidebar-search`}
            >
                {matching.lead.length > 0 && (
                    <div className="flex flex-col gap-px pb-2">{renderProducts(config.lead, matching.lead)}</div>
                )}
                {noMatches && (
                    <div className="px-2 py-1 text-sm text-muted-foreground">
                        Nothing in {config.label} matches your search.
                    </div>
                )}
                <TodayPinnedRecentSections
                    pins={matchingPinnedRows}
                    recents={matchingRecentRows}
                    renderPin={(pin) => renderRecent(pin, `${pane}-sidebar-pinned`)}
                    renderRecent={(recent) => renderRecent(recent, `${pane}-sidebar-recent`)}
                    isSectionOpen={isSectionOpen}
                    onToggleSection={toggleSection}
                    dataAttrPrefix={pane}
                />
                {matching.sections.map(
                    ({ section, products }) =>
                        products.length > 0 && (
                            <SidebarSection
                                key={section.id}
                                label={section.label}
                                open={isSectionOpen(section.id)}
                                count={products.length}
                                showCount={false}
                                onToggle={() => toggleSection(section.id)}
                                divider
                                dataAttr={`${pane}-section-${section.id}`}
                            >
                                {renderProducts(section, products)}
                            </SidebarSection>
                        )
                )}
            </SidebarSearchList>
        </div>
    )
}
