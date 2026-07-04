import { useActions, useValues } from 'kea'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonTable, LemonTableColumn, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { atColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { LemonTag, LemonTagType } from 'lib/lemon-ui/LemonTag'

import { CitationTag } from './CitationTag'
import type { OpportunityApi } from './generated/api.schemas'
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
    const { transitionOpportunity } = useActions(pulseLogic)

    const available = transitionsForStatus(opportunity.status)
    if (available.length === 0) {
        return null
    }
    const inFlightTransition = transitionsInFlight[opportunity.id]

    return (
        <div className="flex gap-1">
            {available.map(({ label, transition }) => (
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
