import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonTable, LemonTag, Tooltip } from '@posthog/lemon-ui'
import type { LemonTableColumns } from '@posthog/lemon-ui'

import { Sparkline } from 'lib/components/Sparkline'
import { TZLabel } from 'lib/components/TZLabel'
import { humanFriendlyLargeNumber, humanFriendlyNumber } from 'lib/utils/numbers'

import type { LogMessage } from '~/queries/schema/schema-general'

import { LogTag } from 'products/logs/frontend/components/LogTag'
import type { _LogPatternApi, _LogPatternExampleApi } from 'products/logs/frontend/generated/api.schemas'

import { logsPatternsLogic } from './logsPatternsLogic'

// Most-severe-first, so ties in sample counts resolve to the stronger signal.
const SEVERITY_RANK: LogMessage['severity_text'][] = ['fatal', 'error', 'warn', 'info', 'debug', 'trace']

// Non-canonical spellings services emit (Python's default "warning", syslog's "err"/"crit", …),
// folded onto the OTel-canonical level so their counts aren't silently dropped from the Level column.
const SEVERITY_ALIASES: Record<string, LogMessage['severity_text']> = {
    warning: 'warn',
    err: 'error',
    critical: 'fatal',
    crit: 'fatal',
    alert: 'fatal',
    emerg: 'fatal',
    emergency: 'fatal',
    panic: 'fatal',
    notice: 'info',
    verbose: 'trace',
}

function canonicalSeverity(raw: string): LogMessage['severity_text'] | null {
    if ((SEVERITY_RANK as string[]).includes(raw)) {
        return raw as LogMessage['severity_text']
    }
    return SEVERITY_ALIASES[raw] ?? null
}

// Dominant severity by sample count. Non-canonical spellings are folded onto their canonical
// level; genuinely unknown levels keep their raw key so they still surface (rather than showing
// "-"). Ties break toward the more severe level.
function dominantSeverity(severityCounts: Record<string, number>): string | null {
    const folded: Record<string, number> = {}
    for (const [raw, count] of Object.entries(severityCounts)) {
        if (count <= 0) {
            continue
        }
        const key = canonicalSeverity(raw) ?? raw
        folded[key] = (folded[key] ?? 0) + count
    }
    let best: string | null = null
    let bestCount = 0
    let bestRank = SEVERITY_RANK.length
    for (const [key, count] of Object.entries(folded)) {
        const canonical = canonicalSeverity(key)
        const rank = canonical ? SEVERITY_RANK.indexOf(canonical) : SEVERITY_RANK.length
        if (count > bestCount || (count === bestCount && rank < bestRank)) {
            best = key
            bestCount = count
            bestRank = rank
        }
    }
    return best
}

function PatternExampleRow({ example }: { example: _LogPatternExampleApi }): JSX.Element {
    return (
        <div className="flex items-baseline gap-2 py-0.5">
            <span className="shrink-0">
                <TZLabel time={example.timestamp} className="text-muted text-xs whitespace-nowrap" />
            </span>
            <span className="shrink-0">
                <LogTag level={example.severity_text as LogMessage['severity_text']} />
            </span>
            <span className="text-muted text-xs shrink-0">{example.service_name}</span>
            <span className="font-mono text-xs break-all">{example.body}</span>
        </div>
    )
}

function PatternExpandedRow({
    row,
    onViewMatchingLogs,
}: {
    row: _LogPatternApi
    onViewMatchingLogs: (row: _LogPatternApi) => void
}): JSX.Element {
    return (
        <div className="px-2 py-2 flex flex-col gap-2" data-attr="logs-pattern-expanded">
            <div className="flex items-center justify-between gap-2">
                <div>{renderPatternTemplate(row.pattern)}</div>
                {(row.match_regex || row.match_literal) && (
                    <LemonButton
                        type="secondary"
                        size="xsmall"
                        onClick={() => onViewMatchingLogs(row)}
                        tooltip={
                            row.match_regex
                                ? 'Open the Logs view filtered to lines matching this pattern'
                                : 'Open the Logs view filtered to lines containing this pattern’s literal text (pattern match unavailable)'
                        }
                        data-attr="logs-pattern-view-matching"
                    >
                        View matching logs
                    </LemonButton>
                )}
            </div>
            <div className="text-muted text-xs">
                First seen <TZLabel time={row.first_seen} /> · last seen <TZLabel time={row.last_seen} />
                {row.services.length ? <> · {row.services.join(', ')}</> : null}
            </div>
            {row.examples.length ? (
                <>
                    <div className="border rounded bg-bg-light p-2 flex flex-col divide-y">
                        {row.examples.map((example, i) => (
                            <PatternExampleRow key={i} example={example} />
                        ))}
                    </div>
                    <div className="text-muted text-xs">
                        Examples are sampled lines, shown as mined (whitespace-collapsed and truncated).
                    </div>
                </>
            ) : (
                <span className="text-muted text-xs">No examples were retained for this pattern.</span>
            )}
        </div>
    )
}

// Highlight Drain's `<*>` wildcard and the masking placeholders (`<ip>`, `<num>`, `<uuid>`,
// `<hex>`, …) the runner emits — see _MASKING_INSTRUCTIONS in
// products/logs/backend/log_patterns.py for the authoritative token vocabulary.
const PATTERN_TOKEN = String.raw`<\*>|<[a-z][a-z0-9]*>`
const PATTERN_TOKEN_SPLIT = new RegExp(`(${PATTERN_TOKEN})`, 'g')
const PATTERN_TOKEN_MATCH = new RegExp(`^(${PATTERN_TOKEN})$`)

