import { useActions, useValues } from 'kea'

import { AutocompleteItem, Button } from '@posthog/quill'

import { SidebarSearchList } from '~/layout/today/sidebar/SidebarSearchList'
import { TodayPaneProduct } from '~/layout/today/todayPaneProducts'
import { TodayPinnedRecentSections } from '~/layout/today/TodayPinnedRecentSections'
import { TodayRecentRow } from '~/layout/today/TodayRecentRow'

import { TodayPaneProductRow } from '../TodayPaneProductRow'
import { todayHomeLogic } from './todayHomeLogic'
import { HomeObjectRow } from './todayHomeObjects'

/** A list option, so the arrow keys reach it from the search field like the rows, and Enter shows more. */
function ShowMoreRow({
    onClick,
    loading = false,
    dataAttr,
}: {
    onClick: () => void
    loading?: boolean
    dataAttr: string
}): JSX.Element {
    return (
        <AutocompleteItem
            value={`more:${dataAttr}`}
            onClick={onClick}
            data-attr={dataAttr}
            render={
                <Button
                    size="sm"
                    left
                    loading={loading}
                    className="w-full text-muted-foreground hover:text-foreground data-highlighted:border-transparent data-highlighted:bg-fill-hover data-highlighted:text-foreground data-highlighted:ring-0"
                />
            }
        >
            Show more
        </AutocompleteItem>
    )
}

export function TodayHomeSidebar(): JSX.Element {
    const {
        matching,
        activeRow,
        activePath,
        noMatches,
        searchQuery,
        shownPinnedRows,
        shownRecentRows,
        hasMore,
        recentsPageLoading,
        isSectionOpen,
    } = useValues(todayHomeLogic)
    const { setSearchQuery, toggleSection, showMore } = useActions(todayHomeLogic)

    const renderProduct = (product: TodayPaneProduct, dataAttr: string): JSX.Element => (
        <TodayPaneProductRow
            key={product.key}
            product={product}
            active={activeRow === `product:${product.key}`}
            dataAttr={dataAttr}
        />
    )
    const renderObject = (row: HomeObjectRow, dataAttr: string): JSX.Element => (
        <TodayRecentRow
            recent={row}
            icon={row.icon}
            typeCopy={row.typeCopy}
            active={activePath === row.href}
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
                {matching.length > 0 && (
                    <div className="flex flex-col gap-px pb-2">
                        {matching.map((product) => renderProduct(product, 'home-sidebar-top'))}
                    </div>
                )}
                {noMatches && (
                    <div className="px-2 py-1 text-sm text-muted-foreground">Nothing in Home matches your search.</div>
                )}
                <TodayPinnedRecentSections
                    pins={shownPinnedRows}
                    recents={shownRecentRows}
                    renderPin={(row) => renderObject(row, 'home-sidebar-pinned')}
                    renderRecent={(row) => renderObject(row, 'home-sidebar-recent')}
                    isSectionOpen={isSectionOpen}
                    onToggleSection={toggleSection}
                    dataAttrPrefix="home"
                    pinsFooter={
                        hasMore.pinned && (
                            <ShowMoreRow onClick={() => showMore('pinned')} dataAttr="home-sidebar-pinned-more" />
                        )
                    }
                    recentsFooter={
                        hasMore.recents && (
                            <ShowMoreRow
                                onClick={() => showMore('recents')}
                                loading={recentsPageLoading}
                                dataAttr="home-sidebar-recent-more"
                            />
                        )
                    }
                />
            </SidebarSearchList>
        </div>
    )
}
