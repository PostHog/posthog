import { useValues } from 'kea'
import { useState } from 'react'

import { LemonBanner, LemonSkeleton, LemonTag, Link } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { DiffPercentage } from '../components/DiffPercentage'
import { VisualReviewTabs } from '../components/VisualReviewTabs'
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

// Max height for any single pane — keeps very tall snapshots (e.g. 200×1500
// scrollable lists) from blowing out the row. Width is capped to the grid cell
// so ultra-wide ones letterbox horizontally instead.
const PANE_MAX_HEIGHT_PX = 480

function ThemePane({
    entry,
    theme,
}: {
    entry: SnapshotHistoryEntryApi | null
    theme: 'light' | 'dark' | null
}): JSX.Element {
    const [imageLoaded, setImageLoaded] = useState(false)
    const hasImage = !!entry?.current_artifact?.download_url
    return (
        <div
            className={`relative border rounded overflow-hidden flex items-center justify-center ${theme === 'dark' ? 'bg-bg-3000' : 'bg-bg-light'} ${hasImage ? '' : 'aspect-[16/9]'}`}
            style={{ maxHeight: PANE_MAX_HEIGHT_PX }}
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
            {hasImage ? (
                <>
                    {!imageLoaded && <LemonSkeleton className="absolute inset-0" />}
                    <img
                        src={entry!.current_artifact!.download_url!}
                        alt={`${theme ?? 'snapshot'} variant`}
                        loading="lazy"
                        decoding="async"
                        className={`max-w-full w-auto h-auto object-contain transition-opacity duration-150 ${imageLoaded ? 'opacity-100' : 'opacity-0'}`}
                        style={{ maxHeight: PANE_MAX_HEIGHT_PX }}
                        onLoad={() => setImageLoaded(true)}
                        onError={() => setImageLoaded(true)}
                    />
                </>
            ) : (
                <div className="text-muted text-xs">{entry ? 'No image' : 'No matching capture'}</div>
            )}
        </div>
    )
}

// Deep link into the run with the identifier's snapshot pre-selected. The run scene
// reads `snapshot` from the URL hash (see `urlToAction` in visualReviewRunSceneLogic),
// not from the query string — using `?` here would land on the run overview instead.
function runUrl(entry: SnapshotHistoryEntryApi): string {
    return `${urls.visualReviewRun(entry.run_id)}#snapshot=${encodeURIComponent(entry.snapshot_id)}`
}

function HistoryRow({
    pair,
    isCurrent,
    isLast,
    repoFullName,
}: {
    pair: ThemePair
    isCurrent: boolean
    isLast: boolean
    repoFullName: string | null
}): JSX.Element {
    const entry = pair.primary
    const reason = REASON_TAGS[entry.result] ?? { label: entry.result, type: 'default' as const }
    const prUrl = entry.pr_number && repoFullName ? `https://github.com/${repoFullName}/pull/${entry.pr_number}` : null
    const commitUrl = repoFullName ? `https://github.com/${repoFullName}/commit/${entry.commit_sha}` : null
    const showPair = pair.primaryTheme !== null

    return (
        <article className="flex gap-4">
            {/* Spine + dot */}
            <div className="flex flex-col items-center pt-1.5 shrink-0" aria-hidden>
                <span
                    className={`w-3 h-3 rounded-full border-2 ${
                        isCurrent
                            ? 'bg-accent border-accent shadow-[0_0_0_4px_rgba(245,78,0,0.18)]'
                            : 'bg-bg-light border-secondary'
                    }`}
                />
                {!isLast && <span className="flex-1 w-0.5 bg-border mt-2" />}
            </div>

            <div className="flex-1 min-w-0 pb-6">
                <div className="flex items-center gap-2 flex-wrap mb-1">
                    {isCurrent && <LemonTag type="primary">Current baseline</LemonTag>}
                    <LemonTag type={reason.type}>{reason.label}</LemonTag>
                    <TZLabel time={entry.created_at} className="text-sm font-semibold" />
                </div>

                <div className="flex items-center gap-2 flex-wrap text-xs text-muted mb-2">
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
                    {entry.diff_percentage != null && entry.diff_percentage > 0 && (
                        <>
                            <span>·</span>
                            <DiffPercentage value={entry.diff_percentage} />
                        </>
                    )}
                </div>

                <div className={`grid gap-2 ${showPair ? 'grid-cols-2' : 'grid-cols-1 w-1/2'}`}>
                    <Link to={runUrl(pair.primary)} className="contents">
                        <ThemePane entry={pair.primary} theme={pair.primaryTheme} />
                    </Link>
                    {showPair &&
                        (pair.partner ? (
                            <Link to={runUrl(pair.partner)} className="contents">
                                <ThemePane entry={pair.partner} theme={pair.partnerTheme} />
                            </Link>
                        ) : (
                            <ThemePane entry={null} theme={pair.partnerTheme} />
                        ))}
                </div>
            </div>
        </article>
    )
}

