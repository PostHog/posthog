import { useValues } from 'kea'

import { LemonTable, LemonTag } from '@posthog/lemon-ui'
import type { LemonTableColumns } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { humanFriendlyNumber } from 'lib/utils/numbers'

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
    const { patterns, patternsResponseLoading } = useValues(logsPatternsLogic({ id }))

    const columns: LemonTableColumns<_LogPatternApi> = [
        {
            title: 'Pattern',
            dataIndex: 'pattern',
            render: (_, row) => renderPatternTemplate(row.pattern),
        },
        {
            title: 'Count',
            dataIndex: 'count',
            render: (_, row) => humanFriendlyNumber(row.count),
            sorter: (a, b) => a.count - b.count,
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
            dataIndex: 'error_count',
            render: (_, row) =>
                row.error_count > 0 ? (
                    <LemonTag type="danger">{humanFriendlyNumber(row.error_count)}</LemonTag>
                ) : (
                    <span className="text-muted">0</span>
                ),
            sorter: (a, b) => a.error_count - b.error_count,
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
            <LemonTable
                columns={columns}
                dataSource={patterns}
                loading={patternsResponseLoading}
                defaultSorting={{ columnKey: 'count', order: -1 }}
                emptyState="No patterns found for the current filters"
                rowKey="pattern"
                size="small"
            />
        </div>
    )
}
