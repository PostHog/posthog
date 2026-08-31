import { useActions, useValues } from 'kea'

import { IconBolt } from '@posthog/icons'
import { LemonButton, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { TZLabel } from 'lib/components/TZLabel'
import { LemonCollapse } from 'lib/lemon-ui/LemonCollapse'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import type {
    WorkflowProposalApi,
    WorkflowProposalMetricApi,
    WorkflowProposalOutcomeApi,
    WorkflowProposalSourceTypeEnumApi,
} from '../generated/api.schemas'
import { workflowLogic } from './workflowLogic'
import { workflowProposalsLogic } from './workflowProposalsLogic'

const SOURCE_LABELS: Record<WorkflowProposalSourceTypeEnumApi, string> = {
    scout: 'Suggested by a scout',
    responder: 'Suggested by a responder',
    human: 'Suggested by a person',
    stub: 'Suggested by a stub generator',
}

export function WorkflowProposalsBanner({ id }: { id: string }): JSX.Element | null {
    const logic = workflowProposalsLogic({ id })
    const { pendingProposals, appliedProposals, outcomes, resolvingId, resolvingAction } = useValues(logic)
    const { approveProposal, rejectProposal } = useActions(logic)
    const { workflowUserAccessLevel } = useValues(workflowLogic({ id }))

    const measuredApplied = appliedProposals.filter((proposal) => outcomes[proposal.id]?.after)
    if (!pendingProposals.length && !measuredApplied.length) {
        return null
    }

    return (
        <div className="flex flex-col gap-2">
            {pendingProposals.map((proposal) => (
                <div key={proposal.id} className="border rounded p-3 bg-surface-primary flex flex-col gap-2">
                    <div className="flex items-start gap-2">
                        <IconBolt className="text-lg shrink-0 mt-0.5" />
                        <div className="flex flex-col gap-1 grow">
                            <div className="flex items-center gap-2 flex-wrap">
                                <span className="font-semibold">{proposal.title}</span>
                                <LemonTag type="highlight">{SOURCE_LABELS[proposal.source_type]}</LemonTag>
                                {proposal.is_stale && (
                                    <Tooltip title="The live workflow has changed since this was suggested. Check it still makes sense before you publish.">
                                        <LemonTag type="warning">Out of date</LemonTag>
                                    </Tooltip>
                                )}
                            </div>
                            <p className="mb-0 text-secondary">{proposal.rationale}</p>
                            <EvidenceSummary evidence={proposal.evidence} />
                            <span className="text-xs text-secondary">
                                Suggested <TZLabel time={proposal.created_at} /> against version {proposal.base_version}
                            </span>
                        </div>
                        <div className="flex items-center gap-2 shrink-0">
                            <AccessControlAction
                                resourceType={AccessControlResourceType.Workflow}
                                minAccessLevel={AccessControlLevel.Editor}
                                userAccessLevel={workflowUserAccessLevel ?? undefined}
                            >
                                <LemonButton
                                    type="secondary"
                                    size="small"
                                    onClick={() => rejectProposal(proposal.id)}
                                    loading={resolvingId === proposal.id && resolvingAction === 'reject'}
                                    disabledReason={
                                        resolvingId !== null && resolvingId !== proposal.id
                                            ? 'Another suggestion is being resolved'
                                            : undefined
                                    }
                                >
                                    Reject
                                </LemonButton>
                            </AccessControlAction>
                            <AccessControlAction
                                resourceType={AccessControlResourceType.Workflow}
                                minAccessLevel={AccessControlLevel.Editor}
                                userAccessLevel={workflowUserAccessLevel ?? undefined}
                            >
                                <LemonButton
                                    type="primary"
                                    size="small"
                                    onClick={() => approveProposal(proposal.id)}
                                    loading={resolvingId === proposal.id && resolvingAction === 'approve'}
                                    disabledReason={
                                        resolvingId !== null && resolvingId !== proposal.id
                                            ? 'Another suggestion is being resolved'
                                            : undefined
                                    }
                                >
                                    Approve as draft
                                </LemonButton>
                            </AccessControlAction>
                        </div>
                    </div>
                    <LemonCollapse
                        size="small"
                        panels={[
                            {
                                key: 'details',
                                header: 'What it changes and why',
                                content: <ProposalDetails proposal={proposal} />,
                            },
                        ]}
                    />
                </div>
            ))}
            {measuredApplied.map((proposal) => (
                <AppliedOutcome key={proposal.id} proposal={proposal} outcome={outcomes[proposal.id]} />
            ))}
        </div>
    )
}

function MetricReading({ reading }: { reading: WorkflowProposalMetricApi }): JSX.Element {
    return (
        <span className="flex items-center gap-1">
            {reading.metric} {formatValue(reading.value) ?? 'no data'}
            <span className="text-secondary">(n={reading.n})</span>
            {reading.below_minimum_sample && (
                <Tooltip title={`Under ${MIN_EVIDENCE_SAMPLE} observations. Not enough to call this a result.`}>
                    <LemonTag type="warning">Too little data</LemonTag>
                </Tooltip>
            )}
        </span>
    )
}

function AppliedOutcome({
    proposal,
    outcome,
}: {
    proposal: WorkflowProposalApi
    outcome: WorkflowProposalOutcomeApi
}): JSX.Element {
    return (
        <div className="border rounded p-3 bg-surface-primary flex flex-col gap-2">
            <div className="flex items-center gap-2 flex-wrap">
                <span className="font-semibold">{proposal.title}</span>
                <LemonTag type="success">Applied as version {proposal.applied_version}</LemonTag>
            </div>
            {/* Two windows side by side, not a controlled comparison. Said plainly so nobody reads a
                difference here as proof the change caused it. */}
            <p className="mb-0 text-secondary text-sm">
                Measured over {outcome.window}, before and after. Different periods, so treat a difference as a signal
                to look closer, not as proof.
            </p>
            <div className="grid grid-cols-2 gap-3 text-sm">
                {(['before', 'after'] as const).map((side) => {
                    const reading = outcome[side]
                    return (
                        <div key={side} className="flex flex-col gap-1">
                            <span className="font-semibold">
                                {side === 'before' ? 'Before' : 'After'}
                                {reading ? ` (v${reading.version})` : ''}
                            </span>
                            {reading ? (
                                <>
                                    <MetricReading reading={reading.target} />
                                    {reading.guardrails.map((guardrail) => (
                                        <MetricReading key={guardrail.metric} reading={guardrail} />
                                    ))}
                                </>
                            ) : (
                                <span className="text-secondary">No data</span>
                            )}
                        </div>
                    )
                })}
            </div>
            {outcome.unavailable_guardrails.length > 0 && (
                <span className="text-xs text-secondary">
                    Not measured: {outcome.unavailable_guardrails.join(', ')}
                </span>
            )}
        </div>
    )
}

// A rate under this many observations is noise. Mirrors MIN_EVIDENCE_SAMPLE in
// products/workflows/backend/metrics.py.
const MIN_EVIDENCE_SAMPLE = 20

interface GuardrailReading {
    metric: string
    value: number | null
    n?: number
}

function readGuardrails(evidence: Record<string, unknown>): GuardrailReading[] {
    const raw = Array.isArray(evidence.guardrails) ? evidence.guardrails : []
    return raw.filter((entry): entry is GuardrailReading => !!entry && typeof entry === 'object' && 'metric' in entry)
}

function EvidenceSummary({ evidence }: { evidence: Record<string, unknown> }): JSX.Element | null {
    const metric = typeof evidence.metric === 'string' ? evidence.metric : null
    if (!metric) {
        return null
    }
    const current = formatValue(evidence.current_value)
    const target = formatValue(evidence.target_value)
    const window = typeof evidence.window === 'string' ? evidence.window : null
    const sample = typeof evidence.n === 'number' ? evidence.n : null
    const guardrails = readGuardrails(evidence)
    const unavailable = Array.isArray(evidence.guardrails_unavailable)
        ? evidence.guardrails_unavailable.filter((name): name is string => typeof name === 'string')
        : []
    const lowSample = sample !== null && sample < MIN_EVIDENCE_SAMPLE

    return (
        <div className="flex flex-col gap-1 text-sm">
            <span className="flex items-center gap-2 flex-wrap">
                <span>
                    {metric}: {current ?? 'no data'}
                    {target ? `, target ${target}` : ''}
                    {window ? ` over ${window}` : ''}
                    {sample !== null ? ` (${sample} observations)` : ''}
                </span>
                {sample === null && (
                    <Tooltip title="This suggestion did not say how many observations its number came from, so there is no way to tell a result from noise.">
                        <LemonTag type="warning">No sample size</LemonTag>
                    </Tooltip>
                )}
                {lowSample && (
                    <Tooltip
                        title={`Under ${MIN_EVIDENCE_SAMPLE} observations. Treat this as a hunch to check, not a finding.`}
                    >
                        <LemonTag type="warning">Too little data</LemonTag>
                    </Tooltip>
                )}
            </span>
            {guardrails.length > 0 && (
                <span className="text-secondary">
                    Alongside:{' '}
                    {guardrails
                        .map((guardrail) => `${guardrail.metric} ${formatValue(guardrail.value) ?? 'no data'}`)
                        .join(', ')}
                    {unavailable.length > 0 ? `. Not measured: ${unavailable.join(', ')}` : ''}
                </span>
            )}
            {guardrails.length === 0 && (
                <Tooltip title="No counter-metrics were sent with this suggestion, so a change that lifts the target by harming something else would not show here.">
                    <LemonTag type="warning">No counter-metrics</LemonTag>
                </Tooltip>
            )}
        </div>
    )
}

function ProposalDetails({ proposal }: { proposal: WorkflowProposalApi }): JSX.Element {
    const changedFields = Object.keys(proposal.content)

    return (
        <div className="flex flex-col gap-2 text-sm">
            <div>
                <span className="font-semibold">Workflow fields it changes: </span>
                {changedFields.length ? changedFields.join(', ') : 'none'}
            </div>
            <div className="flex flex-col gap-1">
                <span className="font-semibold">Evidence</span>
                <pre className="text-xs bg-surface-secondary rounded p-2 overflow-x-auto mb-0">
                    {JSON.stringify(proposal.evidence, null, 2)}
                </pre>
            </div>
            {proposal.source_id && (
                <div>
                    <span className="font-semibold">Source: </span>
                    {proposal.source_id}
                </div>
            )}
        </div>
    )
}

function formatValue(value: unknown): string | null {
    if (typeof value !== 'number') {
        return null
    }
    return value > 0 && value <= 1 ? `${(value * 100).toFixed(1)}%` : String(value)
}