function Stat({ value, label }: { value: React.ReactNode; label: string }): JSX.Element {
    return (
        <div className="flex flex-col gap-0.5">
            <div className="text-base font-semibold leading-tight whitespace-nowrap">{value}</div>
            <div className="text-[11px] uppercase tracking-wider text-tertiary">{label}</div>
        </div>
    )
}

export function VisualReviewSnapshotHistoryScene(): JSX.Element {
    const { repo, repoLoading, history, historyLoading, identifier, pairedHistory, runType, repoId } = useValues(
        visualReviewSnapshotHistorySceneLogic
    )

    const repoFullName = repo?.repo_full_name ?? null
    // history is already deduped to one row per distinct baseline (newest first),
    // so the tail is the first ever capture and the length is the number of
    // distinct baselines this identifier has had.
    const firstSeen = history.length > 0 ? history[history.length - 1].created_at : null
    const baselineUpdates = Math.max(0, history.length - 1)

    return (
        <SceneContent>
            <SceneTitleSection name={identifier} resourceType={{ type: 'visual_review' }} />
            {repoId && <VisualReviewTabs activeKey="snapshots" repoId={repoId} />}

            <div className="w-full max-w-4xl mx-auto flex flex-col gap-4">
                <div className="border rounded bg-bg-light flex flex-wrap items-center gap-x-10 gap-y-3 px-4 py-3">
                    {runType && (
                        <Stat
                            value={
                                <LemonTag type="default" className="uppercase tracking-wider">
                                    {runType}
                                </LemonTag>
                            }
                            label="Type"
                        />
                    )}
                    <Stat
                        value={historyLoading ? '–' : String(baselineUpdates)}
                        label={baselineUpdates === 1 ? 'Baseline update' : 'Baseline updates'}
                    />
                    <Stat value={firstSeen ? dayjs(firstSeen).fromNow() : '–'} label="First captured" />
                    {repoFullName && (
                        <Stat
                            value={
                                <Link
                                    to={`https://github.com/${repoFullName}`}
                                    target="_blank"
                                    className="font-mono text-default"
                                >
                                    {repoFullName}
                                </Link>
                            }
                            label="Repo"
                        />
                    )}
                </div>

                {historyLoading || repoLoading ? (
                    <div className="flex flex-col gap-4">
                        <LemonSkeleton className="h-32 w-full" />
                        <LemonSkeleton className="h-32 w-full" />
                    </div>
                ) : history.length === 0 ? (
                    <LemonBanner type="info">No history yet for this snapshot.</LemonBanner>
                ) : (
                    <div className="flex flex-col">
                        {pairedHistory.map((pair: ThemePair, i: number) => (
                            <HistoryRow
                                key={`${pair.runId}-${pair.primary.snapshot_id}`}
                                pair={pair}
                                isCurrent={i === 0}
                                isLast={i === pairedHistory.length - 1}
                                repoFullName={repoFullName}
                            />
                        ))}
                    </div>
                )}
            </div>
        </SceneContent>
    )
}

export default VisualReviewSnapshotHistoryScene
