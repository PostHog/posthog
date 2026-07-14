import { useActions, useValues } from 'kea'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonTable, LemonTableColumn, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { atColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { LemonTag, LemonTagType } from 'lib/lemon-ui/LemonTag'
import { Link } from 'lib/lemon-ui/Link'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

import type { OpportunityApi, ProposedExperimentApi } from './generated/api.schemas'
import { OpportunityKindEnumApi, OpportunityStatusEnumApi } from './generated/api.schemas'
import { HelpfulnessVote } from './HelpfulnessVote'
import { type OpportunityRowAction, opportunitiesLogic, transitionsForStatus } from './opportunitiesLogic'

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
    const { opportunities, opportunitiesLoading, opportunitiesLoadFailed } = useValues(opportunitiesLogic)
    const { loadOpportunities } = useActions(opportunitiesLogic)

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
            // Evidence links resolve to a display label and deep link on the backend (ResourceLink),
            // so render those directly — same shape and treatment as section citations.
            render: (_, opportunity) => (
                <div className="flex flex-wrap gap-1">
                    {opportunity.evidence.map((link) => {
                        const key = `${link.type}:${link.ref}`
                        const tag = <LemonTag>{link.label || key}</LemonTag>
                        return link.url ? (
                            <Link key={key} to={link.url}>
                                {tag}
                            </Link>
                        ) : (
                            <span key={key}>{tag}</span>
                        )
                    })}
                </div>
            ),
        },
        {
            title: '',
            key: 'actions',
            width: 0,
            render: (_, opportunity) => (
                <div className="flex items-center gap-2 justify-end">
                    <OpportunityRowActions opportunity={opportunity} />
                    <OpportunityVote opportunity={opportunity} />
                </div>
            ),
        },
    ]

    // A failed load shows an error with a retry instead of the "run a brief" empty state, which
    // would otherwise contradict the error toast and send the user down the wrong path.
    if (opportunitiesLoadFailed) {
        return (
            <LemonBanner type="error" action={{ children: 'Retry', onClick: () => loadOpportunities() }}>
                Loading opportunities failed.
            </LemonBanner>
        )
    }

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
    const { transitionsInFlight } = useValues(opportunitiesLogic)
    const { transitionOpportunity, createExperimentFromOpportunity } = useActions(opportunitiesLogic)

    const available = transitionsForStatus(opportunity.status)
    const proposal = opportunity.proposed_experiment
    if (available.length === 0 && !proposal) {
        return null
    }
    // Creating an experiment rides the acted transition, so the button is offered exactly when
    // that transition is; elsewhere the proposal stays visible read-only.
    const canCreateExperiment = proposal !== null && available.some(({ transition }) => transition === 'acted')
    const inFlightTransition = transitionsInFlight[opportunity.id]
    // A row's other actions disable while any one of them is mid-flight — same rule for every button.
    const waitingReason = (self: OpportunityRowAction): string | undefined =>
        inFlightTransition && inFlightTransition !== self ? 'Waiting for the current update' : undefined

    return (
        <div className="flex items-center gap-1">
            {proposal && canCreateExperiment && (
                <LemonButton
                    size="small"
                    type="primary"
                    loading={inFlightTransition === 'create_experiment'}
                    disabledReason={waitingReason('create_experiment')}
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
                        disabledReason={waitingReason(transition)}
                        onClick={() => transitionOpportunity(opportunity.id, transition)}
                    >
                        {label}
                    </LemonButton>
                ))}
        </div>
    )
}

function OpportunityVote({ opportunity }: { opportunity: OpportunityApi }): JSX.Element {
    const { feedbackVotesInFlight } = useValues(opportunitiesLogic)
    const { voteOnOpportunity } = useActions(opportunitiesLogic)
    return (
        <HelpfulnessVote
            item={opportunity}
            inFlight={opportunity.id in feedbackVotesInFlight}
            onVote={(helpful, reason) => voteOnOpportunity(opportunity.id, helpful, reason)}
        />
    )
}

function ProposedExperimentSummary({
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
            {proposal.target_metric?.insight_short_id && (
                <span>
                    {/* Plain text, not a link: this summary renders inside a non-interactive tooltip
                        where a link is unreachable by keyboard and mouse. The short ID travels to the
                        experiment form via the clipboard handoff. */}
                    <strong>Target metric insight:</strong> {proposal.target_metric.insight_short_id}
                </span>
            )}
            {footer && <span className="text-muted">{footer}</span>}
        </div>
    )
}
