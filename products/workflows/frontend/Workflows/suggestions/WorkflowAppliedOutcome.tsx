import { LemonCollapse, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonTable } from 'lib/lemon-ui/LemonTable'

import type {
    WorkflowProposalApi,
    WorkflowProposalMetricApi,
    WorkflowProposalOutcomeApi,
    WorkflowProposalVersionOutcomeApi,
} from '../../generated/api.schemas'
import { MIN_EVIDENCE_SAMPLE, formatValue } from './suggestionEvidence'

const ROW_LABELS: Record<string, string> = {
    'email open rate': 'Opened',
    'click rate': 'Clicked',
    'complaint rate': 'Complaints',
    'bounce rate': 'Bounced',
    'unsubscribe rate': 'Unsubscribed',
}

// Roughly 6rem a bar, so a workflow with three versions does not get three bars the width of the card.
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
                        The {charted[0].target.metric} of this step on each published version, over the time that
                        version was live. Other edits ship in these versions too, so read a move as a signal to look
                        closer, not as proof.
                    </p>
                    <LemonTable
                        size="small"
                        data-attr="workflow-suggestion-outcome"
                        columns={[
                            {
                                title: 'Version',
                                key: 'version',
                                width: '18%',
                                render: (_, version) => (
                                    <span className="flex flex-col gap-0.5">
                                        <span className={version.applied ? 'font-semibold' : undefined}>
                                            v{version.version}
                                        </span>
                                        {version.published_at && (
                                            <span className="text-xs text-secondary">
                                                <TZLabel time={version.published_at} />
                                            </span>
                                        )}
                                    </span>
                                ),
                            },
                            {
                                title: 'The change',
                                key: 'change',
                                width: '22%',
                                render: (_, version) =>
                                    version.applied ? (
                                        <LemonTag type="warning">applied here</LemonTag>
                                    ) : version.carries_change ? (
                                        <span className="flex items-center gap-2 flex-wrap">
                                            <span>still in</span>
                                            {version.other_changes && (
                                                <span className="text-xs text-secondary">+ other edits</span>
                                            )}
                                        </span>
                                    ) : (
                                        <span className="text-secondary">
                                            {version.version < (proposal.applied_version ?? 0)
                                                ? 'before it'
                                                : 'changed again'}
                                        </span>
                                    ),
                            },
                            {
                                title: ROW_LABELS[charted[0].target.metric] ?? charted[0].target.metric,
                                key: 'target',
                                width: '25%',
                                render: (_, version) => (
                                    <span className="flex flex-col gap-1">
                                        <span>{formatValue(version.target.value, 'rate') ?? 'No data'}</span>
                                        <span className="h-1 w-4/5 rounded bg-fill-primary overflow-hidden">
                                            <span
                                                className="block h-full rounded bg-accent"
                                                // The width is the rate against the best version, so it cannot be a class.
                                                style={{
                                                    width: `${Math.max(2, (percent(version.target) / Math.max(...charted.map((other) => percent(other.target)), 1)) * 100)}%`,
                                                }}
                                            />
                                        </span>
                                    </span>
                                ),
                            },
                            {
                                title: ROW_LABELS[charted[0].secondary?.metric ?? ''] ?? 'Clicked',
                                key: 'secondary',
                                width: '20%',
                                render: (_, version) => (
                                    <span className="text-secondary">
                                        {formatValue((version.secondary ?? version.click_through).value, 'rate') ??
                                            'No data'}
                                    </span>
                                ),
                            },
                            {
                                title: 'Sends',
                                key: 'sends',
                                width: '15%',
                                render: (_, version) => (
                                    <span className="text-secondary">
                                        {version.guardrails[0]?.n ?? version.target.n}
                                    </span>
                                ),
                            },
                        ]}
                        dataSource={charted}
                        rowKey={(version) => String(version.version)}
                    />
                    {latest && (
                        <div className="flex items-center gap-4 flex-wrap text-sm">
                            <span className="text-secondary">Live version:</span>
                            {latest.guardrails.map((guardrail) => (
                                <Reading
                                    key={guardrail.metric}
                                    label={ROW_LABELS[guardrail.metric] ?? guardrail.metric}
                                    reading={guardrail}
                                />
                            ))}
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
                                <div className="flex flex-col">
                                    {[...charted].reverse().map((version, index) => (
                                        <div
                                            key={version.version}
                                            className={`flex flex-col gap-2 ${index > 0 ? 'pt-4' : ''}`}
                                        >
                                            <div className="flex flex-col gap-0.5">
                                                <span className="flex items-center gap-2 flex-wrap">
                                                    <h4 className="mb-0">Version {version.version}</h4>
                                                    {version.applied && (
                                                        <LemonTag type="warning">the suggestion</LemonTag>
                                                    )}
                                                </span>
                                                <span className="flex items-center gap-1 flex-wrap text-xs text-secondary">
                                                    {version.published_by && (
                                                        <span>
                                                            Published by{' '}
                                                            {version.published_by.first_name ||
                                                                version.published_by.email}
                                                        </span>
                                                    )}
                                                    {version.published_at && <TZLabel time={version.published_at} />}
                                                </span>
                                            </div>
                                            {version.changes?.length ? (
                                                <LemonTable
                                                    size="small"
                                                    columns={[
                                                        {
                                                            title: 'Field',
                                                            key: 'field',
                                                            // Same split as the suggestion card's table, so the two read alike.
                                                            width: '20%',
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
                                                            width: '40%',
                                                            render: (_, change) => (
                                                                <span className="text-secondary">
                                                                    {change.before ?? 'not set'}
                                                                </span>
                                                            ),
                                                        },
                                                        {
                                                            title: 'Became',
                                                            key: 'after',
                                                            width: '40%',
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
