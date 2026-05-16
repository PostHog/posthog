import { useActions, useValues } from 'kea'
import { useCallback, useMemo, useState } from 'react'

import { IconChevronDown, IconChevronRight, IconPeople, IconRefresh } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'

import {
    DashboardReference,
    EventReach,
    FlagReach,
    FlagReference,
    GitHogPRImpactLogicProps,
    IssueReference,
    RelatedSignal,
    WebPathReach,
    gitHogPRImpactLogic,
} from '../gitHogPRImpactLogic'

function Star({ reason }: { reason?: string }): JSX.Element | null {
    if (!reason) {
        return null
    }
    return (
        <span
            className="text-warning text-sm leading-none shrink-0 cursor-help"
            title={reason}
            aria-label={`AI pick: ${reason}`}
        >
            ★
        </span>
    )
}

// Best-effort parse of the LLM's headline number. Handles "0", "1,234", "1.5k",
// "<10", "~50", and "0-10" (returns lower bound). Returns null on shapes we
// can't parse so we fall back to rendering the raw string.
function parseHeadlineNumber(headline: string | null | undefined): number | null {
    if (!headline) {
        return null
    }
    const cleaned = headline
        .replace(/\(.*?\)/g, '')
        .replace(/[~,\s≈]/g, '')
        .toLowerCase()
    if (
        cleaned === '' ||
        cleaned === '0' ||
        cleaned === '0.0' ||
        cleaned === '—' ||
        cleaned === '-' ||
        cleaned === 'none' ||
        cleaned === 'zero'
    ) {
        return 0
    }
    const range = cleaned.match(/^([0-9.]+)[-–]([0-9.]+)([kmb])?$/)
    if (range) {
        const n = parseFloat(range[1])
        return Number.isFinite(n) ? n : null
    }
    const m = cleaned.match(/^[<>]?=?([0-9.]+)([kmb])?$/)
    if (!m) {
        return null
    }
    let n = parseFloat(m[1])
    if (m[2] === 'k') {
        n *= 1_000
    } else if (m[2] === 'm') {
        n *= 1_000_000
    } else if (m[2] === 'b') {
        n *= 1_000_000_000
    }
    return Number.isFinite(n) ? n : null
}

const CONFIDENCE_STYLES: Record<'high' | 'medium' | 'low', { text: string; dot: string }> = {
    high: { text: 'text-success', dot: 'bg-success' },
    medium: { text: 'text-warning', dot: 'bg-warning' },
    low: { text: 'text-muted', dot: 'bg-muted' },
}

// Shape of an impact — different change types have different blast-radius
// stories and "X users" is only one of them. CI / migration / docs aren't
// measured in users at all.
type ImpactShape = 'ci' | 'infra' | 'migration' | 'docs' | 'styling' | 'feature' | 'mixed'

const IMPACT_SHAPE_DEFS: Record<
    ImpactShape,
    { label: string; description: string; tint: string; reachApplies: boolean }
> = {
    ci: {
        label: 'CI / build pipeline',
        description:
            'Affects every future build of this repo. Runtime user reach does not apply — see Risk above for safety implications.',
        tint: 'bg-bg-3000',
        reachApplies: false,
    },
    infra: {
        label: 'Infrastructure',
        description:
            'Touches deploy, container, or orchestration config. Potentially every production user on the next rollout.',
        tint: 'bg-warning-highlight',
        reachApplies: false,
    },
    migration: {
        label: 'Database migration',
        description:
            'Schema change — affects every existing row and every future write. Runtime user reach does not apply on a per-user basis.',
        tint: 'bg-warning-highlight',
        reachApplies: false,
    },
    docs: {
        label: 'Documentation',
        description: 'Markdown / docs only. No runtime impact.',
        tint: 'bg-bg-3000',
        reachApplies: false,
    },
    styling: {
        label: 'Styling change',
        description: 'CSS / visual only — everyone who renders the affected surfaces sees it.',
        tint: 'bg-bg-3000',
        reachApplies: true,
    },
    feature: { label: '', description: '', tint: 'bg-fill-highlight-50', reachApplies: true },
    mixed: { label: '', description: '', tint: 'bg-fill-highlight-50', reachApplies: true },
}

