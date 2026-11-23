import { useActions, useValues } from 'kea'
import { useEffect, useMemo, useState } from 'react'

import { IconList, IconSearch } from '@posthog/icons'
import {
    Button,
    Card,
    DataTable,
    Empty,
    EmptyContent,
    EmptyDescription,
    EmptyHeader,
    EmptyMedia,
    EmptyTitle,
    Text,
} from '@posthog/quill'

import { cn } from 'lib/utils/css-classes'
import { AnalyticsSearchInput } from 'scenes/analytics/AnalyticsSearchInput'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { releaseAllColumns } from './ReleaseAllColumns'
import { ReleaseAllFilterMenu } from './ReleaseAllFilterMenu'
import { ReleaseAllRow, releaseAllLogic } from './releaseAllLogic'
import { ReleaseAllNewMenu } from './ReleaseAllNewMenu'
import { ReleaseAllSkeleton } from './ReleaseAllSkeleton'
import { RELEASE_ALL_TYPE_INFO } from './releaseAllTypeInfo'
import { ReleaseAutoImport } from './ReleaseAutoImport'
import { NewReleaseDialog } from './ReleaseFilters'
import { ReleaseImportFailedNotice } from './ReleaseImportFailedNotice'
import { releaseImportLogic } from './releaseImportLogic'
import { releaseLogic } from './releaseLogic'
import { ReleasesGate } from './ReleasesGate'
import { STAGE_COLOR_VARS } from './releaseUtils'
import { useNearTableEnd } from './useNearTableEnd'

export const scene: SceneExport = {
    component: ReleaseAll,
    logic: releaseLogic,
}

const SCROLL_PREFETCH_MARGIN = '1200px 0px'
const rowId = (row: ReleaseAllRow): string => row.key
const rowHoverGroup = (): string => 'group/row'

