import { LemonTag, Tooltip } from '@posthog/lemon-ui'

import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'

import type {
    WorkflowProposalApi,
    WorkflowProposalMetricApi,
    WorkflowProposalOutcomeApi,
    WorkflowProposalVersionOutcomeApi,
} from '../generated/api.schemas'
import { MIN_EVIDENCE_SAMPLE, describeWindow, formatValue } from './suggestionEvidence'

/** The API names each rate; the table names the thing counted, because "Emails sent" heads it. */
const ROW_LABELS: Record<string, string> = {
    'email open rate': 'Opened',
    'click rate': 'Clicked',
    'complaint rate': 'Complaints',
    'bounce rate': 'Bounced',
    'unsubscribe rate': 'Unsubscribed',
}

type OutcomeRow =
    | { key: 'sent'; kind: 'sent'; label: string }
    | {
          key: string
          kind: 'rate'
          label: string
          before: WorkflowProposalMetricApi | null
          after: WorkflowProposalMetricApi | null
      }

function readings(side: WorkflowProposalVersionOutcomeApi | null): WorkflowProposalMetricApi[] {
    return side ? [side.target, side.click_through, ...side.guardrails] : []
}

function SentCell({ side }: { side: WorkflowProposalVersionOutcomeApi | null }): JSX.Element {
    if (!side) {
        return <span className="text-secondary">No data</span>
    }
    // Every send counts toward the guardrails; opens and clicks only count sends with tracking on.
    const all = side.guardrails[0]?.n ?? side.target.n
    const tracked = side.target.n
    return (
        <span className="flex items-center gap-1 flex-wrap">
            {all}
            {tracked !== all && (
                <Tooltip title="Sends with tracking off cannot record an open or a click, so those rates read against the tracked sends only.">
                    <span className="text-secondary">({tracked} tracked)</span>
                </Tooltip>
            )}
            {side.target.below_minimum_sample && (
                <Tooltip title={`Under ${MIN_EVIDENCE_SAMPLE} sends. Not enough for the rates to mean anything.`}>
                    <LemonTag type="warning">Too little data</LemonTag>
                </Tooltip>
            )}
        </span>
    )
}

function RateCell({ reading }: { reading: WorkflowProposalMetricApi | null }): JSX.Element {
    const value = reading ? formatValue(reading.value, 'rate') : null
    return value ? <span>{value}</span> : <span className="text-secondary">No data</span>
}

export function WorkflowAppliedOutcome({
    proposal,
    outcome,
}: {
    proposal: WorkflowProposalApi
    outcome: WorkflowProposalOutcomeApi
}): JSX.Element {
    const beforeByMetric = new Map(readings(outcome.before).map((reading) => [reading.metric, reading]))
    const afterByMetric = new Map(readings(outcome.after).map((reading) => [reading.metric, reading]))
    const metrics = [...new Set([...beforeByMetric.keys(), ...afterByMetric.keys()])]
    const rows: OutcomeRow[] = [
        { key: 'sent', kind: 'sent', label: 'Emails sent' },
        ...metrics.map(
            (metric): OutcomeRow => ({
                key: metric,
                kind: 'rate',
                label: ROW_LABELS[metric] ?? metric,
                before: beforeByMetric.get(metric) ?? null,
                after: afterByMetric.get(metric) ?? null,
            })
        ),
    ]

    const sideColumn = (side: 'before' | 'after'): LemonTableColumns<OutcomeRow>[number] => {
        const version = outcome[side]
        const label = side === 'before' ? 'Before' : 'After'
        return {
            title: version ? `${label} (v${version.version})` : label,
            key: side,
            width: '33%',
            render: (_, row) => (row.kind === 'sent' ? <SentCell side={version} /> : <RateCell reading={row[side]} />),
        }
    }

    const columns: LemonTableColumns<OutcomeRow> = [
        { title: 'Metric', key: 'label', width: '34%', render: (_, row) => <span>{row.label}</span> },
        sideColumn('before'),
        sideColumn('after'),
    ]

    return (
        <div className="border rounded p-3 bg-surface-primary flex flex-col gap-2">
            <div className="flex items-center gap-2 flex-wrap">
                <span className="font-semibold">{proposal.title}</span>
                <LemonTag type="success">Applied as version {proposal.applied_version}</LemonTag>
            </div>
            <p className="mb-0 text-secondary text-sm">
                Measured over {describeWindow(outcome.window)}, before and after. Different periods, so treat a
                difference as a signal to look closer, not as proof.
            </p>
            <LemonTable
                size="small"
                columns={columns}
                dataSource={rows}
                rowKey="key"
                data-attr="workflow-suggestion-outcome"
            />
            {outcome.unavailable_guardrails.length > 0 && (
                <span className="text-xs text-secondary">
                    Not measured:{' '}
                    {outcome.unavailable_guardrails.map((metric) => ROW_LABELS[metric] ?? metric).join(', ')}
                </span>
            )}
        </div>
    )
}
