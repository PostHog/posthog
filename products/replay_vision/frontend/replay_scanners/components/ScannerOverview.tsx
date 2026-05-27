import { useValues } from 'kea'
import { useMemo, useState } from 'react'

import { LemonInput, LemonTag, Link } from '@posthog/lemon-ui'

import { Sparkline } from 'lib/components/Sparkline'
import { dayjs } from 'lib/dayjs'
import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { urls } from 'scenes/urls'

import type { ReplayObservationApi } from '../../generated/api.schemas'
import { replayScannerLogic } from '../replayScannerLogic'
import { ScannerType } from '../types'

const OVER_TIME_DAYS = 14

function readModelOutput(obs: ReplayObservationApi): Record<string, unknown> | null {
    const output = obs.scanner_result?.model_output
    return output && typeof output === 'object' ? (output as Record<string, unknown>) : null
}

function readConfig(observations: ReplayObservationApi[]): Record<string, unknown> {
    const cfg = observations[0]?.scanner_snapshot?.scanner_config
    return cfg && typeof cfg === 'object' ? (cfg as Record<string, unknown>) : {}
}

function confidenceBucket(value: number): 'low' | 'medium' | 'high' {
    if (value >= 0.8) {
        return 'high'
    }
    if (value >= 0.5) {
        return 'medium'
    }
    return 'low'
}

/** Buckets observations by day for the last N days; returns counts oldest-first. */
function dailyBuckets(
    observations: ReplayObservationApi[],
    project: (out: Record<string, unknown>) => number | null
): number[] {
    const buckets = Array.from({ length: OVER_TIME_DAYS }, () => ({ total: 0, count: 0 }))
    const cutoff = dayjs()
        .startOf('day')
        .subtract(OVER_TIME_DAYS - 1, 'day')
    for (const obs of observations) {
        const out = readModelOutput(obs)
        if (!out) {
            continue
        }
        const value = project(out)
        if (value === null) {
            continue
        }
        const day = dayjs(obs.created_at).startOf('day')
        const offset = day.diff(cutoff, 'day')
        if (offset < 0 || offset >= OVER_TIME_DAYS) {
            continue
        }
        buckets[offset].total += value
        buckets[offset].count += 1
    }
    return buckets.map((b) => b.count)
}

function dailyAverages(
    observations: ReplayObservationApi[],
    project: (out: Record<string, unknown>) => number | null
): number[] {
    const buckets = Array.from({ length: OVER_TIME_DAYS }, () => ({ total: 0, count: 0 }))
    const cutoff = dayjs()
        .startOf('day')
        .subtract(OVER_TIME_DAYS - 1, 'day')
    for (const obs of observations) {
        const out = readModelOutput(obs)
        if (!out) {
            continue
        }
        const value = project(out)
        if (value === null) {
            continue
        }
        const day = dayjs(obs.created_at).startOf('day')
        const offset = day.diff(cutoff, 'day')
        if (offset < 0 || offset >= OVER_TIME_DAYS) {
            continue
        }
        buckets[offset].total += value
        buckets[offset].count += 1
    }
    return buckets.map((b) => (b.count > 0 ? b.total / b.count : 0))
}

function dailyLabels(): string[] {
    const cutoff = dayjs()
        .startOf('day')
        .subtract(OVER_TIME_DAYS - 1, 'day')
    return Array.from({ length: OVER_TIME_DAYS }, (_, i) => cutoff.add(i, 'day').format('MMM D'))
}

function OverviewPanel({
    title,
    subtitle,
    children,
}: {
    title: string
    subtitle?: React.ReactNode
    children: React.ReactNode
}): JSX.Element {
    return (
        <div className="border rounded p-4 bg-surface-primary space-y-3">
            <div className="flex items-baseline justify-between gap-2">
                <span className="text-sm font-medium">{title}</span>
                {subtitle && <span className="text-xs text-muted tabular-nums">{subtitle}</span>}
            </div>
            {children}
        </div>
    )
}

