import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { MemberSelect } from 'lib/components/MemberSelect'

import type { WarehouseSuggestionApi } from '../generated/api.schemas'
import { warehouseSuggestionsLogic } from '../warehouseSuggestionsLogic'

const EDIT_ACCESS_REASON = 'You need edit access to this view or table to assign its suggestion'

export interface SuggestionAssigneeSelectProps {
    suggestionId: string
    assignee: WarehouseSuggestionApi['assignee']
    canAct: boolean
}

export function SuggestionAssigneeSelect({
    suggestionId,
    assignee,
    canAct,
}: SuggestionAssigneeSelectProps): JSX.Element {
    const { actionsInFlight } = useValues(warehouseSuggestionsLogic)
    const { assignSuggestion } = useActions(warehouseSuggestionsLogic)

    return (
        <MemberSelect
            value={assignee?.id ?? null}
            defaultLabel="Unassigned"
            onChange={(user) => assignSuggestion(suggestionId, user?.id ?? null)}
        >
            {() => (
                <LemonButton
                    size="xsmall"
                    type="tertiary"
                    noPadding
                    loading={!!actionsInFlight[suggestionId]}
                    disabledReason={canAct ? undefined : EDIT_ACCESS_REASON}
                    data-attr="warehouse-suggestions-assign"
                >
                    <span className="text-xs font-normal text-secondary">
                        {assignee ? `Assigned to ${assignee.first_name || assignee.email}` : 'Assign'}
                    </span>
                </LemonButton>
            )}
        </MemberSelect>
    )
}
