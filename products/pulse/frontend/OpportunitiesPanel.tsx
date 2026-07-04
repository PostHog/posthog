import { useActions, useValues } from 'kea'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonTable, LemonTableColumn, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { atColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { LemonTag, LemonTagType } from 'lib/lemon-ui/LemonTag'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

import { CitationTag } from './CitationTag'
import type { OpportunityApi, ProposedExperimentApi } from './generated/api.schemas'
import { OpportunityKindEnumApi, OpportunityStatusEnumApi } from './generated/api.schemas'
import { parseOpportunityEvidence, pulseLogic, transitionsForStatus } from './pulseLogic'

// Exhaustive over the enums so a new backend value fails compilation here instead of rendering unstyled.
const STATUS_TAG_TYPES: Record<OpportunityStatusEnumApi, LemonTagType> = {
    [OpportunityStatusEnumApi.Open]: 'primary',
    [OpportunityStatusEnumApi.Dismissed]: 'muted',
    [OpportunityStatusEnumApi.Acted]: 'success',
    [OpportunityStatusEnumApi.Resolved]: 'completion',
}

const KIND_TAG_TYPES: Record<OpportunityKindEnumApi, LemonTagType> = {
    [OpportunityKindEnumApi.Build]: 'highlight',
    [OpportunityKindEnumApi.Fix]: 'danger',
    [OpportunityKindEnumApi.Instrument]: 'caution',
}

export function OpportunitiesPanel(): JSX.Element {
    const { opportunities, opportunitiesLoading } = useValues(pulseLogic)

    const columns: LemonTableColumns<OpportunityApi> = [
        {
            title: 'Kind',
            key: 'kind',
            width: 0,
            render: (_, opportunity) => <LemonTag type={KIND_TAG_TYPES[opportunity.kind]}>{opportunity.kind}</LemonTag>,
        },
        {
            title: 'Opportunity',
            key: 'title',
            render: (_, opportunity) => (
                <div className="flex flex-col gap-1">
                    <span className="flex items-center gap-2">
                        <span className="font-semibold">{opportunity.title}</span>
                        {opportunity.goal_relevant && (
                            <LemonTag size="small" type="completion">
                                Goal
                            </LemonTag>
                        )}
                    </span>
                    <span className="text-muted text-xs">{opportunity.summary}</span>
                </div>
            ),
        },
        {
            title: 'Status',
            key: 'status',
            width: 0,
            render: (_, opportunity) => (
                <LemonTag type={STATUS_TAG_TYPES[opportunity.status]}>{opportunity.status}</LemonTag>
            ),
        },
        atColumn<OpportunityApi>('created_at', 'Surfaced') as LemonTableColumn<
            OpportunityApi,
            keyof OpportunityApi | undefined
        >,
        {
            title: 'Evidence',
            key: 'evidence',
            render: (_, opportunity) => (
                <div className="flex flex-wrap gap-1">
                    {parseOpportunityEvidence(opportunity.evidence).map((citation) => (
                        <CitationTag key={`${citation.type}:${citation.ref}`} citation={citation} />
                    ))}
                </div>
            ),
        },
        {
            title: '',
            key: 'actions',
            width: 0,
            render: (_, opportunity) => <OpportunityRowActions opportunity={opportunity} />,
        },
    ]

    return (
        <LemonTable
            dataSource={opportunities}
            columns={columns}
            loading={opportunitiesLoading}
            rowKey="id"
            emptyState="No opportunities yet — run a brief to surface some"
        />
    )
}

function OpportunityRowActions({ opportunity }: { opportunity: OpportunityApi }): JSX.Element | null {
    const { transitionsInFlight } = useValues(pulseLogic)
    const { transitionOpportunity, createExperimentFromOpportunity } = useActions(pulseLogic)

    const available = transitionsForStatus(opportunity.status)
    const proposal = opportunity.proposed_experiment
    if (available.length === 0 && !proposal) {
        return null
    }
    // Creating an experiment rides the acted transition, so the button is offered exactly when
    // that transition is; elsewhere the proposal stays visible read-only.
    const canCreateExperiment = proposal !== null && available.some(({ transition }) => transition === 'acted')
    const inFlightTransition = transitionsInFlight[opportunity.id]

    return (
        <div className="flex items-center gap-1">
            {proposal && canCreateExperiment && (
                <LemonButton
                    size="small"
                    type="primary"
                    loading={inFlightTransition === 'create_experiment'}
                    disabledReason={
                        inFlightTransition && inFlightTransition !== 'create_experiment'
                            ? 'Waiting for the current update'
                            : undefined
                    }
                    tooltip={
                        <ProposedExperimentSummary
                            proposal={proposal}
                            footer="Marks the opportunity as acted, copies the proposal, and opens a new experiment."
                        />
                    }
                    onClick={() => createExperimentFromOpportunity(opportunity.id)}
                >
                    Create experiment
                </LemonButton>
            )}
            {proposal && !canCreateExperiment && (
                <Tooltip title={<ProposedExperimentSummary proposal={proposal} />}>
                    <LemonTag type="completion">Proposed experiment</LemonTag>
                </Tooltip>
            )}
            {available
                // "Create experiment" IS the acted action for proposal rows — one action per outcome.
                .filter(({ transition }) => !(canCreateExperiment && transition === 'acted'))
                .map(({ label, transition }) => (
                    <LemonButton
                        key={transition}
                        size="small"
                        type="secondary"
                        loading={inFlightTransition === transition}
                        disabledReason={
                            inFlightTransition && inFlightTransition !== transition
                                ? 'Waiting for the current update'
                                : undefined
                        }
                        onClick={() => transitionOpportunity(opportunity.id, transition)}
                    >
                        {label}
                    </LemonButton>
                ))}
        </div>
    )
}

export function ProposedExperimentSummary({
    proposal,
    footer,
}: {
    proposal: ProposedExperimentApi
    footer?: string
}): JSX.Element {
    return (
        <div className="flex flex-col gap-1">
            <span>
                <strong>Hypothesis:</strong> {proposal.hypothesis}
            </span>
            <span>
                <strong>Variants:</strong> {proposal.variant_sketch}
            </span>
            <span>
                <strong>Flag key:</strong> {proposal.flag_key_suggestion}
            </span>
            {proposal.target_metric && (
                <span>
                    <strong>Target metric:</strong> {proposal.target_metric.insight_short_id}
                </span>
            )}
            {footer && <span className="text-muted">{footer}</span>}
        </div>
    )
}
