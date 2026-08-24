import { useValues } from 'kea'
import { memo, useMemo, useState } from 'react'

import { IconArrowRight, IconChevronDown, IconExternal } from '@posthog/icons'
import { LemonButton, LemonSkeleton, LemonTag, Link } from '@posthog/lemon-ui'

import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { pluralize } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import { captureScoutAction } from '../../../inboxAnalytics'
import { scoutFleetLogic } from '../../../logics/scoutFleetLogic'
import { SignalScoutRunSummary } from '../../../types'
import {
    deriveRunFailureKind,
    formatRunDuration,
    normalizeRunStatus,
    runDurationSeconds,
    runMatchesFilter,
    runProducedOutput,
    runReportActivity,
    ScoutRunFilter,
    scoutReportActivityLabel,
    SCOUT_NO_RECENT_RUNS,
    SCOUT_RUNS_PER_SCOUT_LABEL,
} from '../../../utils/scoutRunsWindow'
import { ScoutTimestamp } from './ScoutTimestamp'

const FILTERS: { value: ScoutRunFilter; label: string }[] = [
    { value: 'all', label: 'All' },
    { value: 'emitted', label: 'Emitted' },
    { value: 'quiet', label: 'Quiet' },
    { value: 'failed', label: 'Failed' },
]

function captureOpenLinkedReport(skillName: string, reportId: string, relationship: 'authored' | 'edited'): void {
    captureScoutAction({
        actionType: 'open_linked_report',
        surface: 'scout_detail',
        skillName,
        extra: { signal_report_id: reportId, report_relationship: relationship },
    })
}

/** Truncated mono id (run ids are long ULIDs; only the leading chunk earns a row footer). */
function truncateId(value: string): string {
    return value.length > 12 ? `${value.slice(0, 12)}…` : value
}

/** A compact status glyph: ✗ failed · pulsing dot running/queued · ◆ produced output (finding or
 * report) · · quiet. */
function RunGlyph({ run }: { run: SignalScoutRunSummary }): JSX.Element {
    const status = normalizeRunStatus(run.status)
    if (status === 'failed') {
        return <span className="text-danger text-sm font-medium leading-none">✗</span>
    }
    if (status === 'running' || status === 'queued') {
        return <span className="inline-block size-2 shrink-0 rounded-full bg-primary animate-pulse" />
    }
    if (runProducedOutput(run)) {
        return <span className="text-primary-3000 text-sm font-medium leading-none">◆</span>
    }
    return <span className="text-muted text-sm leading-none">·</span>
}

/**
 * One run in the history list. Shares the collapse/expand grammar of `ScoutEmissionCard`: a header
 * (chevron · glyph · timestamp · duration · failure · emitted count) that stays visible, the run
 * summary markdown (2-line preview collapsed, full expanded), and an id/task-run footer when open.
 *
 * Memoized because the 60s runs-window poll re-renders the whole history list; `loadRunsWindow`
 * reconciles run identity (see `reconcileById`) so unchanged runs keep their reference and skip here.
 */
const ScoutRunRow = memo(function ScoutRunRow({
    run,
    skillName,
}: {
    run: SignalScoutRunSummary
    skillName: string
}): JSX.Element {
    const [expanded, setExpanded] = useState(false)
    const now = new Date()
    const status = normalizeRunStatus(run.status)
    const failureKind = deriveRunFailureKind(run, now)
    const duration = formatRunDuration(runDurationSeconds(run, now))
    const emitted = run.emitted_count ?? 0
    const reportActivityLabel = scoutReportActivityLabel(run)
    const { authored: authoredReportIds, edited: editedReportIds } = runReportActivity(run)
    const hasBody = Boolean(run.summary) || status === 'failed' || expanded

    return (
        <div className="flex flex-col border-b border-primary last:border-b-0">
            <button
                type="button"
                onClick={() => {
                    captureScoutAction({
                        actionType: expanded ? 'collapse_run' : 'expand_run',
                        surface: 'scout_detail',
                        skillName,
                        extra: { run_id: run.run_id, run_status: status, emitted_count: emitted },
                    })
                    setExpanded((value) => !value)
                }}
                className="flex items-center gap-2 px-3 py-2.5 text-left transition-colors hover:bg-surface-secondary"
                aria-expanded={expanded}
            >
                <IconChevronDown
                    className={`size-4 shrink-0 text-muted transition-transform ${expanded ? '' : '-rotate-90'}`}
                />
                <RunGlyph run={run} />
                <ScoutTimestamp time={run.started_at} />
                {duration && <span className="whitespace-nowrap text-[11px] text-muted">· {duration}</span>}
                {failureKind && (
                    <span className="whitespace-nowrap text-[11px] text-warning">
                        · {failureKind === 'timed_out' ? 'timed out' : 'failed'}
                    </span>
                )}
                <span className="flex-1" />
                {emitted > 0 ? (
                    <LemonTag type="highlight" size="small">
                        {pluralize(emitted, 'signal')} emitted
                    </LemonTag>
                ) : reportActivityLabel ? (
                    <LemonTag type="highlight" size="small">
                        {reportActivityLabel}
                    </LemonTag>
                ) : null}
            </button>

            {hasBody && (
                <div className="px-3 pb-2.5 pl-9">
                    {run.summary ? (
                        <LemonMarkdown
                            disableImages
                            className={
                                expanded
                                    ? 'text-[13px] leading-snug text-secondary'
                                    : 'text-[13px] leading-snug text-secondary line-clamp-2'
                            }
                        >
                            {run.summary}
                        </LemonMarkdown>
                    ) : status === 'failed' ? (
                        <span className="text-[13px] italic text-muted">
                            No summary — the run ended before writing its close-out. The task run in PostHog is the only
                            diagnostic.
                        </span>
                    ) : null}

                    {expanded && (
                        <div className="mt-2.5 flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-primary pt-2 text-xs text-tertiary">
                            <span className="font-mono">{truncateId(run.run_id)}</span>
                            {authoredReportIds.map((reportId) => (
                                <Link
                                    key={reportId}
                                    to={urls.inboxReport('reports', reportId)}
                                    className="flex items-center gap-1 font-medium shrink-0"
                                    onClick={() => captureOpenLinkedReport(skillName, reportId, 'authored')}
                                >
                                    Authored report <IconArrowRight className="size-3" />
                                </Link>
                            ))}
                            {editedReportIds.map((reportId) => (
                                <Link
                                    key={reportId}
                                    to={urls.inboxReport('reports', reportId)}
                                    className="flex items-center gap-1 font-medium shrink-0"
                                    onClick={() => captureOpenLinkedReport(skillName, reportId, 'edited')}
                                >
                                    Edited report <IconArrowRight className="size-3" />
                                </Link>
                            ))}
                            {run.task_url && (
                                <>
                                    <span className="flex-1" />
                                    <Link
                                        to={run.task_url}
                                        className="flex items-center gap-1 font-medium shrink-0"
                                        onClick={() =>
                                            captureScoutAction({
                                                actionType: 'open_task_run',
                                                surface: 'scout_detail',
                                                skillName,
                                                extra: { run_id: run.run_id, run_status: status },
                                            })
                                        }
                                    >
                                        Open task run <IconExternal className="size-3" />
                                    </Link>
                                </>
                            )}
                        </div>
                    )}
                </div>
            )}
        </div>
    )
})

