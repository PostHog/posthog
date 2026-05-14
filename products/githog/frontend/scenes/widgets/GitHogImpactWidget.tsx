import { useActions, useValues } from 'kea'
import { useMemo, useState } from 'react'

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

function SectionHeading({ children }: { children: React.ReactNode }): JSX.Element {
    return (
        <div className="px-4 py-3">
            <span className="font-semibold text-xs uppercase tracking-wide text-secondary">{children}</span>
        </div>
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

    const [aiOpen, setAiOpen] = useState(false)

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

            <div className="px-4 py-2 text-xs text-secondary">
                Real users, sessions, and surfaces this PR touches — measured from PostHog activity, not configured
                rollouts.
            </div>

            {isInitialLoading && (
                <div className="px-4 py-6 flex flex-col items-center justify-center gap-y-1 text-secondary text-sm">
                    <div className="flex items-center gap-x-2">
                        <Spinner />
                        Measuring impact and asking the model…
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
                <div className="px-4 py-6 flex flex-col gap-y-2 text-sm">
                    <span className="text-secondary text-center">
                        No PostHog flag or event references found in this PR
                        {isReloading ? ' (reloading…)' : '.'}
                    </span>
                    <span className="text-xs text-muted text-center">
                        Scanned {report.known_flag_count.toLocaleString()} flag keys and{' '}
                        {report.known_event_count.toLocaleString()} recent event names against{' '}
                        {report.changed_files.length} touched file
                        {report.changed_files.length === 1 ? '' : 's'}.
                    </span>
                </div>
            )}

            {hasResult && hasAnySignal && (
                <>
                    {/* Loud metric — the answer to "how many and who" */}
                    {hasLLM && report.llm_analysis?.affected && (
                        <div className="px-4 py-5 flex flex-col gap-y-2 bg-fill-highlight-50">
                            <div className="flex items-baseline gap-x-3 flex-wrap">
                                <span className="text-3xl font-bold leading-none tabular-nums">
                                    {report.llm_analysis.affected.headline}
                                </span>
                                {(() => {
                                    const a = report.llm_analysis.affected
                                    const range =
                                        a.lower != null && a.upper != null && a.lower !== a.upper
                                            ? `${a.lower.toLocaleString()}–${a.upper.toLocaleString()}`
                                            : a.lower != null
                                              ? a.lower.toLocaleString()
                                              : a.upper != null
                                                ? a.upper.toLocaleString()
                                                : null
                                    const share =
                                        a.share_lower != null && a.share_upper != null
                                            ? a.share_lower === a.share_upper
                                                ? `${Math.round(a.share_upper * 100)}% of active`
                                                : `${Math.round(a.share_lower * 100)}–${Math.round(a.share_upper * 100)}% of active`
                                            : null
                                    const parts: string[] = []
                                    if (range) {
                                        parts.push(`${range} ${a.unit}`)
                                    }
                                    if (share) {
                                        parts.push(share)
                                    }
                                    if (parts.length === 0) {
                                        return null
                                    }
                                    return <span className="text-sm text-secondary">{parts.join(' · ')}</span>
                                })()}
                                <LemonTag
                                    type={
                                        report.llm_analysis.affected.confidence === 'high'
                                            ? 'success'
                                            : report.llm_analysis.affected.confidence === 'medium'
                                              ? 'warning'
                                              : 'muted'
                                    }
                                    size="small"
                                >
                                    {report.llm_analysis.affected.confidence} confidence
                                </LemonTag>
                            </div>
                            {report.llm_analysis.audience.length > 0 && (
                                <div className="flex items-center gap-x-1.5 flex-wrap">
                                    {report.llm_analysis.audience.map((who: string, idx: number) => (
                                        <LemonTag key={idx} type="option" size="small">
                                            {who}
                                        </LemonTag>
                                    ))}
                                </div>
                            )}
                            {report.llm_analysis.affected.rationale && (
                                <span className="text-xs text-muted leading-relaxed">
                                    {report.llm_analysis.affected.rationale}
                                </span>
                            )}
                        </div>
                    )}

                    {/* Errors — risk signal, surfaced first */}
                    {hasIssues && (
                        <>
                            <SectionHeading>
                                Errors related · {report.issue_references.length} ·{' '}
                                {
                                    report.issue_references.filter(
                                        (i: IssueReference) =>
                                            i.status !== 'resolved' &&
                                            i.status !== 'archived' &&
                                            i.status !== 'suppressed'
                                    ).length
                                }{' '}
                                active
                            </SectionHeading>
                            {report.issue_references.map((issue: IssueReference) => (
                                <div key={issue.id} className="px-4 py-3 flex flex-col gap-y-1.5">
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
                                            {issue.occurrences.toLocaleString()} events
                                        </span>
                                        <span className="text-xs text-muted tabular-nums">
                                            {issue.users_affected.toLocaleString()} users
                                        </span>
                                    </div>
                                    {issue.sample_message && (
                                        <span className="text-xs text-secondary font-mono truncate">
                                            {issue.sample_message}
                                        </span>
                                    )}
                                    <span
                                        className="text-xs text-muted truncate"
                                        title={issue.matched_terms.join(', ')}
                                    >
                                        via {issue.matched_terms.slice(0, 3).join(', ')}
                                        {issue.matched_terms.length > 3 ? ` +${issue.matched_terms.length - 3}` : ''}
                                    </span>
                                </div>
                            ))}
                        </>
                    )}

                    {/* Insights & dashboards this PR affects */}
                    {hasDashboards && (
                        <>
                            <SectionHeading>
                                Insights this affects · {report.dashboard_references.length}
                            </SectionHeading>
                            {report.dashboard_references.map((ref: DashboardReference) => (
                                <div key={`${ref.kind}-${ref.id}`} className="px-4 py-3 flex items-center gap-x-3">
                                    <LemonTag type={ref.kind === 'dashboard' ? 'primary' : 'muted'} size="small">
                                        {ref.kind === 'dashboard' ? 'Dashboard' : 'Insight'}
                                    </LemonTag>
                                    <span className="text-sm flex-1 truncate">{ref.name}</span>
                                    <Star reason={starOf('dashboard', ref.name)} />
                                    <span
                                        className="text-xs text-muted truncate max-w-[40%]"
                                        title={ref.matched_keys.join(', ')}
                                    >
                                        via {ref.matched_keys.slice(0, 2).join(', ')}
                                        {ref.matched_keys.length > 2 ? ` +${ref.matched_keys.length - 2}` : ''}
                                    </span>
                                </div>
                            ))}
                        </>
                    )}

                    {/* Pages this PR affects — web analytics */}
                    {hasWebPaths && (
                        <>
                            <SectionHeading>
                                Pages this affects · {report.web_paths.length} · last {report.lookback_days} days
                            </SectionHeading>
                            {report.web_paths.map((page: WebPathReach) => (
                                <div key={page.path} className="px-4 py-3 flex items-center gap-x-3">
                                    <LemonTag type="muted" size="small">
                                        page
                                    </LemonTag>
                                    <span className="text-sm flex-1 font-mono truncate">{page.path}</span>
                                    <Star reason={starOf('page', page.path)} />
                                    {page.matched_from === 'llm_tool' && (
                                        <LemonTag type="option" size="small">
                                            AI-inferred
                                        </LemonTag>
                                    )}
                                    {page.has_data ? (
                                        <>
                                            <span className="text-xs text-secondary tabular-nums">
                                                {page.unique_visitors.toLocaleString()} visitors
                                            </span>
                                            <span className="text-xs text-muted tabular-nums">
                                                {page.pageviews.toLocaleString()} pageviews
                                            </span>
                                        </>
                                    ) : (
                                        <LemonTag type="warning" size="small">
                                            No pageviews
                                        </LemonTag>
                                    )}
                                </div>
                            ))}
                        </>
                    )}

                    {/* Flag touch + reach */}
                    {hasFlags && (
                        <>
                            <SectionHeading>
                                Flags touched · {report.per_flag_reach.length} · last {report.lookback_days} days
                            </SectionHeading>
                            {hasFlags && (
                                <div className="px-4 py-3 flex items-center gap-x-6 text-xs text-secondary">
                                    <span>
                                        Intersection:{' '}
                                        <span className="font-semibold text-primary tabular-nums">
                                            {report.intersection_users.toLocaleString()}
                                        </span>{' '}
                                        users ·{' '}
                                        <span className="font-semibold text-primary tabular-nums">
                                            {report.intersection_sessions.toLocaleString()}
                                        </span>{' '}
                                        sessions
                                    </span>
                                </div>
                            )}
                            {report.per_flag_reach.map((flag: FlagReach) => (
                                <div key={flag.key} className="px-4 py-3 flex items-center gap-x-3">
                                    <span className="text-sm flex-1 font-mono truncate">{flag.key}</span>
                                    <Star reason={starOf('flag', flag.key)} />
                                    {flag.is_server_side && (
                                        <LemonTag type="muted" size="small">
                                            server-side
                                        </LemonTag>
                                    )}
                                    {flag.has_data ? (
                                        flag.is_server_side ? (
                                            <>
                                                <span className="text-xs text-secondary tabular-nums">
                                                    {flag.call_count.toLocaleString()} evaluations
                                                </span>
                                                <span className="text-xs text-muted tabular-nums">
                                                    {flag.users_affected.toLocaleString()} identities
                                                </span>
                                            </>
                                        ) : (
                                            <>
                                                <span className="text-xs text-secondary tabular-nums">
                                                    {flag.users_affected.toLocaleString()} users
                                                </span>
                                                <span className="text-xs text-muted tabular-nums">
                                                    {flag.call_count.toLocaleString()} evaluations
                                                </span>
                                            </>
                                        )
                                    ) : (
                                        <LemonTag type="warning" size="small">
                                            No data
                                        </LemonTag>
                                    )}
                                </div>
                            ))}
                        </>
                    )}

                    {/* Event instrumentation + reach */}
                    {hasEvents && (
                        <>
                            <SectionHeading>
                                Events instrumented · {report.per_event_reach.length} · last {report.lookback_days} days
                            </SectionHeading>
                            {report.per_event_reach.map((evt: EventReach) => (
                                <div key={evt.name} className="px-4 py-3 flex items-center gap-x-3">
                                    <span className="text-sm flex-1 font-mono truncate">{evt.name}</span>
                                    <Star reason={starOf('event', evt.name)} />
                                    {evt.is_server_side && (
                                        <LemonTag type="muted" size="small">
                                            server-side
                                        </LemonTag>
                                    )}
                                    {evt.has_data ? (
                                        evt.is_server_side ? (
                                            <>
                                                <span className="text-xs text-secondary tabular-nums">
                                                    {evt.call_count.toLocaleString()} fires
                                                </span>
                                                <span className="text-xs text-muted tabular-nums">
                                                    {evt.users_affected.toLocaleString()} identities
                                                </span>
                                            </>
                                        ) : (
                                            <>
                                                <span className="text-xs text-secondary tabular-nums">
                                                    {evt.users_affected.toLocaleString()} users
                                                </span>
                                                <span className="text-xs text-muted tabular-nums">
                                                    {evt.call_count.toLocaleString()} fires
                                                </span>
                                            </>
                                        )
                                    ) : (
                                        <LemonTag type="warning" size="small">
                                            No data
                                        </LemonTag>
                                    )}
                                </div>
                            ))}
                        </>
                    )}

                    {/* Related signals — filename-token suggestions */}
                    {hasRelated && (
                        <>
                            <SectionHeading>
                                Related signals · {report.related_signals.length} · by filename match
                            </SectionHeading>
                            <div className="px-4 -mt-1 pb-2">
                                <span className="text-xs text-muted">
                                    Not literally referenced in this PR, but they share names with files you touched.
                                </span>
                            </div>
                            {report.related_signals.map((sig: RelatedSignal) => (
                                <div key={`${sig.kind}-${sig.key}`} className="px-4 py-3 flex items-center gap-x-3">
                                    <LemonTag type="muted" size="small">
                                        {sig.kind}
                                    </LemonTag>
                                    <span className="text-sm flex-1 font-mono truncate">{sig.key}</span>
                                    <Star reason={starOf(sig.kind, sig.key)} />
                                    {sig.is_server_side && (
                                        <LemonTag type="muted" size="small">
                                            server-side
                                        </LemonTag>
                                    )}
                                    {sig.has_data ? (
                                        sig.is_server_side ? (
                                            <span className="text-xs text-secondary tabular-nums">
                                                {sig.call_count.toLocaleString()}{' '}
                                                {sig.kind === 'flag' ? 'evaluations' : 'fires'}
                                            </span>
                                        ) : (
                                            <span className="text-xs text-secondary tabular-nums">
                                                {sig.users_affected.toLocaleString()} users
                                            </span>
                                        )
                                    ) : (
                                        <LemonTag type="warning" size="small">
                                            No data
                                        </LemonTag>
                                    )}
                                    <span
                                        className="text-xs text-muted truncate max-w-[30%]"
                                        title={sig.matched_tokens.join(', ')}
                                    >
                                        via {sig.matched_tokens.slice(0, 2).join(', ')}
                                        {sig.matched_tokens.length > 2 ? ` +${sig.matched_tokens.length - 2}` : ''}
                                    </span>
                                </div>
                            ))}
                        </>
                    )}

                    {hasFlags && report.flag_references.some((r: FlagReference) => r.key.startsWith('const:')) && (
                        <div className="px-4 py-3">
                            <span className="font-semibold text-xs uppercase tracking-wide text-secondary">
                                Unresolved references
                            </span>
                            <div className="mt-2 flex flex-wrap gap-1.5">
                                {report.flag_references
                                    .filter((r: FlagReference) => r.key.startsWith('const:'))
                                    .map((r: FlagReference) => (
                                        <LemonTag key={r.key} type="muted" size="small">
                                            {r.key}
                                        </LemonTag>
                                    ))}
                            </div>
                        </div>
                    )}

                    {report.notes.length > 0 && (
                        <div className="px-4 py-3 flex flex-col gap-y-1.5">
                            {report.notes.map((note: string, idx: number) => (
                                <span key={idx} className="text-xs text-secondary">
                                    · {note}
                                </span>
                            ))}
                        </div>
                    )}

                    {/* AI synthesis — collapsed by default. Stars on items above
                        already encode the model's prioritization; this is for
                        reviewers who want the prose. */}
                    {hasLLM && report.llm_analysis && (
                        <div className="flex flex-col">
                            <button
                                type="button"
                                className="px-4 py-3 flex items-center gap-x-2 text-left hover:bg-fill-highlight-50 transition-colors"
                                onClick={() => setAiOpen((v) => !v)}
                            >
                                {aiOpen ? (
                                    <IconChevronDown className="size-3.5 text-secondary" />
                                ) : (
                                    <IconChevronRight className="size-3.5 text-secondary" />
                                )}
                                <span className="font-semibold text-xs uppercase tracking-wide text-secondary">
                                    AI synthesis
                                </span>
                                <span className="text-xs text-muted">
                                    · {report.llm_analysis.tool_calls_used} tool call
                                    {report.llm_analysis.tool_calls_used === 1 ? '' : 's'} used
                                </span>
                            </button>
                            {aiOpen && (
                                <div className="px-4 pb-4 pt-1 flex flex-col gap-y-3">
                                    <p className="text-sm font-medium leading-snug my-0">
                                        {report.llm_analysis.headline}
                                    </p>
                                    {report.llm_analysis.summary && (
                                        <p className="text-sm text-secondary leading-relaxed my-0">
                                            {report.llm_analysis.summary}
                                        </p>
                                    )}
                                    {report.llm_analysis.caveats.length > 0 && (
                                        <div className="flex flex-col gap-y-0.5">
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
                </>
            )}
        </div>
    )
}
