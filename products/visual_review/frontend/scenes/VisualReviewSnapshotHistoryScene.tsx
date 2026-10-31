import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { LemonBanner, LemonButton, LemonSkeleton, LemonTag, Link } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'

import { QuarantineAction } from '../components/QuarantineAction'
import type { OnQuarantine } from '../components/QuarantineModal'
import { SnapshotChangeBadge, hasSnapshotChangeBadge } from '../components/SnapshotChangeBadge'
import { VisualReviewSceneTitle } from '../components/VisualReviewSceneTitle'
import { VisualReviewTabs } from '../components/VisualReviewTabs'
import { VisualReviewTrail } from '../components/VisualReviewTrail'
import type { QuarantinedIdentifierEntryApi, SnapshotHistoryEntryApi } from '../generated/api.schemas'
import { repoFullNameFromParams, runPath, splitRepoFullName } from '../lib/repoPaths'
import { mergeQueueBatchLeaderPrNumber } from '../lib/runPredicates'
import {
    ThemePair,
    VisualReviewSnapshotHistorySceneLogicProps,
    visualReviewSnapshotHistorySceneLogic,
} from './visualReviewSnapshotHistorySceneLogic'

export const scene: SceneExport = {
    component: VisualReviewSnapshotHistoryScene,
    logic: visualReviewSnapshotHistorySceneLogic,
    paramsToProps: ({
        params: { repoOwner, repoName, runType, identifier },
    }): VisualReviewSnapshotHistorySceneLogicProps => ({
        repoFullName: repoFullNameFromParams(repoOwner, repoName),
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
function runUrl(entry: SnapshotHistoryEntryApi, repoFullName: string): string {
    return `${runPath(entry.run_id, repoFullName)}#snapshot=${encodeURIComponent(entry.snapshot_id)}`
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
    repoFullName: string
}): JSX.Element {
    const entry = pair.primary
    const reason = REASON_TAGS[entry.result] ?? { label: entry.result, type: 'default' as const }
    const prUrl = entry.pr_number ? `https://github.com/${repoFullName}/pull/${entry.pr_number}` : null
    const commitUrl = `https://github.com/${repoFullName}/commit/${entry.commit_sha}`
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
                    <Link to={runUrl(entry, repoFullName)} className="font-mono text-default">
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
                    <Link to={commitUrl} target="_blank" className="font-mono">
                        {entry.commit_sha.slice(0, 8)}
                    </Link>
                    {hasSnapshotChangeBadge(entry) && (
                        <>
                            <span>·</span>
                            <SnapshotChangeBadge snapshot={entry} size="small" />
                        </>
                    )}
                </div>

                <div className={`grid gap-2 ${showPair ? 'grid-cols-2' : 'grid-cols-1 w-1/2'}`}>
                    <Link to={runUrl(pair.primary, repoFullName)} className="contents">
                        <ThemePane entry={pair.primary} theme={pair.primaryTheme} />
                    </Link>
                    {showPair &&
                        (pair.partner ? (
                            <Link to={runUrl(pair.partner, repoFullName)} className="contents">
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

interface QuarantineVariant {
    identifier: string
    label: string | null
    quarantineEntry: QuarantinedIdentifierEntryApi | null
    onUnquarantine: () => void
}

function QuarantineBanner({
    identifier,
    label,
    quarantineEntry,
    onQuarantine,
    onUnquarantine,
    repoFullName,
}: {
    identifier: string
    repoFullName: string
    label: string | null
    quarantineEntry: QuarantinedIdentifierEntryApi
    onQuarantine: OnQuarantine
    onUnquarantine: () => void
}): JSX.Element {
    const expires = quarantineEntry.expires_at ? new Date(quarantineEntry.expires_at) : null
    const sourceRun = quarantineEntry.source_run ?? null
    const batchLeaderPrNumber = sourceRun ? mergeQueueBatchLeaderPrNumber(sourceRun.branch) : null
    const pullUrl = (prNumber: number): string => `https://github.com/${repoFullName}/pull/${prNumber}`
    const openConfirmation = (): void => {
        LemonDialog.open({
            title: `Unquarantine ${label ? `(${label})` : 'this identifier'}?`,
            description:
                'This identifier will be gated on again in future runs. ' +
                "Branches that haven't merged the fix may get blocked.",
            primaryButton: {
                children: 'Unquarantine',
                status: 'danger',
                onClick: onUnquarantine,
            },
            secondaryButton: { children: 'Cancel' },
        })
    }
    return (
        <LemonBanner type="warning">
            <div className="text-sm flex flex-col gap-1">
                <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                    <span>
                        <span className="font-semibold">Quarantined{label && ` (${label})`}:</span>{' '}
                        {quarantineEntry.reason || 'no reason given'}
                    </span>
                    <span aria-hidden>·</span>
                    {expires ? (
                        <span>
                            until {expires.toLocaleDateString()}{' '}
                            <span className="text-muted">({dayjs(expires).fromNow()})</span>
                        </span>
                    ) : (
                        <span className="text-muted">no expiry set</span>
                    )}
                    {quarantineEntry.created_by && (
                        <>
                            <span aria-hidden>·</span>
                            <ProfilePicture user={quarantineEntry.created_by} size="xs" showName />
                        </>
                    )}
                </div>
                {sourceRun && (
                    <div className="text-xs text-muted flex flex-wrap items-center gap-x-2 gap-y-0.5">
                        {batchLeaderPrNumber ? (
                            <span>
                                Failed in the merge queue with{' '}
                                <Link
                                    to={pullUrl(batchLeaderPrNumber)}
                                    target="_blank"
                                    className="font-mono"
                                    data-attr="visual-review-quarantine-merge-queue-pr"
                                >
                                    #{batchLeaderPrNumber}
                                </Link>
                            </span>
                        ) : (
                            <>
                                <span>Failed on</span>
                                <span className="font-mono">{sourceRun.branch}</span>
                            </>
                        )}
                        <span aria-hidden>·</span>
                        <Link
                            to={`https://github.com/${repoFullName}/commit/${sourceRun.commit_sha}`}
                            target="_blank"
                            className="font-mono"
                        >
                            {sourceRun.commit_sha.slice(0, 8)}
                        </Link>
                        {sourceRun.pr_number && (
                            <>
                                <span aria-hidden>·</span>
                                <Link
                                    to={pullUrl(sourceRun.pr_number)}
                                    target="_blank"
                                    data-attr="visual-review-quarantine-source-pr"
                                >
                                    {batchLeaderPrNumber ? (
                                        'All PRs tested'
                                    ) : (
                                        <span className="font-mono">#{sourceRun.pr_number}</span>
                                    )}
                                </Link>
                            </>
                        )}
                        <span aria-hidden>·</span>
                        <TZLabel time={sourceRun.created_at} />
                    </div>
                )}
                <div className="flex flex-wrap items-center gap-2 pt-1">
                    {sourceRun && (
                        <LemonButton
                            type="secondary"
                            size="small"
                            to={runPath(sourceRun.id, repoFullName)}
                            data-attr="visual-review-quarantine-source-run"
                        >
                            View run
                        </LemonButton>
                    )}
                    <QuarantineAction
                        identifier={identifier}
                        onQuarantine={onQuarantine}
                        mode="extend"
                        triggerLabel={label ? `Extend (${label})` : 'Extend quarantine'}
                        initialReason={quarantineEntry.reason}
                        initialExpiresAt={quarantineEntry.expires_at}
                        sourceRunId={sourceRun?.id ?? null}
                    />
                    <LemonButton
                        type="secondary"
                        size="small"
                        status="danger"
                        onClick={openConfirmation}
                        data-attr="visual-review-history-unquarantine"
                    >
                        Unquarantine
                    </LemonButton>
                </div>
            </div>
        </LemonBanner>
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
    const {
        repo,
        repoLoading,
        repoNotFound,
        history,
        historyLoading,
        identifier,
        pairedHistory,
        primaryTheme,
        siblingIdentifier,
        runType,
        repoFullName: pathRepoFullName,
        quarantineEntry,
        quarantineEntryLoading,
        siblingQuarantineEntry,
        siblingQuarantineEntryLoading,
    } = useValues(visualReviewSnapshotHistorySceneLogic) as any
    const { quarantineIdentifier, unquarantineIdentifier, unquarantineSibling } = useActions(
        visualReviewSnapshotHistorySceneLogic
    ) as any

    const repoFullName: string = repo?.repo_full_name ?? pathRepoFullName
    const firstSeen = history.length > 0 ? history[history.length - 1].created_at : null
    const baselineUpdates = Math.max(0, history.length - 1)
    const hasThemePair = primaryTheme !== null && siblingIdentifier !== null
    const loadedVariants: QuarantineVariant[] = []
    if (!quarantineEntryLoading) {
        loadedVariants.push({
            identifier,
            label: hasThemePair ? primaryTheme : null,
            quarantineEntry,
            onUnquarantine: unquarantineIdentifier,
        })
    }
    if (hasThemePair && !siblingQuarantineEntryLoading) {
        loadedVariants.push({
            identifier: siblingIdentifier,
            label: primaryTheme === 'light' ? 'dark' : 'light',
            quarantineEntry: siblingQuarantineEntry,
            onUnquarantine: unquarantineSibling,
        })
    }

    if (repoNotFound) {
        return <NotFound object="visual review repo" />
    }

    return (
        <SceneContent>
            <VisualReviewSceneTitle repoFullName={pathRepoFullName} activeTab="snapshots" />
            <VisualReviewTabs activeKey="snapshots" repoFullName={pathRepoFullName} />
            <VisualReviewTrail
                crumbs={[
                    {
                        label: 'Snapshots',
                        to: urls.visualReviewSnapshotOverview(...splitRepoFullName(pathRepoFullName)),
                    },
                    { label: identifier },
                ]}
            />

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
                    <div className="ml-auto flex flex-wrap items-center gap-2">
                        {loadedVariants
                            .filter((variant) => !variant.quarantineEntry)
                            .map((variant) => (
                                <QuarantineAction
                                    key={variant.identifier}
                                    identifier={variant.identifier}
                                    onQuarantine={quarantineIdentifier}
                                    triggerLabel={variant.label ? `Quarantine (${variant.label})` : undefined}
                                    runType={runType}
                                />
                            ))}
                    </div>
                </div>

                {loadedVariants.map(
                    (variant) =>
                        variant.quarantineEntry && (
                            <QuarantineBanner
                                key={variant.identifier}
                                identifier={variant.identifier}
                                repoFullName={repoFullName}
                                label={variant.label}
                                quarantineEntry={variant.quarantineEntry}
                                onQuarantine={quarantineIdentifier}
                                onUnquarantine={variant.onUnquarantine}
                            />
                        )
                )}

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