function ReleaseAllContent(): JSX.Element {
    const { displayRows, filters, searchInput, hasMore, loading, stale, failedTypes, listState } =
        useValues(releaseAllLogic)
    const { setSearchInput, setFilters, clearFilters, loadMore, retry } = useActions(releaseAllLogic)
    const { showAutoImport } = useValues(releaseImportLogic)
    const { releasesEnabled } = useValues(releaseLogic)
    const [tableViewport, setTableViewport] = useState<HTMLDivElement | null>(null)
    const { ref: tableEndRef, inView: tableEndInView } = useNearTableEnd(tableViewport, SCROLL_PREFETCH_MARGIN)
    const nearEnd = !tableViewport || tableEndInView
    const columns = useMemo(() => releaseAllColumns({ sortable: true }), [])

    useEffect(() => {
        if (nearEnd && hasMore && !loading && !stale && !showAutoImport) {
            loadMore()
        }
    }, [nearEnd, hasMore, loading, stale, showAutoImport, displayRows.length, loadMore])

    const renderBody = (): JSX.Element => {
        if (showAutoImport) {
            return <ReleaseAutoImport />
        }
        if (listState === 'error') {
            return (
                <Empty>
                    <EmptyHeader>
                        <EmptyTitle>Couldn’t load your releases</EmptyTitle>
                        <EmptyDescription>Try again, and if it keeps happening contact support.</EmptyDescription>
                    </EmptyHeader>
                    <EmptyContent>
                        <Button
                            variant="outline"
                            loading={loading}
                            onClick={() => retry()}
                            data-attr="release-all-retry"
                        >
                            Try again
                        </Button>
                    </EmptyContent>
                </Empty>
            )
        }
        if (listState === 'loading') {
            return (
                <Card size="sm" flush className="pt-0">
                    <ReleaseAllSkeleton />
                </Card>
            )
        }
        if (listState === 'no-matches') {
            return (
                <Empty>
                    <EmptyHeader>
                        <EmptyMedia variant="icon">
                            <IconSearch />
                        </EmptyMedia>
                        <EmptyTitle>Nothing matches these filters</EmptyTitle>
                        <EmptyDescription>Try a different name, or clear the filters.</EmptyDescription>
                    </EmptyHeader>
                    <EmptyContent>
                        <Button variant="outline" onClick={() => clearFilters()} data-attr="release-all-clear-filters">
                            Clear filters
                        </Button>
                    </EmptyContent>
                </Empty>
            )
        }
        if (listState === 'empty') {
            return (
                <Empty>
                    <EmptyHeader>
                        <EmptyMedia variant="icon">
                            <IconList />
                        </EmptyMedia>
                        <EmptyTitle>Nothing to release yet</EmptyTitle>
                        <EmptyDescription>
                            {releasesEnabled
                                ? 'Releases, feature flags, experiments and early access features show up here as people create them.'
                                : 'Feature flags, experiments and early access features show up here as people create them.'}
                        </EmptyDescription>
                    </EmptyHeader>
                    <EmptyContent>
                        <ReleaseAllNewMenu />
                    </EmptyContent>
                </Empty>
            )
        }
        return (
            <div
                className={cn('flex min-h-0 flex-col transition-opacity', stale && 'opacity-60')}
                aria-busy={stale || hasMore}
            >
                <Card size="sm" flush className={cn('min-h-0 pt-0', STAGE_COLOR_VARS)} data-attr="release-all-table">
                    <DataTable
                        columns={columns}
                        data={displayRows}
                        fullWidth
                        size="sm"
                        stickyHeader
                        resizableColumns
                        viewportRef={setTableViewport}
                        viewportEndRef={tableEndRef}
                        getRowId={rowId}
                        sorting={[{ id: 'created_at', desc: filters.order === '-created_at' }]}
                        onSortingChange={([sort]) =>
                            setFilters({ order: sort && !sort.desc ? 'created_at' : '-created_at' })
                        }
                        className="flex min-h-0 flex-col [--quill-table-sticky-bg:var(--card)]"
                        rowClassName={rowHoverGroup}
                    />
                </Card>
            </div>
        )
    }

    return (
        <SceneContent className="min-h-0 flex-1 pb-4">
            <SceneTitleSection
                name="View all"
                description={
                    releasesEnabled
                        ? 'Releases, feature flags, experiments and early access features in this project.'
                        : 'Feature flags, experiments and early access features in this project.'
                }
                resourceType={{ type: 'release', forceIcon: <IconList /> }}
                actions={
                    <div data-quill className="flex items-center gap-2">
                        <ReleaseAllNewMenu />
                    </div>
                }
            />
            <div data-quill className="flex min-h-0 flex-1 flex-col gap-3">
                <div className="flex flex-wrap items-center gap-2">
                    <AnalyticsSearchInput
                        value={searchInput}
                        onChange={setSearchInput}
                        label={
                            releasesEnabled
                                ? 'Search releases, flags, experiments and early access features'
                                : 'Search flags, experiments and early access features'
                        }
                        placeholder="Search"
                        dataAttr="release-all-search"
                    />
                    <ReleaseAllFilterMenu />
                </div>
                {releasesEnabled && <ReleaseImportFailedNotice />}
                {listState === 'ready' && failedTypes.length > 0 && (
                    <div className="flex flex-wrap items-center gap-2" role="alert">
                        <Text size="sm" variant="destructive">
                            {`${new Intl.ListFormat('en', { type: 'conjunction' }).format(
                                failedTypes.map((type) => RELEASE_ALL_TYPE_INFO[type].pluralLabel)
                            )} didn’t load, so this list may be incomplete.`}
                        </Text>
                        <Button
                            variant="outline"
                            size="xs"
                            loading={loading}
                            onClick={() => retry()}
                            data-attr="release-all-retry"
                        >
                            Try again
                        </Button>
                    </div>
                )}
                {renderBody()}
            </div>
            {releasesEnabled && <NewReleaseDialog />}
        </SceneContent>
    )
}

export function ReleaseAll(): JSX.Element {
    return (
        <ReleasesGate area>
            <ReleaseAllContent />
        </ReleasesGate>
    )
}
