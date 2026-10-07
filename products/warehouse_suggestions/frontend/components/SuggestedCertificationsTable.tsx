import { BindLogic, useActions, useValues } from 'kea'

import { LemonButton, LemonTable, LemonTableColumns, LemonTag } from '@posthog/lemon-ui'

import type { WarehouseSuggestionApi } from '../generated/api.schemas'
import { WarehouseSuggestionsLogicProps, warehouseSuggestionsLogic } from '../warehouseSuggestionsLogic'
import { DismissSuggestionMenu } from './DismissSuggestionMenu'
import { WhyThisSuggestion } from './WhyThisSuggestion'

const EDIT_ACCESS_REASON = 'You need edit access to this view or table'
const ACCEPT_LABELS: Record<string, string> = { certify: 'Certify', deprecate: 'Mark deprecated' }
const PROPOSAL_LABELS: Record<string, string> = { certify: 'Certify', deprecate: 'Deprecate, unread for a month' }

export interface SuggestedCertificationsTableProps {
    onAccepted?: WarehouseSuggestionsLogicProps['onAccepted']
}

export function SuggestedCertificationsTable({ onAccepted }: SuggestedCertificationsTableProps): JSX.Element | null {
    const logicProps: WarehouseSuggestionsLogicProps = { surface: 'catalog', onAccepted }
    return (
        <BindLogic logic={warehouseSuggestionsLogic} props={logicProps}>
            <SuggestionsTable />
        </BindLogic>
    )
}

function SuggestionsTable(): JSX.Element | null {
    const { surfaceSuggestions, actionsInFlight, status } = useValues(warehouseSuggestionsLogic)
    const { acceptSuggestion } = useActions(warehouseSuggestionsLogic)

    if (surfaceSuggestions.length === 0) {
        return null
    }
    const windowDays = status?.window_days ?? 0

    const columns: LemonTableColumns<WarehouseSuggestionApi> = [
        {
            title: 'Target',
            key: 'target',
            render: (_, suggestion) => (
                <div className="flex flex-wrap items-center gap-2">
                    <span className="truncate">{suggestion.payload.subject_name}</span>
                    <LemonTag type="highlight">Suggested</LemonTag>
                </div>
            ),
        },
        {
            title: 'Type',
            key: 'subject_kind',
            render: (_, suggestion) => (
                <LemonTag type="option">{suggestion.subject_kind === 'table' ? 'table' : 'view'}</LemonTag>
            ),
        },
        {
            title: 'Suggestion',
            key: 'kind',
            render: (_, suggestion) => PROPOSAL_LABELS[suggestion.kind] ?? suggestion.kind,
        },
        {
            key: 'actions',
            render: (_, suggestion) => {
                const inFlight = !!actionsInFlight[suggestion.id]
                const blockedReason = !suggestion.can_act ? EDIT_ACCESS_REASON : undefined
                return (
                    <div className="flex flex-wrap items-center justify-end gap-2">
                        <WhyThisSuggestion evidence={suggestion.evidence} windowDays={windowDays} />
                        <LemonButton
                            size="xsmall"
                            type="secondary"
                            loading={inFlight}
                            disabledReason={blockedReason}
                            onClick={() => acceptSuggestion(suggestion.id)}
                            data-attr={`warehouse-suggestions-${suggestion.kind}`}
                        >
                            {ACCEPT_LABELS[suggestion.kind] ?? 'Accept'}
                        </LemonButton>
                        <DismissSuggestionMenu
                            suggestionId={suggestion.id}
                            disabledReason={blockedReason ?? (inFlight ? 'Working' : undefined)}
                        />
                    </div>
                )
            },
        },
    ]

    return (
        <div className="flex flex-col gap-2">
            <div>
                <h3 className="m-0 text-sm font-semibold">Suggested</h3>
                <span className="text-xs text-muted">
                    Found from how this project reads its tables. Nothing changes until you accept.
                </span>
            </div>
            <LemonTable
                data-attr="warehouse-suggestions-catalog-table"
                dataSource={surfaceSuggestions}
                rowKey="id"
                columns={columns}
                size="small"
            />
        </div>
    )
}
