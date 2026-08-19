import { useActions, useValues } from 'kea'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonTable, LemonTableColumn, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { atColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { LemonTag, LemonTagType } from 'lib/lemon-ui/LemonTag'
import { Link } from 'lib/lemon-ui/Link'

import type { OpportunityApi } from './generated/api.schemas'
import { OpportunityKindEnumApi, OpportunityStatusEnumApi } from './generated/api.schemas'
import { opportunitiesLogic, transitionsForStatus } from './opportunitiesLogic'

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
                    <span className="font-semibold">{opportunity.title}</span>
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
            render: (_, opportunity) => <OpportunityRowActions opportunity={opportunity} />,
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
    const { transitionOpportunity } = useActions(opportunitiesLogic)

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