function renderPatternTemplate(pattern: string): JSX.Element {
    return (
        <span className="font-mono text-xs break-all">
            {pattern.split(PATTERN_TOKEN_SPLIT).map((part, i) => (
                <span key={i} className={PATTERN_TOKEN_MATCH.test(part) ? 'text-accent font-semibold' : undefined}>
                    {part}
                </span>
            ))}
        </span>
    )
}

export function LogsPatterns({ id }: { id: string }): JSX.Element {
    const { patterns, patternsResponse, patternsResponseLoading, patternsError, sparklineLabels } = useValues(
        logsPatternsLogic({ id })
    )
    const { viewMatchingLogs } = useActions(logsPatternsLogic({ id }))
    const { sampled, scanned_count, total_count, sample_coverage_pct } = patternsResponse

    // Estimated counts are rounded (not exact-comma-formatted) and prefixed with "~" so a
    // reader never mistakes an extrapolation for a measurement; the tooltip carries the raw
    // sample fact the estimate was derived from.
    const renderEstimate = (estimated: number, sampleCount: number): JSX.Element | string => {
        if (!sampled) {
            return humanFriendlyNumber(estimated)
        }
        return (
            <Tooltip
                title={`${humanFriendlyNumber(sampleCount)} of the ${humanFriendlyNumber(
                    scanned_count
                )} sampled lines — extrapolated to the full window`}
            >
                <span>~{humanFriendlyLargeNumber(estimated)}</span>
            </Tooltip>
        )
    }

    const columns: LemonTableColumns<_LogPatternApi> = [
        {
            title: 'Level',
            key: 'severity',
            width: 0,
            render: (_, row) => {
                const severity = dominantSeverity(row.severity_counts)
                if (!severity) {
                    return <span className="text-muted">-</span>
                }
                const canonical = canonicalSeverity(severity)
                return canonical ? <LogTag level={canonical} /> : <LemonTag>{severity}</LemonTag>
            },
        },
        {
            title: 'Pattern',
            dataIndex: 'pattern',
            render: (_, row) => renderPatternTemplate(row.pattern),
        },
        {
            title: 'Trend',
            key: 'sparkline',
            render: (_, row) =>
                row.sparkline.length ? (
                    <div className="w-24 h-6">
                        <Sparkline
                            data={row.sparkline}
                            labels={sparklineLabels}
                            className="w-full h-full"
                            maximumIndicator={false}
                        />
                    </div>
                ) : (
                    <span className="text-muted">-</span>
                ),
        },
        {
            title: 'Count',
            dataIndex: 'estimated_count',
            render: (_, row) => renderEstimate(row.estimated_count, row.count),
            sorter: (a, b) => a.estimated_count - b.estimated_count,
            align: 'right',
        },
        {
            title: 'Share',
            dataIndex: 'volume_share_pct',
            render: (_, row) => `${row.volume_share_pct.toFixed(1)}%`,
            sorter: (a, b) => a.volume_share_pct - b.volume_share_pct,
            align: 'right',
        },
        {
            title: 'Errors',
            dataIndex: 'estimated_error_count',
            render: (_, row) =>
                row.estimated_error_count > 0 ? (
                    <LemonTag type="danger">{renderEstimate(row.estimated_error_count, row.error_count)}</LemonTag>
                ) : (
                    <span className="text-muted">0</span>
                ),
            sorter: (a, b) => a.estimated_error_count - b.estimated_error_count,
            align: 'right',
        },
        {
            title: 'Services',
            key: 'services',
            render: (_, row) =>
                row.services.length ? (
                    <span className="text-muted">{row.services.join(', ')}</span>
                ) : (
                    <span className="text-muted">-</span>
                ),
        },
        {
            title: 'Last seen',
            dataIndex: 'last_seen',
            render: (_, row) => <TZLabel time={row.last_seen} />,
            sorter: (a, b) => (a.last_seen < b.last_seen ? -1 : a.last_seen > b.last_seen ? 1 : 0),
        },
    ]

    return (
        <div className="flex-1 min-h-0 overflow-auto" data-attr="logs-patterns">
            {sampled && !patternsResponseLoading && !patternsError && (
                <LemonBanner type="info" className="m-2" data-attr="logs-patterns-sample-info">
                    Patterns are mined from a representative sample of {humanFriendlyNumber(scanned_count)} lines out of
                    the {humanFriendlyLargeNumber(total_count)} matching your filters
                    {sample_coverage_pct < 100
                        ? `, drawn from evenly-spaced time slices covering ${sample_coverage_pct.toFixed(
                              1
                          )}% of the window`
                        : ''}
                    . Counts are estimates for the full window — hover a count for the underlying sample figure. Narrow
                    your filters (a service, a severity, or a shorter time range) to sharpen the sample.
                </LemonBanner>
            )}
            <LemonTable
                columns={columns}
                dataSource={patterns}
                loading={patternsResponseLoading}
                expandable={{
                    expandedRowRender: (row) => <PatternExpandedRow row={row} onViewMatchingLogs={viewMatchingLogs} />,
                }}
                defaultSorting={{ columnKey: 'estimated_count', order: -1 }}
                emptyState={
                    patternsError
                        ? 'Pattern analysis failed — try a shorter time range or narrower filters'
                        : 'No patterns found for the current filters'
                }
                rowKey="pattern"
                size="small"
            />
        </div>
    )
}
