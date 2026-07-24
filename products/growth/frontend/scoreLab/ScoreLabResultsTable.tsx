import { useValues } from 'kea'

import { LemonTable, LemonTableColumns, LemonTag, LemonTagType } from '@posthog/lemon-ui'

import { ScoreLabVerdictRow, scoreLabLogic } from './scoreLabLogic'

function verdictTagType(verdict: string): LemonTagType {
    switch (verdict) {
        case 'true':
            return 'success'
        case 'false':
            return 'danger'
        case 'error':
            return 'warning'
        default:
            return 'muted'
    }
}

const columns: LemonTableColumns<ScoreLabVerdictRow> = [
    { title: 'Company', key: 'company', dataIndex: 'company' },
    {
        title: 'Domain',
        key: 'domain',
        render: (_, row) => row.domain ?? <span className="text-secondary">–</span>,
    },
    {
        title: 'Verdict',
        key: 'verdict',
        render: (_, row) => <LemonTag type={verdictTagType(row.verdict.toLowerCase())}>{row.verdict}</LemonTag>,
    },
    { title: 'Confidence', key: 'confidence', dataIndex: 'confidence' },
    { title: 'Reasoning', key: 'reasoning', dataIndex: 'reasoning' },
]

export function ScoreLabResultsTable(): JSX.Element {
    const { runRows, runSummary, isRunning } = useValues(scoreLabLogic)

    return (
        <div className="space-y-2">
            <LemonTable
                dataSource={runRows}
                columns={columns}
                loading={isRunning && runRows.length === 0}
                rowKey={(row, index) => `${row.company}-${index}`}
                emptyState="Run the classifier to see verdicts here."
            />
            {runSummary && (
                <div className="text-secondary text-sm">
                    Classified {runSummary.classified} · Unknown {runSummary.unknown} · Errors {runSummary.errors}
                </div>
            )}
        </div>
    )
}
