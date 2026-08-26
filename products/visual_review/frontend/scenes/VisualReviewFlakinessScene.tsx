import { useActions, useValues } from 'kea'

import { IconGear } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonInput,
    LemonSegmentedButton,
    LemonSkeleton,
    LemonTable,
    Link,
} from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { QuarantineCell } from '../components/FlakinessQuarantineCell'
import { StateCell } from '../components/FlakinessStateCell'
import { FlakinessStatRow } from '../components/FlakinessStatRow'
import { VariantsCell } from '../components/FlakinessVariantsCell'
import { QuarantineAction } from '../components/QuarantineAction'
import { RepoSwitcher } from '../components/RepoSwitcher'
import { SnapshotFacetSidebar } from '../components/SnapshotFacetSidebar'
import { VisualReviewTabs } from '../components/VisualReviewTabs'
import type { FlakinessEntryApi } from '../generated/api.schemas'
import {
    DecoratedEntry,
    VisualReviewFlakinessSceneLogicProps,
    visualReviewFlakinessSceneLogic,
} from './visualReviewFlakinessSceneLogic'

export const scene: SceneExport = {
    component: VisualReviewFlakinessScene,
    logic: visualReviewFlakinessSceneLogic,
    paramsToProps: ({ params: { repoId } }): VisualReviewFlakinessSceneLogicProps => ({
        repoId: repoId || '',
    }),
}

function formatLastSeen(lastFlakedAt: string | null | undefined): string {
    if (!lastFlakedAt) {
        return 'never'
    }
    const days = dayjs().diff(dayjs(lastFlakedAt), 'day')
    return days === 0 ? 'today' : `${days}d ago`
}