function detectImpactShape(
    files: string[],
    signals: { flags: boolean; events: boolean; pages: boolean; dashboards: boolean; issues: boolean }
): ImpactShape {
    if (!files || files.length === 0) {
        return 'mixed'
    }
    const lower = files.map((f) => f.toLowerCase())
    const all = (predicate: (f: string) => boolean): boolean => lower.every(predicate)

    if (
        all(
            (f) =>
                f.startsWith('.github/workflows/') ||
                /(^|\/)\.gitlab-ci\.yml$/.test(f) ||
                /(^|\/)\.circleci\//.test(f) ||
                /jenkinsfile/.test(f)
        )
    ) {
        return 'ci'
    }
    if (
        all((f) =>
            /(dockerfile|docker-compose|k8s|kubernetes|kustomization|helm|terraform|\.tf$|(^|\/)infra\/|(^|\/)deploy\/)/.test(
                f
            )
        )
    ) {
        return 'infra'
    }
    if (all((f) => /(^|\/)migrations?\//.test(f) || f.endsWith('.sql'))) {
        return 'migration'
    }
    if (all((f) => /\.(md|mdx|rst|txt|adoc)$/.test(f) || /(^|\/)docs?\//.test(f) || /(^|\/)readme/i.test(f))) {
        return 'docs'
    }
    if (all((f) => /\.(css|scss|sass|less|styl)$/.test(f))) {
        return 'styling'
    }
    if (signals.flags || signals.events || signals.pages || signals.dashboards) {
        return 'feature'
    }
    return 'mixed'
}

function SectionToggle({
    open,
    onToggle,
    title,
    count,
    accent,
}: {
    open: boolean
    onToggle: () => void
    title: string
    count: number | string
    accent?: 'danger' | 'warning' | 'default'
}): JSX.Element {
    const countClass = accent === 'danger' ? 'text-danger' : accent === 'warning' ? 'text-warning' : 'text-secondary'
    return (
        <button
            type="button"
            onClick={onToggle}
            className="w-full px-4 py-2.5 flex items-center gap-x-2 text-left hover:bg-fill-highlight-50 transition-colors"
        >
            {open ? (
                <IconChevronDown className="size-3.5 text-muted shrink-0" />
            ) : (
                <IconChevronRight className="size-3.5 text-muted shrink-0" />
            )}
            <span className="text-sm font-medium flex-1 truncate">{title}</span>
            <span className={`text-xs tabular-nums ${countClass}`}>{count}</span>
        </button>
    )
}

export function GitHogImpactWidget({ owner, name, number }: GitHogPRImpactLogicProps): JSX.Element {
    const logic = gitHogPRImpactLogic({ owner, name, number })
    const { lookbackDays, report, reportLoading, reportError } = useValues(logic)
    const { setLookbackDays, computeImpact } = useActions(logic)

    const hasFlags = (report?.flag_references?.length ?? 0) > 0
    const hasEvents = (report?.event_references?.length ?? 0) > 0
    const hasDashboards = (report?.dashboard_references?.length ?? 0) > 0
    const hasIssues = (report?.issue_references?.length ?? 0) > 0
    const hasRelated = (report?.related_signals?.length ?? 0) > 0
    const hasWebPaths = (report?.web_paths?.length ?? 0) > 0
    const hasLLM = !!report?.llm_analysis
    const hasAnySignal = hasFlags || hasEvents || hasDashboards || hasIssues || hasRelated || hasWebPaths || hasLLM
    const isInitialLoading = reportLoading && !report
    const isReloading = reportLoading && !!report
    const isErrored = !reportLoading && !!reportError && !report
    const isIdle = !reportLoading && !report && !reportError
    const hasResult = !reportLoading && !!report

    // Map of "kind:key" → reason. Used to mark items in structured sections
    // that the LLM flagged as top picks — surfaces the AI's prioritization
    // without producing a parallel wall-of-text section.
    const starredItems = useMemo(() => {
        const map = new Map<string, string>()
        report?.llm_analysis?.top_picks?.forEach((p) => {
            if (p.key) {
                map.set(`${p.kind}:${p.key}`, p.reason)
            }
        })
        return map
    }, [report?.llm_analysis?.top_picks])
    const starOf = (kind: string, key: string): string | undefined => starredItems.get(`${kind}:${key}`)

    // Single set of expanded section keys; default collapsed. Reviewers expand
    // only the sections they actually want to dig into.
    const [expanded, setExpanded] = useState<Set<string>>(new Set())
    const toggle = useCallback((key: string) => {
        setExpanded((prev) => {
            const next = new Set(prev)
            if (next.has(key)) {
                next.delete(key)
            } else {
                next.add(key)
            }
            return next
        })
    }, [])
    const isOpen = (key: string): boolean => expanded.has(key)

    const activeIssueCount = report?.issue_references?.filter(
        (i: IssueReference) => i.status !== 'resolved' && i.status !== 'archived' && i.status !== 'suppressed'
    ).length

    return (
        <div className="flex flex-col divide-y divide-border">
            <div className="px-4 py-3 flex items-center justify-between gap-x-3 flex-wrap">
                <span className="font-semibold text-sm flex items-center gap-x-2">
                    <IconPeople className="size-4 text-secondary" />
                    Impact
                </span>
                <div className="flex items-center gap-x-2">
                    <LemonSelect
                        size="small"
                        value={lookbackDays}
                        onChange={(v) => v && setLookbackDays(v)}
                        options={[
                            { value: 7, label: 'Last 7 days' },
                            { value: 30, label: 'Last 30 days' },
                            { value: 90, label: 'Last 90 days' },
                        ]}
                    />
                    <LemonButton
                        type="secondary"
                        size="small"
                        icon={<IconRefresh />}
                        onClick={() => computeImpact({ refresh: true })}
                        loading={reportLoading}
                        tooltip="Bypass cache and recompute from scratch"
                    />
                </div>
            </div>

            {isInitialLoading && (
                <div className="px-4 py-8 flex flex-col items-center justify-center gap-y-1 text-secondary text-sm">
                    <div className="flex items-center gap-x-2">
                        <Spinner />
                        Measuring impact…
                    </div>
                    <span className="text-xs text-muted">This can take up to ~30 seconds for large PRs.</span>
                </div>
            )}

            {isIdle && (
                <div className="px-4 py-6 text-sm text-secondary text-center">
                    Click <IconRefresh className="size-3.5 inline -mt-0.5" /> to measure impact for this PR.
                </div>
            )}

            {isErrored && (
                <div className="px-4 py-6 flex flex-col items-center gap-y-2 text-sm text-danger text-center">
                    <span>Failed to measure impact.</span>
                    <span className="text-xs text-secondary font-mono break-all max-w-prose">{reportError}</span>
                </div>
            )}

            {hasResult && !hasAnySignal && (
                <div className="px-4 py-8 text-sm text-secondary text-center">
                    No PostHog flag or event references found in this PR
                    {isReloading ? ' (reloading…)' : '.'}
                </div>
            )}

            {hasResult && hasAnySignal && (
                <>
                    {/* HERO — shape-aware. CI / infra / migration / docs are not
                        measured in users, so we surface a categorical statement
                        instead of a misleading "0 users". Only feature/mixed
                        changes get the numeric stat treatment. */}
                    {(() => {
                        const shape = detectImpactShape(report.changed_files, {
                            flags: hasFlags,
                            events: hasEvents,
                            pages: hasWebPaths,
                            dashboards: hasDashboards,
                            issues: hasIssues,
                        })
                        const def = IMPACT_SHAPE_DEFS[shape]
                        const affected = report.llm_analysis?.affected
                        const parsedReach = parseHeadlineNumber(affected?.headline)
                        const hasMeaningfulReach =
                            def.reachApplies && affected != null && parsedReach != null && parsedReach >= 1
                        const audience = report.llm_analysis?.audience ?? []
                        const confStyles = affected
                            ? (CONFIDENCE_STYLES[affected.confidence] ?? CONFIDENCE_STYLES.low)
                            : CONFIDENCE_STYLES.low

                        // Signal-count strip — quiet line under the hero so reviewers
                        // can see what's behind the framing without scrolling.
                        const signalChips: string[] = []
                        if (hasFlags) {
                            signalChips.push(
                                `${report.per_flag_reach.length} flag${report.per_flag_reach.length === 1 ? '' : 's'}`
                            )
                        }
                        if (hasEvents) {
                            signalChips.push(
                                `${report.per_event_reach.length} event${report.per_event_reach.length === 1 ? '' : 's'}`
                            )
                        }
                        if (hasWebPaths) {
                            signalChips.push(
                                `${report.web_paths.length} page${report.web_paths.length === 1 ? '' : 's'}`
                            )
                        }
                        if (hasIssues) {
                            signalChips.push(
                                `${report.issue_references.length} error${report.issue_references.length === 1 ? '' : 's'}`
                            )
                        }
                        if (hasDashboards) {
                            signalChips.push(
                                `${report.dashboard_references.length} dashboard${report.dashboard_references.length === 1 ? '' : 's'}`
                            )
                        }
                        signalChips.push(
                            `${report.changed_files.length} file${report.changed_files.length === 1 ? '' : 's'} touched`
                        )

                        return (
                            <div className={`px-5 py-4 ${def.tint}`}>
                                {hasMeaningfulReach ? (
                                    <>
                                        <div className="flex items-baseline gap-x-2 flex-wrap">
                                            <span className="text-3xl font-bold tabular-nums tracking-tight leading-none">
                                                {affected!.headline}
                                            </span>
                                            <span className="text-sm text-secondary">{affected!.unit}</span>
                                            <span className="text-muted text-xs">·</span>
                                            <span
                                                className={`inline-flex items-center gap-x-1.5 text-xs font-medium ${confStyles.text}`}
                                            >
                                                <span className={`size-1.5 rounded-full ${confStyles.dot}`} />
                                                {affected!.confidence} confidence
                                            </span>
                                        </div>
                                        {audience.length > 0 && (
                                            <div className="mt-1.5 text-xs text-secondary">
                                                {audience.slice(0, 3).join(' · ')}
                                            </div>
                                        )}
                                    </>
                                ) : (
                                    <>
                                        <div className="text-base font-semibold leading-snug">
                                            {def.label || affected?.headline || 'Mixed change'}
                                        </div>
                                        <p className="mt-1.5 text-sm text-secondary leading-relaxed my-0">
                                            {def.description ||
                                                affected?.rationale ||
                                                'Could not determine a single user-reach figure for this change.'}
                                        </p>
                                    </>
                                )}
                                <div className="mt-3 pt-3 border-t border-border-light text-xs text-muted flex flex-wrap gap-x-3 gap-y-0.5">
                                    {signalChips.map((chip, idx) => (
                                        <span key={idx}>{chip}</span>
                                    ))}
                                </div>
                            </div>
                        )
                    })()}

                    {/* Description — available, not prominent. Click to expand. */}
                    {hasLLM && report.llm_analysis && (
                        <div className="flex flex-col">
                            <SectionToggle
                                open={isOpen('why')}
                                onToggle={() => toggle('why')}
                                title="Why this estimate?"
                                count=""
                            />
                            {isOpen('why') && (
                                <div className="px-4 pb-4 flex flex-col gap-y-2">
                                    {report.llm_analysis.affected?.rationale && (
                                        <p className="text-sm text-primary leading-relaxed my-0">
                                            {report.llm_analysis.affected.rationale}
                                        </p>
                                    )}
                                    {report.llm_analysis.headline && (
                                        <p className="text-sm font-medium leading-snug my-0">
                                            {report.llm_analysis.headline}
                                        </p>
                                    )}
                                    {report.llm_analysis.summary && (
                                        <p className="text-sm text-secondary leading-relaxed my-0">
                                            {report.llm_analysis.summary}
                                        </p>
                                    )}
                                    {report.llm_analysis.caveats.length > 0 && (
                                        <div className="flex flex-col gap-y-0.5 pt-1">
                                            {report.llm_analysis.caveats.map((c: string, idx: number) => (
                                                <span key={idx} className="text-xs text-muted">
                                                    · {c}
                                                </span>
                                            ))}
                                        </div>
                                    )}
                                </div>
                            )}
                        </div>
                    )}

                    {/* Errors */}
                    {hasIssues && (
                        <div className="flex flex-col">
                            <SectionToggle
                                open={isOpen('errors')}
                                onToggle={() => toggle('errors')}
                                title="Errors"
                                count={
                                    activeIssueCount != null && activeIssueCount > 0
                                        ? `${report.issue_references.length} · ${activeIssueCount} active`
                                        : report.issue_references.length
                                }
                                accent={activeIssueCount && activeIssueCount > 0 ? 'danger' : 'default'}
                            />
                            {isOpen('errors') &&
                                report.issue_references.map((issue: IssueReference) => (
                                    <div
                                        key={issue.id}
                                        className="px-4 py-2.5 flex flex-col gap-y-1 border-t border-border"
                                    >
                                        <div className="flex items-center gap-x-2 flex-wrap">
                                            <LemonTag
                                                type={
                                                    issue.status === 'resolved'
                                                        ? 'success'
                                                        : issue.status === 'pending_release'
                                                          ? 'warning'
                                                          : issue.status === 'archived' || issue.status === 'suppressed'
                                                            ? 'muted'
                                                            : 'danger'
                                                }
                                                size="small"
                                            >
                                                {issue.status}
                                            </LemonTag>
                                            <span className="text-sm font-medium flex-1 truncate">{issue.name}</span>
                                            <Star reason={starOf('issue', issue.name)} />
                                            <span className="text-xs text-secondary tabular-nums">
                                                {issue.occurrences.toLocaleString()}
                                            </span>
                                            <span className="text-xs text-muted tabular-nums">
                                                {issue.users_affected.toLocaleString()}u
                                            </span>
                                        </div>
                                        {issue.sample_message && (
                                            <span className="text-xs text-muted font-mono truncate">
                                                {issue.sample_message}
                                            </span>
                                        )}
                                    </div>
                                ))}
                        </div>
                    )}

                    {/* Insights & dashboards */}
                    {hasDashboards && (
                        <div className="flex flex-col">
                            <SectionToggle
                                open={isOpen('insights')}
                                onToggle={() => toggle('insights')}
                                title="Insights & dashboards"
                                count={report.dashboard_references.length}
                            />
                            {isOpen('insights') &&
                                report.dashboard_references.map((ref: DashboardReference) => (
                                    <div
                                        key={`${ref.kind}-${ref.id}`}
                                        className="px-4 py-2.5 flex items-center gap-x-3 border-t border-border"
                                    >
                                        <LemonTag type={ref.kind === 'dashboard' ? 'primary' : 'muted'} size="small">
                                            {ref.kind === 'dashboard' ? 'Dashboard' : 'Insight'}
                                        </LemonTag>
                                        <span className="text-sm flex-1 truncate">{ref.name}</span>
                                        <Star reason={starOf('dashboard', ref.name)} />
                                    </div>
                                ))}
                        </div>
                    )}

                    {/* Pages */}
                    {hasWebPaths && (
                        <div className="flex flex-col">
                            <SectionToggle
                                open={isOpen('pages')}
                                onToggle={() => toggle('pages')}
                                title="Pages"
                                count={report.web_paths.length}
                            />
                            {isOpen('pages') &&
                                report.web_paths.map((page: WebPathReach) => (
                                    <div
                                        key={page.path}
                                        className="px-4 py-2.5 flex items-center gap-x-3 border-t border-border"
                                    >
                                        <span className="text-sm flex-1 font-mono truncate">{page.path}</span>
                                        <Star reason={starOf('page', page.path)} />
                                        {page.has_data ? (
                                            <span className="text-xs text-secondary tabular-nums">
                                                {page.unique_visitors.toLocaleString()}u ·{' '}
                                                {page.pageviews.toLocaleString()}pv
                                            </span>
                                        ) : (
                                            <LemonTag type="warning" size="small">
                                                no data
                                            </LemonTag>
                                        )}
                                    </div>
                                ))}
                        </div>
                    )}

                    {/* Flags */}
                    {hasFlags && (
                        <div className="flex flex-col">
                            <SectionToggle
                                open={isOpen('flags')}
                                onToggle={() => toggle('flags')}
                                title="Flags"
                                count={report.per_flag_reach.length}
                            />
                            {isOpen('flags') && (
                                <>
                                    {report.per_flag_reach.map((flag: FlagReach) => (
                                        <div
                                            key={flag.key}
                                            className="px-4 py-2.5 flex items-center gap-x-3 border-t border-border"
                                        >
                                            <span className="text-sm flex-1 font-mono truncate">{flag.key}</span>
                                            <Star reason={starOf('flag', flag.key)} />
                                            {flag.has_data ? (
                                                <span className="text-xs text-secondary tabular-nums">
                                                    {flag.users_affected.toLocaleString()}
                                                    {flag.is_server_side ? 'i' : 'u'} ·{' '}
                                                    {flag.call_count.toLocaleString()}e
                                                </span>
                                            ) : (
                                                <LemonTag type="warning" size="small">
                                                    no data
                                                </LemonTag>
                                            )}
                                        </div>
                                    ))}
                                    {report.flag_references.some((r: FlagReference) => r.key.startsWith('const:')) && (
                                        <div className="px-4 py-2 border-t border-border flex flex-wrap gap-1.5 bg-fill-highlight-50">
                                            <span className="text-xs text-muted">unresolved:</span>
                                            {report.flag_references
                                                .filter((r: FlagReference) => r.key.startsWith('const:'))
                                                .map((r: FlagReference) => (
                                                    <LemonTag key={r.key} type="muted" size="small">
                                                        {r.key}
                                                    </LemonTag>
                                                ))}
                                        </div>
                                    )}
                                </>
                            )}
                        </div>
                    )}

                    {/* Events */}
                    {hasEvents && (
                        <div className="flex flex-col">
                            <SectionToggle
                                open={isOpen('events')}
                                onToggle={() => toggle('events')}
                                title="Events"
                                count={report.per_event_reach.length}
                            />
                            {isOpen('events') &&
                                report.per_event_reach.map((evt: EventReach) => (
                                    <div
                                        key={evt.name}
                                        className="px-4 py-2.5 flex items-center gap-x-3 border-t border-border"
                                    >
                                        <span className="text-sm flex-1 font-mono truncate">{evt.name}</span>
                                        <Star reason={starOf('event', evt.name)} />
                                        {evt.has_data ? (
                                            <span className="text-xs text-secondary tabular-nums">
                                                {evt.users_affected.toLocaleString()}
                                                {evt.is_server_side ? 'i' : 'u'} · {evt.call_count.toLocaleString()}f
                                            </span>
                                        ) : (
                                            <LemonTag type="warning" size="small">
                                                no data
                                            </LemonTag>
                                        )}
                                    </div>
                                ))}
                        </div>
                    )}

                    {/* Related — quieter, filename-token heuristic */}
                    {hasRelated && (
                        <div className="flex flex-col">
                            <SectionToggle
                                open={isOpen('related')}
                                onToggle={() => toggle('related')}
                                title="Related signals"
                                count={report.related_signals.length}
                            />
                            {isOpen('related') && (
                                <>
                                    {report.related_signals.map((sig: RelatedSignal) => (
                                        <div
                                            key={`${sig.kind}-${sig.key}`}
                                            className="px-4 py-2.5 flex items-center gap-x-3 border-t border-border"
                                        >
                                            <LemonTag type="muted" size="small">
                                                {sig.kind}
                                            </LemonTag>
                                            <span className="text-sm flex-1 font-mono truncate">{sig.key}</span>
                                            <Star reason={starOf(sig.kind, sig.key)} />
                                            {sig.has_data ? (
                                                <span className="text-xs text-secondary tabular-nums">
                                                    {sig.users_affected.toLocaleString()}
                                                    {sig.is_server_side ? 'i' : 'u'}
                                                </span>
                                            ) : (
                                                <LemonTag type="warning" size="small">
                                                    no data
                                                </LemonTag>
                                            )}
                                        </div>
                                    ))}
                                </>
                            )}
                        </div>
                    )}

                    {report.notes.length > 0 && (
                        <div className="px-4 py-2 flex flex-col gap-y-0.5">
                            {report.notes.map((note: string, idx: number) => (
                                <span key={idx} className="text-xs text-muted">
                                    · {note}
                                </span>
                            ))}
                        </div>
                    )}
                </>
            )}
        </div>
    )
}
