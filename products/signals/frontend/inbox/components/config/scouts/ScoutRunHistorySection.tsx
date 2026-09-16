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
    groupScoutRuns,
    normalizeRunStatus,
    runDurationSeconds,
    runMatchesFilter,
    runProducedOutput,
    runReportActivity,
    ScoutRunFilter,
    ScoutRunGroup,
    scoutRunFailureLine,
    scoutRunGroupKey,
    scoutRunReportLabel,
    SCOUT_NO_RECENT_RUNS,
    SCOUT_RUNS_PER_SCOUT_LABEL,
} from '../../../utils/scoutRunsWindow'
import { ScoutTimestamp } from './ScoutTimestamp'

// This pill matches any run that produced output, either a signal finding or report activity, so its
// label names neither channel. Each row names the channel its own run used.
const FILTERS: { value: ScoutRunFilter; label: string }[] = [
    { value: 'all', label: 'All' },
    { value: 'emitted', label: 'Found something' },
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

/** Chevron that points down when open, right when shut. Shared by run rows and folded groups. */
function ExpandChevron({ expanded }: { expanded: boolean }): JSX.Element {
    return (
        <IconChevronDown
            className={`size-4 shrink-0 text-muted transition-transform ${expanded ? '' : '-rotate-90'}`}
        />
    )
}

/** The times a folded group spans: one timestamp for a lone run, first-to-last for several. */
function GroupTimeSpan({ runs }: { runs: SignalScoutRunSummary[] }): JSX.Element | null {
    // Rows are newest first, so the group's last entry is its earliest run.
    const newest = runs[0]?.started_at
    const oldest = runs[runs.length - 1]?.started_at
    if (!newest) {
        return null
    }
    if (!oldest || oldest === newest) {
        return <ScoutTimestamp time={newest} />
    }
    return (
        <span className="flex flex-wrap items-center gap-x-1">
            <ScoutTimestamp time={oldest} />
            <span className="text-[11px] text-muted">to</span>
            <ScoutTimestamp time={newest} />
        </span>
    )
}

/**
 * What a run produced: its findings if it emitted any, otherwise its report activity. A run can
 * file a report and then fail, so this is shown for a failed run too.
 */
function RunOutputTag({ run }: { run: SignalScoutRunSummary }): JSX.Element | null {
    const emitted = run.emitted_count ?? 0
    if (emitted > 0) {
        return (
            <LemonTag type="highlight" size="small">
                {pluralize(emitted, 'signal')} emitted
            </LemonTag>
        )
    }
    const reportLabel = scoutRunReportLabel(run)
    return reportLabel ? (
        <LemonTag type="highlight" size="small">
            {reportLabel}
        </LemonTag>
    ) : null
}

/** Records that a folded group was opened, so we can see whether the folded rows get read. */
function captureExpandRunGroup(skillName: string, kind: 'quiet' | 'failed', size: number): void {
    captureScoutAction({
        actionType: 'expand_run_group',
        surface: 'scout_detail',
        skillName,
        extra: { group_kind: kind, group_size: size },
    })
}

/**
 * Consecutive runs that found nothing, folded into one line: how many, when, and that no report
 * changed. A scout's history is mostly quiet, so a flat list spends its first screen on runs that
 * found nothing. Expanding restores the individual rows. A lone quiet run keeps the same one-line
 * shape, so the list does not switch grammar for a group of one.
 */
function QuietRunGroup({ runs, skillName }: { runs: SignalScoutRunSummary[]; skillName: string }): JSX.Element {
    const [expanded, setExpanded] = useState(false)

    return (
        <div className="flex flex-col border-b border-primary last:border-b-0">
            <button
                type="button"
                onClick={() => {
                    if (!expanded) {
                        captureExpandRunGroup(skillName, 'quiet', runs.length)
                    }
                    setExpanded((value) => !value)
                }}
                className="flex flex-wrap items-center gap-x-2 gap-y-0.5 px-3 py-2 text-left transition-colors hover:bg-surface-secondary"
                aria-expanded={expanded}
            >
                <ExpandChevron expanded={expanded} />
                <span className="text-muted text-sm leading-none">·</span>
                <span className="whitespace-nowrap text-[11px] text-muted">
                    {runs.length === 1 ? '1 quiet run' : `${runs.length} quiet runs`}
                </span>
                <GroupTimeSpan runs={runs} />
                <span className="flex-1" />
                <span className="whitespace-nowrap text-[11px] text-muted">no report changed</span>
            </button>
            {expanded && runs.map((run) => <ScoutRunRow key={run.run_id} run={run} skillName={skillName} />)}
        </div>
    )
}

/**
 * Consecutive failures, folded into one danger-tinted group: the count and time span, then one line
 * per run with its time, whether it merely ran out of time, what it managed to say, and its own
 * task-run link. Failures are what a reader opens this list for, so they stay readable without
 * expanding anything.
 */
function FailedRunGroup({ runs, skillName }: { runs: SignalScoutRunSummary[]; skillName: string }): JSX.Element {
    const now = new Date()

    return (
        <div className="flex flex-col border-b border-primary bg-danger-highlight last:border-b-0">
            <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 px-3 py-2">
                <span className="text-danger text-sm font-medium leading-none">✗</span>
                <span className="whitespace-nowrap text-[11px] font-medium text-danger">
                    {runs.length === 1 ? '1 run failed' : `${runs.length} runs failed`}
                </span>
                <GroupTimeSpan runs={runs} />
            </div>
            {runs.map((run) => (
                <div
                    key={run.run_id}
                    className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 px-3 pb-2 pl-9 text-[13px] leading-snug"
                >
                    <ScoutTimestamp time={run.started_at} />
                    {/* A run that only hit its deadline is marked, in the colour an unfolded row
                        gives it. An error carries no mark: the group header already says failed,
                        in the same red a row would use. */}
                    {deriveRunFailureKind(run, now) === 'timed_out' && (
                        <span className="whitespace-nowrap text-[11px] text-warning">· timed out</span>
                    )}
                    <span className="min-w-0 flex-1 text-secondary">{scoutRunFailureLine(run, now)}</span>
                    <RunOutputTag run={run} />
                    {run.task_url && (
                        <Link
                            to={run.task_url}
                            className="flex shrink-0 items-center gap-1 text-xs font-medium"
                            onClick={() =>
                                captureScoutAction({
                                    actionType: 'open_task_run',
                                    surface: 'scout_detail',
                                    skillName,
                                    extra: { run_id: run.run_id, run_status: 'failed' },
                                })
                            }
                        >
                            Open task run <IconExternal className="size-3" />
                        </Link>
                    )}
                </div>
            ))}
        </div>
    )
}

/**
 * One run in the history list. Shares the collapse/expand grammar of `ScoutEmissionCard`: a header
 * (chevron · glyph · timestamp · duration · failure · report activity) that stays visible, the run
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
                <ExpandChevron expanded={expanded} />
                <RunGlyph run={run} />
                <ScoutTimestamp time={run.started_at} />
                {duration && <span className="whitespace-nowrap text-[11px] text-muted">· {duration}</span>}
                {/* One colour per failure kind, matching the glyph — a red glyph next to amber text
                    read as two different states of the same run. */}
                {failureKind && (
                    <span
                        className={`whitespace-nowrap text-[11px] ${
                            failureKind === 'timed_out' ? 'text-warning' : 'text-danger'
                        }`}
                    >
                        · {failureKind === 'timed_out' ? 'timed out' : 'failed'}
                    </span>
                )}
                <span className="flex-1" />
                <RunOutputTag run={run} />
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
                                    Filed report <IconArrowRight className="size-3" />
                                </Link>
                            ))}
                            {editedReportIds.map((reportId) => (
                                <Link
                                    key={reportId}
                                    to={urls.inboxReport('reports', reportId)}
                                    className="flex items-center gap-1 font-medium shrink-0"
                                    onClick={() => captureOpenLinkedReport(skillName, reportId, 'edited')}
                                >
                                    Added to report <IconArrowRight className="size-3" />
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

/** This scout's runs in the recent window, newest first. */
function useScoutRuns(skillName: string): SignalScoutRunSummary[] {
    const { rollups } = useValues(scoutFleetLogic)
    return useMemo(() => {
        // Newest first for a history list; the rollup keeps runs oldest-first for the header timeline.
        const windowRuns = rollups.get(skillName)?.runs ?? []
        return [...windowRuns].reverse()
    }, [rollups, skillName])
}

/**
 * The All / Found something / Quiet / Failed pills, each with its match count. They live in the Runs
 * tab bar's right slot rather than above the list, so the tab bar carries both what you are looking
 * at and how it is narrowed.
 */
export function ScoutRunFilterPills({
    skillName,
    filter,
    onChange,
}: {
    skillName: string
    filter: ScoutRunFilter
    onChange: (filter: ScoutRunFilter) => void
}): JSX.Element {
    const runs = useScoutRuns(skillName)
    const filterCounts = useMemo(() => {
        const counts = new Map<ScoutRunFilter, number>()
        for (const entry of FILTERS) {
            counts.set(entry.value, runs.filter((run) => runMatchesFilter(run, entry.value)).length)
        }
        return counts
    }, [runs])

    return (
        <div className="flex flex-wrap items-center gap-1">
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
                        onChange(entry.value)
                    }}
                >
                    {entry.label} {filterCounts.get(entry.value) ?? 0}
                </LemonButton>
            ))}
        </div>
    )
}

