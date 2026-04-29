import { useActions, useValues } from 'kea'

import { IconGear } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonInput, LemonSegmentedButton, LemonSkeleton } from '@posthog/lemon-ui'

import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { RepoSwitcher } from '../components/RepoSwitcher'
import { SnapshotCard } from '../components/SnapshotCard'
import { SnapshotFacetSidebar } from '../components/SnapshotFacetSidebar'
import { SnapshotStatRow } from '../components/SnapshotStatRow'
import { VisualReviewTabs } from '../components/VisualReviewTabs'
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

// Smallest column we'll allow before snapping to a fewer-column layout —
// keeps cards readable on tablet. CSS Grid handles the responsive packing
// via `auto-fill, minmax(220px, 1fr)`.
const CARD_MIN_WIDTH = 220

export function VisualReviewSnapshotOverviewScene(): JSX.Element {
    const {
        overview,
        overviewLoading,
        repo,
        repoId,
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
            <SceneTitleSection
                name={repo?.repo_full_name ?? 'Visual review'}
                resourceType={{ type: 'visual_review' }}
                actions={
                    <div className="flex gap-2 items-center">
                        <RepoSwitcher repoId={repoId} activeTab="snapshots" />
                        <LemonButton size="small" type="secondary" icon={<IconGear />} to={urls.visualReviewSettings()}>
                            Settings
                        </LemonButton>
                    </div>
                }
            />
            <VisualReviewTabs activeKey="snapshots" repoId={repoId} />

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
                <div className="ml-auto flex items-center gap-3">
                    {isFiltered && (
                        <button
                            type="button"
                            className="text-xs text-muted hover:text-default"
                            onClick={() => clearAllFilters()}
                        >
                            Clear all
                        </button>
                    )}
                    <div className="text-xs text-muted">
                        {filteredEntries.length > 0 && overview && (
                            <>
                                <span className="text-default">{filteredEntries.length.toLocaleString()}</span>
                                {filteredEntries.length !== overview.entries.length && (
                                    <> of {overview.entries.length.toLocaleString()}</>
                                )}{' '}
                                snapshots ·{' '}
                            </>
                        )}
                        Sorted by <span className="text-default">{sortLabel.label}</span>
                    </div>
                </div>
            </div>

            {overview?.truncated && (
                <LemonBanner type="info">
                    Showing the {overview.entries.length.toLocaleString()} most recently active snapshots out of{' '}
                    {overview.totals.all_snapshots.toLocaleString()}. Refine filters to see more.
                </LemonBanner>
            )}

            {/* Legend lives above the grid so first-time viewers see what the
                sparkline colors and the "tolerated" chip mean before they dive
                into hundreds of cards. */}
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
                <span className="ml-auto">Sparkline shows last 30 days</span>
            </div>

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

                <div className="flex-1 min-w-0">
                    {overviewLoading && !overview ? (
                        <div
                            className="grid gap-3"
                            style={{ gridTemplateColumns: `repeat(auto-fill, minmax(${CARD_MIN_WIDTH}px, 1fr))` }}
                        >
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
                    ) : (
                        // Plain CSS grid — no internal scroll, page handles
                        // scrolling. Lazy-loaded thumbnails keep network cost
                        // low even at the 5000-entry cap.
                        <div
                            className="grid gap-3"
                            style={{ gridTemplateColumns: `repeat(auto-fill, minmax(${CARD_MIN_WIDTH}px, 1fr))` }}
                        >
                            {filteredEntries.map((entry) => (
                                <SnapshotCard
                                    key={`${entry.run_type}::${entry.identifier}`}
                                    repoId={repoId}
                                    entry={entry}
                                    thumbnailBasePath={thumbnailBasePath}
                                />
                            ))}
                        </div>
                    )}
                </div>
            </div>
        </SceneContent>
    )
}

export default VisualReviewSnapshotOverviewScene
