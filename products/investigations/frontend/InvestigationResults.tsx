import { LemonBanner, LemonTable, LemonTag } from '@posthog/lemon-ui'

import { LemonCard } from 'lib/lemon-ui/LemonCard'

import { InvestigationResult, compareInvestigationResults } from './investigationDocument'

export function InvestigationResults({
    result,
    baseline,
}: {
    result: InvestigationResult
    baseline?: InvestigationResult
}): JSX.Element {
    const comparison = compareInvestigationResults(result, baseline)
    return (
        <LemonCard hoverEffect={false} className="p-4 min-w-0">
            <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
                <h4 className="m-0 break-words">{result.title}</h4>
                <LemonTag
                    type={
                        comparison.kind === 'error' ? 'danger' : comparison.kind === 'changed' ? 'warning' : 'default'
                    }
                >
                    {comparison.label}
                </LemonTag>
            </div>
            {result.error ? (
                <LemonBanner type="error">{result.error}</LemonBanner>
            ) : (
                <>
                    {result.rows.length === 1 && result.columns.length === 1 ? (
                        <div className="flex flex-wrap items-baseline gap-3 mb-2">
                            <span className="text-3xl font-semibold tabular-nums">
                                {String(result.rows[0][0] ?? 'No value')}
                            </span>
                            {comparison.delta !== null && (
                                <span className="text-secondary tabular-nums">{`${comparison.delta > 0 ? '+' : ''}${Number(comparison.delta.toPrecision(8))} from baseline`}</span>
                            )}
                            <span className="text-secondary">{result.columns[0]}</span>
                        </div>
                    ) : (
                        <LemonTable
                            dataSource={result.rows}
                            size="small"
                            pagination={{ pageSize: 5 }}
                            emptyState="The query returned no rows."
                            columns={result.columns.map((column, index) => ({
                                title: column,
                                key: `${column}-${index}`,
                                render: (_, row) => <span className="break-all">{String(row[index] ?? 'NULL')}</span>,
                            }))}
                        />
                    )}
                    {result.truncated && (
                        <p className="text-warning text-xs mt-2 mb-0">
                            This is a partial snapshot. A complete comparison is unavailable.
                        </p>
                    )}
                </>
            )}
            <details className="mt-3 text-sm">
                <summary className="cursor-pointer text-secondary">Query used for this result</summary>
                <pre className="mt-2 whitespace-pre-wrap break-all text-xs">{result.sql}</pre>
            </details>
        </LemonCard>
    )
}