/**
 * The Runs tab on the scout detail surface: this scout's runs in the recent window, newest first,
 * with consecutive quiet runs and consecutive failures each folded into one entry. Runs come from
 * `scoutFleetLogic`'s already-polled per-scout rollup (oldest-first timeline order, reversed here);
 * the tab bar's filter pills narrow that set client-side.
 *
 * Folding is skipped while a filter is on: a list of nothing but quiet runs folded into one row
 * would hide what the reader just asked to see.
 */
export function ScoutRunHistorySection({
    skillName,
    filter,
}: {
    skillName: string
    filter: ScoutRunFilter
}): JSX.Element {
    const { scoutRunsLoadedOnce } = useValues(scoutFleetLogic)
    const runs = useScoutRuns(skillName)

    const filteredRuns = useMemo(() => runs.filter((run) => runMatchesFilter(run, filter)), [runs, filter])
    const groups = useMemo(
        (): ScoutRunGroup[] =>
            filter === 'all' ? groupScoutRuns(filteredRuns) : filteredRuns.map((run) => ({ kind: 'run', run })),
        [filteredRuns, filter]
    )

    // Hold the skeleton until the fleet's per-scout runs have settled once — otherwise a fresh
    // deep-link flashes the empty state before we know this scout's runs.
    if (!scoutRunsLoadedOnce) {
        return <LemonSkeleton className="h-12 w-full rounded" />
    }

    if (groups.length === 0) {
        return (
            <div className="rounded border border-dashed border-primary bg-surface-primary px-4 py-6 text-center text-sm text-muted">
                {runs.length > 0
                    ? `No runs match this filter in the ${SCOUT_RUNS_PER_SCOUT_LABEL}.`
                    : SCOUT_NO_RECENT_RUNS}
            </div>
        )
    }

    return (
        <div className="flex flex-col gap-2">
            {/* One card with attached rows, rather than a stack of separate bordered cards — a run
                list reads as a log, and 25 individually-bordered boxes is a lot of chrome for it. */}
            <div className="overflow-hidden rounded border border-primary bg-surface-primary">
                {groups.map((group) =>
                    group.kind === 'run' ? (
                        <ScoutRunRow key={scoutRunGroupKey(group)} run={group.run} skillName={skillName} />
                    ) : group.kind === 'quiet' ? (
                        <QuietRunGroup key={scoutRunGroupKey(group)} runs={group.runs} skillName={skillName} />
                    ) : (
                        <FailedRunGroup key={scoutRunGroupKey(group)} runs={group.runs} skillName={skillName} />
                    )
                )}
            </div>
            <span className="text-[11px] text-muted">From the {SCOUT_RUNS_PER_SCOUT_LABEL}.</span>
        </div>
    )
}
