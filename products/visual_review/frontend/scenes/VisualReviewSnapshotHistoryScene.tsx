import { useValues } from 'kea'
import { useState } from 'react'

import { IconArrowLeft } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonDivider, LemonSkeleton, LemonTag, Link } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'

import type { SnapshotHistoryEntryApi } from '../generated/api.schemas'
import {
    ThemePair,
    VisualReviewSnapshotHistorySceneLogicProps,
    visualReviewSnapshotHistorySceneLogic,
} from './visualReviewSnapshotHistorySceneLogic'

export const scene: SceneExport = {
    component: VisualReviewSnapshotHistoryScene,
    logic: visualReviewSnapshotHistorySceneLogic,
    paramsToProps: ({ params: { repoId, runType, identifier } }): VisualReviewSnapshotHistorySceneLogicProps => ({
        repoId: repoId || '',
        runType: runType ? decodeURIComponent(runType) : '',
        identifier: identifier ? decodeURIComponent(identifier) : '',
    }),
}

const REASON_TAGS: Record<string, { label: string; type: 'success' | 'warning' | 'highlight' | 'default' }> = {
    added: { label: 'First capture', type: 'highlight' },
    changed: { label: 'Approved', type: 'success' },
    removed: { label: 'Removed', type: 'warning' },
    unchanged: { label: 'No-op', type: 'default' },
}

function ThemePane({
    entry,
    theme,
}: {
    entry: SnapshotHistoryEntryApi | null
    theme: 'light' | 'dark' | null
}): JSX.Element {
    const [imageLoaded, setImageLoaded] = useState(false)

    return (
        <div
            className={`relative border rounded overflow-hidden aspect-[16/9] ${theme === 'dark' ? 'bg-bg-3000' : 'bg-bg-light'}`}
        >
            {theme && (
                <span
                    className={`absolute top-2 left-2 z-10 text-[10px] font-semibold uppercase tracking-wider px-1.5 py-0.5 rounded-sm backdrop-blur-sm ${
                        theme === 'dark' ? 'bg-black/70 text-white' : 'bg-white/85 text-default'
                    }`}
                >
                    {theme}
                </span>
            )}
            {entry?.current_artifact?.download_url ? (
                <>
                    {!imageLoaded && <LemonSkeleton className="absolute inset-0" />}
                    <img
                        src={entry.current_artifact.download_url}
                        alt={`${theme ?? 'snapshot'} variant`}
                        loading="lazy"
                        decoding="async"
                        className={`w-full h-full object-contain transition-opacity duration-150 ${imageLoaded ? 'opacity-100' : 'opacity-0'}`}
                        onLoad={() => setImageLoaded(true)}
                        onError={() => setImageLoaded(true)}
                    />
                </>
            ) : (
                <div className="w-full h-full flex items-center justify-center text-muted text-xs">
                    {entry ? 'No image' : 'No matching capture'}
                </div>
            )}
        </div>
    )
}

// Deep link into the run with the identifier's snapshot pre-selected so the user lands
// directly on the diff viewer for it, not just the run overview.
function runUrl(entry: SnapshotHistoryEntryApi): string {
    return `${urls.visualReviewRun(entry.run_id)}?snapshot=${encodeURIComponent(entry.snapshot_id)}`
}