/**
 * The Runs section on the scout detail surface: this scout's runs in the recent window, newest
 * first, with All/Emitted/Quiet/Failed filter chips (each showing its match count). Runs come
 * from `scoutFleetLogic`'s already-polled per-scout rollup (oldest-first timeline order, reversed
 * here); the filter chips narrow that set client-side.
 */
export function ScoutRunHistorySection({ skillName }: { skillName: string }): JSX.Element {
    const { rollups, scoutRunsLoadedOnce } = useValues(scoutFleetLogic)
    const [filter, setFilter] = useState<ScoutRunFilter>('all')

    // Newest first for a history list; the rollup keeps runs oldest-first for the header timeline.
    const runs = useMemo(() => {
        const windowRuns = rollups.get(skillName)?.runs ?? []
        return [...windowRuns].reverse()
    }, [rollups, skillName])

    const filterCounts = useMemo(() => {
        const counts = new Map<ScoutRunFilter, number>()
        for (const entry of FILTERS) {
            counts.set(entry.value, runs.filter((run) => runMatchesFilter(run, entry.value)).length)
        }
        return counts
    }, [runs])

    const filteredRuns = useMemo(() => runs.filter((run) => runMatchesFilter(run, filter)), [runs, filter])

    // Hold the skeleton until the fleet's per-scout runs have settled once — otherwise a fresh
    // deep-link flashes the empty state before we know this scout's runs.
    const loading = !scoutRunsLoadedOnce

    return (
        <div className="flex flex-col gap-2">
            <div className="flex items-center gap-2 flex-wrap">
                <span className="text-xs font-medium text-default uppercase tracking-wide">Runs</span>
                <span className="flex-1" />
                {FILTERS.map((entry) => (
                    <LemonButton
                        key={entry.value}
                        size="xsmall"
                        type="tertiary"
                        active={filter === entry.value}
                        onClick={() => {
                            captureScoutAction({
                                actionType: 'filter_runs',
                                surface: 'scout_detail',
                                skillName,
                                extra: {
                                    filter: entry.value,
                                    filter_match_count: filterCounts.get(entry.value) ?? 0,
                                },
                            })
                            setFilter(entry.value)
                        }}
                    >
                        {entry.label} {filterCounts.get(entry.value) ?? 0}
                    </LemonButton>
                ))}
            </div>

            {loading ? (
                <LemonSkeleton className="h-12 w-full rounded" />
            ) : filteredRuns.length === 0 ? (
                <div className="rounded border border-dashed border-primary bg-surface-primary px-4 py-6 text-center text-sm text-muted">
                    {runs.length > 0
                        ? `No runs match this filter in the ${SCOUT_RUNS_PER_SCOUT_LABEL}.`
                        : SCOUT_NO_RECENT_RUNS}
                </div>
            ) : (
                // One card with attached rows, rather than a stack of separate bordered cards — a run
                // list reads as a log, and 25 individually-bordered boxes is a lot of chrome for it.
                <div className="overflow-hidden rounded border border-primary bg-surface-primary">
                    {filteredRuns.map((run) => (
                        <ScoutRunRow key={run.run_id} run={run} skillName={skillName} />
                    ))}
                </div>
            )}
        </div>
    )
}
