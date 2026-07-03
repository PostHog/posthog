import { useValues } from 'kea'

import { LemonBanner, LemonTable, LemonTag, Tooltip } from '@posthog/lemon-ui'
import type { LemonTableColumns } from '@posthog/lemon-ui'

import { Sparkline } from 'lib/components/Sparkline'
import { TZLabel } from 'lib/components/TZLabel'
import { humanFriendlyLargeNumber, humanFriendlyNumber } from 'lib/utils/numbers'

import type { _LogPatternApi } from 'products/logs/frontend/generated/api.schemas'

import { logsPatternsLogic } from './logsPatternsLogic'

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
                    . Counts are estimates for the full window — hover a count for the underlying sample figure.
                </LemonBanner>
            )}
            <LemonTable
                columns={columns}
                dataSource={patterns}
                loading={patternsResponseLoading}
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