function MonitorOverview({ observations }: { observations: ReplayObservationApi[] }): JSX.Element | null {
    const stats = useMemo(() => {
        const yes = { low: 0, medium: 0, high: 0, total: 0 }
        const no = { low: 0, medium: 0, high: 0, total: 0 }
        for (const obs of observations) {
            const out = readModelOutput(obs)
            if (!out) {
                continue
            }
            const target = out.verdict ? yes : no
            target.total += 1
            if (typeof out.confidence === 'number') {
                target[confidenceBucket(out.confidence)] += 1
            }
        }
        return { yes, no }
    }, [observations])

    const total = stats.yes.total + stats.no.total
    const verdictTrend = useMemo(() => dailyBuckets(observations, (out) => (out.verdict ? 1 : 0)), [observations])
    if (total === 0) {
        return null
    }
    const yesPct = Math.round((stats.yes.total / total) * 100)

    return (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <OverviewPanel title="Verdict mix" subtitle={`${total} verdict${total === 1 ? '' : 's'}`}>
                <LemonProgress percent={yesPct} />
                <div className="flex items-center gap-4 text-sm">
                    <span className="flex items-center gap-2">
                        <LemonTag type="success">Yes</LemonTag>
                        <span className="tabular-nums">
                            {stats.yes.total} ({yesPct}%)
                        </span>
                    </span>
                    <span className="flex items-center gap-2">
                        <LemonTag type="default">No</LemonTag>
                        <span className="tabular-nums">
                            {stats.no.total} ({100 - yesPct}%)
                        </span>
                    </span>
                </div>
            </OverviewPanel>

            <OverviewPanel title="Verdict × confidence">
                <div className="grid grid-cols-[auto_repeat(3,1fr)] gap-x-3 gap-y-1.5 text-sm tabular-nums">
                    <div />
                    <div className="text-xs text-muted text-center">Low</div>
                    <div className="text-xs text-muted text-center">Med</div>
                    <div className="text-xs text-muted text-center">High</div>
                    <div className="flex items-center">
                        <LemonTag type="success">Yes</LemonTag>
                    </div>
                    <div className="text-center">{stats.yes.low}</div>
                    <div className="text-center">{stats.yes.medium}</div>
                    <div className="text-center">{stats.yes.high}</div>
                    <div className="flex items-center">
                        <LemonTag type="default">No</LemonTag>
                    </div>
                    <div className="text-center">{stats.no.low}</div>
                    <div className="text-center">{stats.no.medium}</div>
                    <div className="text-center">{stats.no.high}</div>
                </div>
            </OverviewPanel>

            <OverviewPanel
                title={`Yes verdicts (last ${OVER_TIME_DAYS} days)`}
                subtitle={`${verdictTrend.reduce((a, b) => a + b, 0)} total`}
            >
                <Sparkline data={verdictTrend} labels={dailyLabels()} className="h-16" />
            </OverviewPanel>
        </div>
    )
}

