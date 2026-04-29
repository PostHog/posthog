import { useActions, useValues } from 'kea'
import { useMemo } from 'react'
import { Grid } from 'react-window'

import { LemonBanner, LemonInput, LemonSegmentedButton, LemonSkeleton, LemonTag } from '@posthog/lemon-ui'

import { useResizeObserver } from 'lib/hooks/useResizeObserver'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { SnapshotCard } from '../components/SnapshotCard'
import { SnapshotFacetSidebar } from '../components/SnapshotFacetSidebar'
import { SnapshotStatRow } from '../components/SnapshotStatRow'
import {
    VisualReviewSnapshotOverviewSceneLogicProps,
    visualReviewSnapshotOverviewSceneLogic,
} from './visualReviewSnapshotOverviewSceneLogic'

export const scene: SceneExport = {
    component: VisualReviewSnapshotOverviewScene,
    logic: visualReviewSnapshotOverviewSceneLogic,
    paramsToProps: ({ params: { repoId } }): VisualReviewSnapshotOverviewSceneLogicProps => ({
        repoId: repoId || '',
    }),
}

// Width is the smallest column we'll allow before snapping to a fewer-column
// layout — keeps cards readable on tablet. Height is set so that the 140px
// thumbnail box + 60px metadata strip + borders fit comfortably.
const CARD_MIN_WIDTH = 220
const CARD_HEIGHT = 210
const CARD_GAP = 12