function HistoryEntryCard({
    pair,
    isCurrent,
    repoFullName,
}: {
    pair: ThemePair
    isCurrent: boolean
    repoFullName: string | null
}): JSX.Element {
    const entry = pair.primary
    const reason = REASON_TAGS[entry.result] ?? { label: entry.result, type: 'default' as const }
    const diff = entry.diff_percentage
    const hasDiff = diff != null && diff > 0
    const created = dayjs(entry.created_at)
    const prUrl = entry.pr_number && repoFullName ? `https://github.com/${repoFullName}/pull/${entry.pr_number}` : null
    const commitUrl = repoFullName ? `https://github.com/${repoFullName}/commit/${entry.commit_sha}` : null
    const showPair = pair.primaryTheme !== null

    return (
        <article className="flex gap-4">
            {/* Spine + dot */}
            <div className="flex flex-col items-center pt-3 shrink-0" aria-hidden>
                <span
                    className={`w-3 h-3 rounded-full border-2 ${
                        isCurrent
                            ? 'bg-accent border-accent shadow-[0_0_0_4px_rgba(245,78,0,0.18)]'
                            : 'bg-bg-light border-primary'
                    }`}
                />
                <span className="flex-1 w-px bg-border-primary mt-2" />
            </div>

            <LemonCard className={`flex-1 min-w-0 p-3 ${isCurrent ? '' : 'opacity-90'}`} hoverEffect={false}>
                <div className="flex items-center gap-2 flex-wrap mb-1.5">
                    {isCurrent && <LemonTag type="primary">Current baseline</LemonTag>}
                    <LemonTag type={reason.type}>{reason.label}</LemonTag>
                    <span className="text-sm font-semibold">{created.fromNow()}</span>
                    <span className="text-muted text-xs">·</span>
                    <span className="text-muted text-xs font-mono">{created.format('MMM D YYYY · HH:mm')}</span>
                </div>

                <div className="flex items-center gap-2 flex-wrap text-xs text-muted mb-2.5">
                    <Link to={runUrl(entry)} className="font-mono text-default">
                        {entry.branch}
                    </Link>
                    {prUrl && (
                        <>
                            <span>·</span>
                            <Link to={prUrl} target="_blank" className="font-mono">
                                #{entry.pr_number}
                            </Link>
                        </>
                    )}
                    <span>·</span>
                    {commitUrl ? (
                        <Link to={commitUrl} target="_blank" className="font-mono">
                            {entry.commit_sha.slice(0, 8)}
                        </Link>
                    ) : (
                        <span className="font-mono">{entry.commit_sha.slice(0, 8)}</span>
                    )}
                    {hasDiff && (
                        <>
                            <span>·</span>
                            <span
                                className={`font-mono tabular-nums ${diff > 5 ? 'text-warning-dark font-semibold' : ''}`}
                            >
                                {diff < 1 ? diff.toFixed(1) : Math.round(diff)}% change
                            </span>
                        </>
                    )}
                </div>

                <Link
                    to={runUrl(entry)}
                    className={`grid gap-2 ${showPair ? 'grid-cols-2 max-w-md' : 'grid-cols-1 max-w-xs'}`}
                >
                    <ThemePane entry={pair.primary} theme={pair.primaryTheme} />
                    {showPair && <ThemePane entry={pair.partner} theme={pair.partnerTheme} />}
                </Link>
            </LemonCard>
        </article>
    )
}

export function VisualReviewSnapshotHistoryScene(): JSX.Element {
    const { repo, repoLoading, history, historyLoading, baselineUpdates, identifier, pairedHistory } = useValues(
        visualReviewSnapshotHistorySceneLogic
    )

    const firstSeen = history.length > 0 ? dayjs(history[history.length - 1].created_at) : null
    const repoFullName = repo?.repo_full_name ?? null

    return (
        <SceneContent>
            <div className="flex flex-col gap-4 py-4 max-w-3xl">
                <LemonCard hoverEffect={false} className="p-4 flex items-start justify-between gap-6">
                    <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2 mb-2 text-xs">
                            <LemonButton
                                size="xsmall"
                                type="tertiary"
                                icon={<IconArrowLeft />}
                                to={urls.visualReviewRuns()}
                            >
                                All runs
                            </LemonButton>
                            {repoFullName && (
                                <>
                                    <span className="text-muted">·</span>
                                    <span className="font-mono text-muted">{repoFullName}</span>
                                </>
                            )}
                        </div>
                        <h1 className="m-0 text-xl font-semibold font-mono break-all">{identifier}</h1>
                    </div>

                    <div className="flex items-stretch gap-0 shrink-0">
                        <Stat value={historyLoading ? '–' : String(baselineUpdates.length)} label="Baseline updates" />
                        <LemonDivider vertical className="mx-3" />
                        <Stat value={firstSeen ? firstSeen.fromNow(true) : '–'} label="First captured" />
                    </div>
                </LemonCard>

                {historyLoading || repoLoading ? (
                    <div className="flex flex-col gap-4">
                        <LemonSkeleton className="h-48 w-full" />
                        <LemonSkeleton className="h-48 w-full" />
                    </div>
                ) : history.length === 0 ? (
                    <LemonBanner type="info">No history yet for this snapshot.</LemonBanner>
                ) : (
                    <div className="flex flex-col gap-3">
                        {pairedHistory.map((pair: ThemePair, i: number) => (
                            <HistoryEntryCard
                                key={`${pair.runId}-${pair.primary.snapshot_id}`}
                                pair={pair}
                                isCurrent={i === 0}
                                repoFullName={repoFullName}
                            />
                        ))}
                        {firstSeen && (
                            <div className="flex gap-4 opacity-60">
                                <div className="flex flex-col items-center pt-2 shrink-0" aria-hidden>
                                    <span className="w-3 h-3 rounded-full bg-border-primary" />
                                </div>
                                <p className="text-xs italic text-muted py-2 m-0">
                                    Snapshot didn't exist before {firstSeen.fromNow()}
                                </p>
                            </div>
                        )}
                    </div>
                )}
            </div>
        </SceneContent>
    )
}

function Stat({ value, label }: { value: string; label: string }): JSX.Element {
    return (
        <div className="min-w-[110px]">
            <div className="text-base font-semibold leading-tight">{value}</div>
            <div className="text-[11px] uppercase tracking-wider text-tertiary mt-0.5">{label}</div>
        </div>
    )
}

export default VisualReviewSnapshotHistoryScene