function ClassifierOverview({ observations }: { observations: ReplayObservationApi[] }): JSX.Element | null {
    const { counts, totalWithTags, fixedCount, freeformCount, configuredTags } = useMemo(() => {
        const config = readConfig(observations)
        const fixedSet = new Set(
            Array.isArray(config.tags)
                ? (config.tags as unknown[]).filter((t): t is string => typeof t === 'string')
                : []
        )
        const counts = new Map<string, number>()
        let total = 0
        let fixed = 0
        let freeform = 0
        for (const obs of observations) {
            const out = readModelOutput(obs)
            const tags = out && Array.isArray(out.tags) ? (out.tags as unknown[]) : []
            if (tags.length === 0) {
                continue
            }
            total += 1
            for (const tag of tags) {
                if (typeof tag !== 'string') {
                    continue
                }
                counts.set(tag, (counts.get(tag) ?? 0) + 1)
                if (fixedSet.has(tag)) {
                    fixed += 1
                } else {
                    freeform += 1
                }
            }
        }
        return {
            counts,
            totalWithTags: total,
            fixedCount: fixed,
            freeformCount: freeform,
            configuredTags: Array.from(fixedSet),
        }
    }, [observations])

    if (totalWithTags === 0) {
        return null
    }
    const ranked = Array.from(counts.entries())
        .sort((a, b) => b[1] - a[1])
        .slice(0, 10)
    const maxCount = ranked[0]?.[1] ?? 1
    const emittedSet = new Set(counts.keys())
    const unusedTags = configuredTags.filter((t) => !emittedSet.has(t))
    const tagTotal = fixedCount + freeformCount
    const fixedPct = tagTotal > 0 ? Math.round((fixedCount / tagTotal) * 100) : 0

    return (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <OverviewPanel
                title="Top tags"
                subtitle={`${counts.size} unique across ${totalWithTags} observation${totalWithTags === 1 ? '' : 's'}`}
            >
                <div className="space-y-1.5">
                    {ranked.map(([tag, count]) => (
                        <div key={tag} className="flex items-center gap-2">
                            <LemonTag type="option" className="shrink-0">
                                {tag}
                            </LemonTag>
                            <LemonProgress percent={Math.round((count / maxCount) * 100)} />
                            <span className="text-xs text-muted tabular-nums w-8 text-right">{count}</span>
                        </div>
                    ))}
                </div>
            </OverviewPanel>

            <OverviewPanel title="Fixed vs freeform" subtitle={`${tagTotal} tag${tagTotal === 1 ? '' : 's'} emitted`}>
                <LemonProgress percent={fixedPct} />
                <div className="flex items-center gap-4 text-sm">
                    <span className="flex items-center gap-2">
                        <LemonTag type="option">Fixed</LemonTag>
                        <span className="tabular-nums">
                            {fixedCount} ({fixedPct}%)
                        </span>
                    </span>
                    <span className="flex items-center gap-2">
                        <LemonTag type="default">Freeform</LemonTag>
                        <span className="tabular-nums">
                            {freeformCount} ({100 - fixedPct}%)
                        </span>
                    </span>
                </div>
            </OverviewPanel>

            {unusedTags.length > 0 && (
                <OverviewPanel title="Unused configured tags" subtitle={`${unusedTags.length} never emitted`}>
                    <div className="flex flex-wrap gap-1">
                        {unusedTags.map((tag) => (
                            <LemonTag key={tag} type="muted" size="small">
                                {tag}
                            </LemonTag>
                        ))}
                    </div>
                </OverviewPanel>
            )}
        </div>
    )
}

function ScorerOverview({ observations }: { observations: ReplayObservationApi[] }): JSX.Element | null {
    const { scored, sortedAsc, sortedDesc, scoreTrend } = useMemo(() => {
        const items: { obs: ReplayObservationApi; score: number }[] = []
        for (const obs of observations) {
            const out = readModelOutput(obs)
            if (out && typeof out.score === 'number') {
                items.push({ obs, score: out.score })
            }
        }
        const asc = [...items].sort((a, b) => a.score - b.score).slice(0, 5)
        const desc = [...items].sort((a, b) => b.score - a.score).slice(0, 5)
        const trend = dailyAverages(observations, (out) => (typeof out.score === 'number' ? out.score : null))
        return { scored: items.map((i) => i.score), sortedAsc: asc, sortedDesc: desc, scoreTrend: trend }
    }, [observations])

    if (scored.length === 0) {
        return null
    }
    const min = Math.min(...scored)
    const max = Math.max(...scored)
    const avg = scored.reduce((a, b) => a + b, 0) / scored.length

    const bucketCount = 10
    const range = Math.max(max - min, 1)
    const buckets: number[] = Array.from({ length: bucketCount }, () => 0)
    for (const score of scored) {
        const index = Math.min(bucketCount - 1, Math.floor(((score - min) / range) * bucketCount))
        buckets[index] += 1
    }
    const peakBucket = Math.max(...buckets, 1)

    const renderRanked = (items: typeof sortedDesc): JSX.Element => (
        <div className="space-y-1.5 text-sm">
            {items.map(({ obs, score }) => (
                <div key={obs.id} className="flex items-center justify-between gap-2">
                    <Link to={urls.replayVisionObservation(obs.id)} className="font-mono text-xs truncate">
                        {obs.session_id}
                    </Link>
                    <span className="font-semibold tabular-nums shrink-0">{score.toFixed(1)}</span>
                </div>
            ))}
        </div>
    )

    return (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <OverviewPanel title="Score distribution" subtitle={`${scored.length} scored`}>
                <div className="flex items-end gap-1 h-24">
                    {buckets.map((count, i) => (
                        <div
                            key={i}
                            className="flex-1 bg-primary/30 rounded-t"
                            style={{ height: `${(count / peakBucket) * 100}%` }}
                            title={`${count} observation${count === 1 ? '' : 's'}`}
                        />
                    ))}
                </div>
                <div className="flex items-center justify-between text-xs text-muted tabular-nums">
                    <span>min {min.toFixed(1)}</span>
                    <span>avg {avg.toFixed(1)}</span>
                    <span>max {max.toFixed(1)}</span>
                </div>
            </OverviewPanel>

            <OverviewPanel title={`Average score (last ${OVER_TIME_DAYS} days)`}>
                <Sparkline data={scoreTrend} labels={dailyLabels()} className="h-16" />
            </OverviewPanel>

            <OverviewPanel title="Top scoring">{renderRanked(sortedDesc)}</OverviewPanel>
            <OverviewPanel title="Bottom scoring">{renderRanked(sortedAsc)}</OverviewPanel>
        </div>
    )
}