export function VisualReviewSnapshotOverviewScene(): JSX.Element {
    const {
        overview,
        overviewLoading,
        repo,
        filteredEntries,
        statCounts,
        frequentlyToleratedCount,
        facetGroups,
        facetSelection,
        filters,
        sortLabel,
        thumbnailBasePath,
    } = useValues(visualReviewSnapshotOverviewSceneLogic)
    const { setStatPreset, toggleType, toggleArea, toggleStability, setTheme, setSearch, clearAllFilters } = useActions(
        visualReviewSnapshotOverviewSceneLogic
    )

    const { ref: gridContainerRef, width: gridWidth = 0 } = useResizeObserver<HTMLDivElement>()
    const { columnCount, columnWidth } = useMemo(() => {
        if (gridWidth <= 0) {
            return { columnCount: 1, columnWidth: CARD_MIN_WIDTH }
        }
        const cols = Math.max(1, Math.floor((gridWidth + CARD_GAP) / (CARD_MIN_WIDTH + CARD_GAP)))
        const totalGap = CARD_GAP * (cols - 1)
        const cw = Math.floor((gridWidth - totalGap) / cols)
        return { columnCount: cols, columnWidth: cw }
    }, [gridWidth])

    const rowCount = Math.ceil(filteredEntries.length / columnCount)

    const repoId = repo?.id ?? ''

    // Theme is never neutral (always Light or Dark), so we don't count it
    // toward `isFiltered` — picking a side is the default state.
    const isFiltered =
        filters.statPreset !== 'all' ||
        filters.typeKeys.length > 0 ||
        filters.areas.length > 0 ||
        filters.stability.length > 0 ||
        filters.search.length > 0

    return (
        <SceneContent>
            <SceneTitleSection name="Snapshots" resourceType={{ type: 'visual_review' }} />

            <SnapshotStatRow
                counts={statCounts}
                frequentlyToleratedCount={frequentlyToleratedCount}
                preset={filters.statPreset}
                onChange={setStatPreset}
            />

            <div className="flex items-center gap-2 flex-wrap">
                <LemonInput
                    type="search"
                    placeholder="Filter by name…"
                    value={filters.search}
                    onChange={(value) => setSearch(value)}
                    className="flex-1 min-w-60"
                />
                <LemonSegmentedButton
                    size="small"
                    value={filters.theme}
                    onChange={(value) => setTheme(value as 'light' | 'dark')}
                    options={[
                        { value: 'light', label: 'Light' },
                        { value: 'dark', label: 'Dark' },
                    ]}
                />
                {isFiltered && (
                    <button
                        type="button"
                        className="text-xs text-muted hover:text-default"
                        onClick={() => clearAllFilters()}
                    >
                        Clear all
                    </button>
                )}
                <div className="text-xs text-muted ml-auto">
                    Sorted by <span className="text-default">{sortLabel.label}</span>
                </div>
            </div>

            {overview?.truncated && (
                <LemonBanner type="info">
                    Showing the {overview.entries.length.toLocaleString()} most recently active snapshots out of{' '}
                    {overview.totals.all_snapshots.toLocaleString()}. Refine filters to see more.
                </LemonBanner>
            )}

            <div className="flex gap-6 items-start">
                <SnapshotFacetSidebar
                    groups={facetGroups}
                    selection={facetSelection}
                    onToggle={(group, value) => {
                        if (group === 'type') {
                            toggleType(value)
                        } else if (group === 'area') {
                            toggleArea(value)
                        } else {
                            toggleStability(value)
                        }
                    }}
                />

                <div ref={gridContainerRef} className="flex-1 min-w-0">
                    {overviewLoading && !overview ? (
                        <div className="grid grid-cols-3 lg:grid-cols-5 xl:grid-cols-7 gap-3">
                            {Array.from({ length: 14 }).map((_, i) => (
                                <LemonSkeleton key={i} className="h-52 w-full" />
                            ))}
                        </div>
                    ) : filteredEntries.length === 0 ? (
                        <div className="flex flex-col items-center justify-center py-20 gap-2 text-muted">
                            <p className="m-0">No snapshots match these filters.</p>
                            {isFiltered && (
                                <button
                                    type="button"
                                    className="text-primary-3000 hover:underline text-xs"
                                    onClick={() => clearAllFilters()}
                                >
                                    Clear all filters
                                </button>
                            )}
                        </div>
                    ) : gridWidth > 0 ? (
                        <Grid
                            cellComponent={({
                                columnIndex,
                                rowIndex,
                                style,
                            }: {
                                columnIndex: number
                                rowIndex: number
                                style: React.CSSProperties
                            }) => {
                                const entry = filteredEntries[rowIndex * columnCount + columnIndex]
                                if (!entry) {
                                    return <div style={style} />
                                }
                                return (
                                    <div
                                        style={{
                                            ...style,
                                            paddingRight: columnIndex < columnCount - 1 ? CARD_GAP : 0,
                                            paddingBottom: CARD_GAP,
                                        }}
                                    >
                                        <SnapshotCard
                                            repoId={repoId}
                                            entry={entry}
                                            thumbnailBasePath={thumbnailBasePath}
                                        />
                                    </div>
                                )
                            }}
                            cellProps={{}}
                            columnCount={columnCount}
                            columnWidth={columnWidth + (columnWidth < CARD_MIN_WIDTH ? 0 : 0)}
                            rowCount={rowCount}
                            rowHeight={CARD_HEIGHT + CARD_GAP}
                            defaultHeight={Math.min(900, rowCount * (CARD_HEIGHT + CARD_GAP))}
                        />
                    ) : null}

                    {filteredEntries.length > 0 && (
                        <div className="text-xs text-muted mt-3">
                            Showing {filteredEntries.length.toLocaleString()}
                            {overview ? ` of ${overview.entries.length.toLocaleString()}` : ''} snapshots
                            {isFiltered ? ' matching your filters' : ''}.
                        </div>
                    )}
                </div>
            </div>

            {/* Tag legend at the bottom for first-time clarity. */}
            <div className="flex items-center gap-3 text-[11px] text-muted">
                <span className="flex items-center gap-1">
                    <span className="w-2 h-2 rounded-sm" style={{ background: 'var(--success)' }} />
                    Clean
                </span>
                <span className="flex items-center gap-1">
                    <span className="w-2 h-2 rounded-sm" style={{ background: 'var(--primary-3000)' }} />
                    Tolerated
                </span>
                <span className="flex items-center gap-1">
                    <span className="w-2 h-2 rounded-sm" style={{ background: 'var(--warning-dark)' }} />
                    Changed
                </span>
                <span className="flex items-center gap-1">
                    <span className="w-2 h-2 rounded-sm" style={{ background: 'var(--danger)' }} />
                    Quarantined
                </span>
                <LemonTag size="small" type="default" className="ml-auto">
                    Sparkline shows last 30 days
                </LemonTag>
            </div>
        </SceneContent>
    )
}

export default VisualReviewSnapshotOverviewScene