export function VisualReviewFlakinessScene(): JSX.Element {
    const {
        overview,
        overviewLoading,
        repo,
        repoId,
        filteredEntries,
        statCounts,
        facetGroups,
        facetSelection,
        filters,
        thumbnailBasePath,
        loadError,
        pendingQuarantineKeys,
    } = useValues(visualReviewFlakinessSceneLogic)
    const {
        loadOverview,
        setPreset,
        toggleType,
        toggleArea,
        setSearch,
        setSort,
        clearAllFilters,
        quarantineIdentifier,
        unquarantineIdentifier,
    } = useActions(visualReviewFlakinessSceneLogic)

    const isFiltered = filters.typeKeys.length > 0 || filters.areas.length > 0 || filters.search.length > 0
    const hasPopulation = (overview?.entries.length ?? 0) > 0

    const confirmLift = (entry: FlakinessEntryApi): void => {
        LemonDialog.open({
            title: 'Lift this quarantine?',
            description: 'Runs will gate on this snapshot again, so a rendering difference will fail them.',
            primaryButton: {
                children: 'Lift quarantine',
                status: 'danger',
                onClick: () => unquarantineIdentifier(entry.identifier, entry.run_type),
            },
            secondaryButton: { children: 'Cancel' },
        })
    }

    return (
        <SceneContent>
            <SceneTitleSection
                name={repo?.repo_full_name ?? 'Visual review'}
                resourceType={{ type: 'visual_review' }}
                actions={
                    <div className="flex gap-2 items-center">
                        <RepoSwitcher repoId={repoId} activeTab="flakiness" />
                        <LemonButton size="small" type="secondary" icon={<IconGear />} to={urls.visualReviewSettings()}>
                            Settings
                        </LemonButton>
                    </div>
                }
            />
            <VisualReviewTabs activeKey="flakiness" repoId={repoId} />

            <LemonBanner type="info">
                When a snapshot renders differently but stays under the diff threshold, the run accepts it and remembers
                the new image as an allowed variant. Variants are counted against the current baseline only. When a
                snapshot changes for real, its baseline moves and the count starts over.
            </LemonBanner>

            {!loadError && <FlakinessStatRow counts={statCounts} preset={filters.preset} onChange={setPreset} />}

            {overview && (
                <div className="text-xs text-muted">
                    <span className="font-semibold text-default">
                        {overview.totals.listed.toLocaleString()} snapshots
                    </span>{' '}
                    have something to show here, out of {overview.totals.tracked.toLocaleString()} with a current
                    baseline. The rest have no variants against their baseline and no quarantine.
                </div>
            )}

            {overview?.truncated && (
                <LemonBanner type="info">
                    Showing the {overview.entries.length.toLocaleString()} snapshots with the most variants. This repo
                    has more than the page can list, so filtering here only searches the ones above.
                </LemonBanner>
            )}

            {hasPopulation && (
                <div className="flex items-center gap-2 flex-wrap">
                    <LemonInput
                        type="search"
                        placeholder="Filter by name…"
                        value={filters.search}
                        onChange={(value) => setSearch(value)}
                        className="flex-1 min-w-60"
                    />
                    <span className="text-xs text-muted">Sort</span>
                    <LemonSegmentedButton
                        size="small"
                        value={filters.sort}
                        onChange={(value) => setSort(value as 'variants' | 'recent')}
                        options={[
                            { value: 'variants', label: 'Most variants' },
                            { value: 'recent', label: 'Most recent' },
                        ]}
                    />
                    {isFiltered && (
                        <button
                            type="button"
                            className="text-xs text-muted hover:text-default"
                            onClick={clearAllFilters}
                        >
                            Clear all
                        </button>
                    )}
                </div>
            )}

            {overviewLoading && !overview ? (
                <div className="flex flex-col gap-2">
                    {Array.from({ length: 8 }).map((_, index) => (
                        <LemonSkeleton key={index} className="h-12 w-full" />
                    ))}
                </div>
            ) : loadError ? (
                <LemonBanner
                    type="error"
                    action={{
                        children: 'Try again',
                        onClick: () => loadOverview(),
                        'data-attr': 'visual-review-flakiness-retry',
                    }}
                >
                    Could not load flakiness for this repo. {loadError}
                </LemonBanner>
            ) : !hasPopulation ? (
                <div className="flex flex-col items-center justify-center py-20 gap-2 text-center">
                    <p className="m-0 font-semibold">Every snapshot renders the same way every time</p>
                    <p className="m-0 text-xs text-muted max-w-md">
                        Snapshots show up here once a run accepts a variant of one, or once someone quarantines one.
                        Nothing in this repo has done either.
                    </p>
                </div>
            ) : (
                <div className="flex flex-col sm:flex-row gap-6 items-start">
                    <SnapshotFacetSidebar
                        groups={facetGroups}
                        selection={facetSelection}
                        onToggle={(group, value) => {
                            if (group === 'type') {
                                toggleType(value)
                            } else if (group === 'area') {
                                toggleArea(value)
                            }
                        }}
                    />

                    <div className="flex-1 min-w-0">
                        <LemonTable
                            dataSource={filteredEntries}
                            rowKey={(entry: DecoratedEntry) => `${entry.run_type}::${entry.identifier}`}
                            emptyState="No snapshots match these filters."
                            columns={[
                                {
                                    title: 'Snapshot',
                                    key: 'identifier',
                                    render: (_, entry: DecoratedEntry) => (
                                        <div className="flex gap-2 items-start min-w-0">
                                            {entry.thumbnail_hash && thumbnailBasePath && (
                                                <img
                                                    src={`${thumbnailBasePath}/${encodeURIComponent(
                                                        entry.identifier
                                                    )}/?run_type=${encodeURIComponent(entry.run_type)}`}
                                                    alt=""
                                                    loading="lazy"
                                                    className="w-10 h-7 object-cover rounded border border-border shrink-0"
                                                />
                                            )}
                                            <div className="min-w-0">
                                                <Link
                                                    to={urls.visualReviewSnapshotHistory(
                                                        repoId,
                                                        entry.run_type,
                                                        entry.identifier
                                                    )}
                                                    className="font-mono text-xs break-all"
                                                >
                                                    {entry.identifier}
                                                </Link>
                                                <div className="text-[11px] text-muted mt-0.5">
                                                    {entry.run_type} · {entry._area}
                                                </div>
                                            </div>
                                        </div>
                                    ),
                                },
                                {
                                    title: 'State',
                                    key: 'state',
                                    width: 108,
                                    render: (_, entry: DecoratedEntry) => <StateCell entry={entry} />,
                                },
                                {
                                    title: 'Allowed variants',
                                    key: 'variants',
                                    align: 'right',
                                    width: 190,
                                    render: (_, entry: DecoratedEntry) => <VariantsCell entry={entry} />,
                                },
                                {
                                    title: 'Last seen',
                                    key: 'last_seen',
                                    align: 'right',
                                    width: 100,
                                    render: (_, entry: DecoratedEntry) => (
                                        // Highlight follows the server's verdict. Deriving it from
                                        // the day count here drifts at the window edge, because
                                        // dayjs truncates to whole days and the server compares
                                        // exact timestamps.
                                        <span
                                            className={`font-mono text-xs ${
                                                entry.flakiness_state === 'unstable'
                                                    ? 'text-danger font-semibold'
                                                    : 'text-muted'
                                            }`}
                                        >
                                            {formatLastSeen(entry.last_flaked_at)}
                                        </span>
                                    ),
                                },
                                {
                                    title: 'Quarantine',
                                    key: 'quarantine',
                                    render: (_, entry: DecoratedEntry) => <QuarantineCell entry={entry} />,
                                },
                                {
                                    title: '',
                                    key: 'actions',
                                    width: 150,
                                    render: (_, entry: DecoratedEntry) => {
                                        const pending = pendingQuarantineKeys.includes(
                                            `${entry.run_type}::${entry.identifier}`
                                        )
                                            ? 'Saving…'
                                            : null
                                        return (
                                            <div className="flex gap-1 justify-end">
                                                <QuarantineAction
                                                    pendingReason={pending}
                                                    identifier={entry.identifier}
                                                    mode={entry.is_quarantined ? 'extend' : 'create'}
                                                    triggerLabel={entry.is_quarantined ? 'Extend' : 'Quarantine'}
                                                    initialReason={entry.quarantine?.reason}
                                                    initialExpiresAt={entry.quarantine?.expires_at}
                                                    sourceRunId={entry.quarantine?.source_run?.id ?? null}
                                                    onQuarantine={(reason, identifiers, expiresAt, sourceRunId) => {
                                                        identifiers.forEach((identifier) =>
                                                            quarantineIdentifier(
                                                                identifier,
                                                                entry.run_type,
                                                                reason,
                                                                expiresAt,
                                                                sourceRunId
                                                            )
                                                        )
                                                    }}
                                                />
                                                {entry.is_quarantined && (
                                                    <LemonButton
                                                        size="xsmall"
                                                        type="secondary"
                                                        data-attr="visual-review-flakiness-lift"
                                                        onClick={() => confirmLift(entry)}
                                                        loading={!!pending}
                                                        disabledReason={pending ?? undefined}
                                                    >
                                                        Lift
                                                    </LemonButton>
                                                )}
                                            </div>
                                        )
                                    },
                                },
                            ]}
                        />
                    </div>
                </div>
            )}
        </SceneContent>
    )
}

export default VisualReviewFlakinessScene