function SummarizerOverview({ observations }: { observations: ReplayObservationApi[] }): JSX.Element | null {
    const [search, setSearch] = useState('')

    const summaries = useMemo(() => {
        const items: { obs: ReplayObservationApi; title: string | null; summary: string }[] = []
        for (const obs of observations) {
            const out = readModelOutput(obs)
            if (!out) {
                continue
            }
            const summary = typeof out.summary === 'string' ? out.summary : null
            if (!summary) {
                continue
            }
            const title = typeof out.title === 'string' ? out.title : null
            items.push({ obs, title, summary })
        }
        return items
    }, [observations])

    if (summaries.length === 0) {
        return null
    }

    const query = search.trim().toLowerCase()
    const filtered = query
        ? summaries.filter(
              (s) => s.summary.toLowerCase().includes(query) || (s.title && s.title.toLowerCase().includes(query))
          )
        : summaries.slice(0, 5)

    return (
        <OverviewPanel
            title={query ? 'Matching summaries' : 'Recent summaries'}
            subtitle={`${query ? filtered.length : summaries.length} ${query ? 'match' : 'total'}${
                (query ? filtered.length : summaries.length) === 1 ? '' : 'es'
            }`}
        >
            <LemonInput type="search" placeholder="Search summaries…" value={search} onChange={setSearch} fullWidth />
            <div className="space-y-2 max-h-96 overflow-y-auto">
                {filtered.length === 0 ? (
                    <div className="text-muted text-sm py-2">No summaries match.</div>
                ) : (
                    filtered.map((s) => (
                        <Link
                            key={s.obs.id}
                            to={urls.replayVisionObservation(s.obs.id)}
                            className="block border rounded p-2 bg-bg-light hover:bg-bg-3000"
                        >
                            {s.title && <div className="font-semibold text-sm">{s.title}</div>}
                            <div className="text-sm text-muted line-clamp-2">{s.summary}</div>
                        </Link>
                    ))
                )}
            </div>
        </OverviewPanel>
    )
}

export function ScannerOverview({ scannerId, tabId }: { scannerId: string; tabId: string }): JSX.Element | null {
    const { scanner, observations } = useValues(replayScannerLogic({ id: scannerId, tabId }))
    if (!scanner) {
        return null
    }
    const succeeded = observations.filter((o) => o.status === 'succeeded')
    const scannerType: ScannerType = scanner.scanner_type
    if (scannerType === 'monitor') {
        return <MonitorOverview observations={succeeded} />
    }
    if (scannerType === 'classifier') {
        return <ClassifierOverview observations={succeeded} />
    }
    if (scannerType === 'scorer') {
        return <ScorerOverview observations={succeeded} />
    }
    if (scannerType === 'summarizer') {
        return <SummarizerOverview observations={succeeded} />
    }
    return null
}
