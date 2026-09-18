import { LemonCollapse, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { Sparkline } from 'lib/components/Sparkline'
import { TZLabel } from 'lib/components/TZLabel'
import { LemonTable } from 'lib/lemon-ui/LemonTable'

import type {
    WorkflowProposalApi,
    WorkflowProposalMetricApi,
    WorkflowProposalOutcomeApi,
    WorkflowProposalVersionOutcomeApi,
} from '../generated/api.schemas'
import { MIN_EVIDENCE_SAMPLE, formatValue } from './suggestionEvidence'

const ROW_LABELS: Record<string, string> = {
    'email open rate': 'Opened',
    'click rate': 'Clicked',
    'complaint rate': 'Complaints',
    'bounce rate': 'Bounced',
    'unsubscribe rate': 'Unsubscribed',
}

// Roughly 6rem a bar, so a workflow with three versions does not get three bars the width of the card.
const CHART_WIDTHS = [
    'max-w-[8rem]',
    'max-w-[8rem]',
    'max-w-[14rem]',
    'max-w-[20rem]',
    'max-w-[26rem]',
    'max-w-[32rem]',
]

function percent(reading: WorkflowProposalMetricApi | undefined): number {
    return reading?.value ? Math.round(reading.value * 1000) / 10 : 0
}

function Reading({ label, reading }: { label: string; reading: WorkflowProposalMetricApi | undefined }): JSX.Element {
    return (
        <span className="flex items-baseline gap-1">
            <span className="text-secondary">{label}</span>
            <span className="font-semibold">
                {reading ? (formatValue(reading.value, 'rate') ?? 'No data') : 'No data'}
            </span>
        </span>
    )
}

export function WorkflowAppliedOutcome({
    proposal,
    outcome,
}: {
    proposal: WorkflowProposalApi
    outcome: WorkflowProposalOutcomeApi
}): JSX.Element {
    // Only versions that sent something can carry a rate, and a zero bar for one that never ran reads as a drop.
    const charted = (outcome.versions ?? []).filter((version) => version.guardrails[0]?.n || version.target.n)
    const latest: WorkflowProposalVersionOutcomeApi | undefined = charted[charted.length - 1]
    const labels = charted.map((version) => `v${version.version}${version.applied ? ' (applied)' : ''}`)

    return (
        <div className="border rounded p-3 bg-surface-primary flex flex-col gap-2">
            <div className="flex items-center gap-2 flex-wrap">
                <span className="font-semibold">{proposal.title}</span>
                <LemonTag type="success">Applied as version {proposal.applied_version}</LemonTag>
                {outcome.change_ended_at_version !== null && outcome.change_ended_at_version !== undefined && (
                    <Tooltip
                        title={`Version ${outcome.change_ended_at_version} changed this again, so later versions are measuring something else.`}
                    >
                        <LemonTag type="warning">Changed again in v{outcome.change_ended_at_version}</LemonTag>
                    </Tooltip>
                )}
            </div>
            {charted.length === 0 ? (
                <p className="mb-0 text-secondary text-sm">
                    No sends recorded on this step yet, so there is nothing to compare.
                </p>
            ) : (
                <>
                    <p className="mb-0 text-secondary text-sm">
                        Open rate of this step on each published version, over the time that version was live. Other
                        edits ship in these versions too, so read a move as a signal to look closer, not as proof.
                    </p>
                    <div
                        data-attr="workflow-suggestion-outcome"
                        className={`flex flex-col gap-1 ${CHART_WIDTHS[Math.min(charted.length, CHART_WIDTHS.length - 1)]}`}
                    >
                        <Sparkline
                            className="w-full h-28"
                            type="bar"
                            labels={labels}
                            // Two series so the version the suggestion shipped as is its own colour. Every other
                            // index is zero, and stacked bars put one value per version either way.
                            data={[
                                {
                                    name: 'Applied',
                                    values: charted.map((version) => (version.applied ? percent(version.target) : 0)),
                                    color: 'warning',
                                },
                                {
                                    name: 'Opened',
                                    values: charted.map((version) => (version.applied ? 0 : percent(version.target))),
                                    color: 'success',
                                },
                            ]}
                            hideZerosInTooltip
                            renderTooltipValue={(value) => `${value}%`}
                            // From zero, so a bar's height is the rate rather than its distance from the lowest version.
                            valueDomain={{ min: 0 }}
                        />
                        <div className="flex">
                            {charted.map((version) => (
                                <span key={version.version} className="flex-1 flex flex-col items-center text-xs">
                                    <span className="font-semibold">
                                        {formatValue(version.target.value, 'rate') ?? 'No data'}
                                    </span>
                                    <span className={version.applied ? 'font-semibold text-warning' : 'text-secondary'}>
                                        v{version.version}
                                        {version.applied ? ' · applied' : ''}
                                    </span>
                                    {version.other_changes && (
                                        <Tooltip title="This version changed other things too, so its numbers hold more than this suggestion.">
                                            <span className="text-secondary">+ other edits</span>
                                        </Tooltip>
                                    )}
                                </span>
                            ))}
                        </div>
                    </div>
                    {latest && (
                        <div className="flex items-center gap-4 flex-wrap text-sm">
                            <span className="text-secondary">v{latest.version}:</span>
                            <Reading label={ROW_LABELS['email open rate']} reading={latest.target} />
                            <Reading label={ROW_LABELS['click rate']} reading={latest.click_through} />
                            {latest.guardrails.map((guardrail) => (
                                <Reading
                                    key={guardrail.metric}
                                    label={ROW_LABELS[guardrail.metric] ?? guardrail.metric}
                                    reading={guardrail}
                                />
                            ))}
                            <span className="text-secondary">
                                on {latest.guardrails[0]?.n ?? latest.target.n} sends
                            </span>
                            {latest.target.below_minimum_sample && (
                                <Tooltip
                                    title={`Under ${MIN_EVIDENCE_SAMPLE} sends. Not enough for the rates to mean anything.`}
                                >
                                    <LemonTag type="warning">Too little data</LemonTag>
                                </Tooltip>
                            )}
                        </div>
                    )}
                </>
            )}
            {charted.some((version) => version.changes?.length) && (
                <LemonCollapse
                    size="small"
                    panels={[
                        {
                            key: 'changes',
                            header: 'What changed in each version',
                            content: (
                                <div className="flex flex-col gap-3">
                                    {[...charted].reverse().map((version) => (
                                        <div key={version.version} className="flex flex-col gap-1">
                                            <span className="flex items-center gap-2 flex-wrap text-sm">
                                                <span className="font-semibold">v{version.version}</span>
                                                {version.applied && <LemonTag type="warning">the suggestion</LemonTag>}
                                                {version.published_by && (
                                                    <span className="text-secondary">
                                                        published by{' '}
                                                        {version.published_by.first_name || version.published_by.email}
                                                    </span>
                                                )}
                                                {version.published_at && <TZLabel time={version.published_at} />}
                                            </span>
                                            {version.changes?.length ? (
                                                <LemonTable
                                                    size="small"
                                                    embedded
                                                    columns={[
                                                        {
                                                            title: 'Field',
                                                            key: 'field',
                                                            render: (_, change) => (
                                                                <span className="flex items-center gap-1 flex-wrap">
                                                                    {change.step_name && (
                                                                        <span className="text-secondary">
                                                                            {change.step_name} ›
                                                                        </span>
                                                                    )}
                                                                    <span>{change.field}</span>
                                                                    {change.from_suggestion && (
                                                                        <LemonTag type="warning" size="small">
                                                                            suggested
                                                                        </LemonTag>
                                                                    )}
                                                                </span>
                                                            ),
                                                        },
                                                        {
                                                            title: 'Was',
                                                            key: 'before',
                                                            render: (_, change) => (
                                                                <span className="text-secondary">
                                                                    {change.before ?? 'not set'}
                                                                </span>
                                                            ),
                                                        },
                                                        {
                                                            title: 'Became',
                                                            key: 'after',
                                                            render: (_, change) => (
                                                                <span>{change.after ?? 'removed'}</span>
                                                            ),
                                                        },
                                                    ]}
                                                    dataSource={version.changes}
                                                    rowKey={(change) => `${change.step_name}:${change.field}`}
                                                />
                                            ) : (
                                                <span className="text-xs text-secondary">
                                                    Nothing recorded for this version.
                                                </span>
                                            )}
                                        </div>
                                    ))}
                                </div>
                            ),
                        },
                    ]}
                />
            )}
            {outcome.unavailable_guardrails.length > 0 && (
                <span className="text-xs text-secondary">
                    Not measured:{' '}
                    {outcome.unavailable_guardrails.map((metric) => ROW_LABELS[metric] ?? metric).join(', ')}
                </span>
            )}
        </div>
    )
}
