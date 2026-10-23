import { useActions } from 'kea'

import { LemonButton, LemonMenu } from '@posthog/lemon-ui'

import { notNowCondition } from '../suggestionCopy'
import { warehouseSuggestionsLogic } from '../warehouseSuggestionsLogic'

export interface DismissSuggestionMenuProps {
    suggestionId: string
    kind: string
    disabledReason?: string
}

export function DismissSuggestionMenu({ suggestionId, kind, disabledReason }: DismissSuggestionMenuProps): JSX.Element {
    const { dismissSuggestion } = useActions(warehouseSuggestionsLogic)

    return (
        <LemonMenu
            items={[
                {
                    label: "Not useful. Won't be suggested again.",
                    onClick: () => dismissSuggestion(suggestionId, 'not_useful'),
                },
                {
                    label: `Not now. ${notNowCondition(kind)}`,
                    onClick: () => dismissSuggestion(suggestionId, 'not_now'),
                },
                { label: 'Something else', onClick: () => dismissSuggestion(suggestionId, 'other') },
            ]}
        >
            <LemonButton
                size="small"
                type="tertiary"
                disabledReason={disabledReason}
                data-attr="warehouse-suggestions-dismiss"
            >
                Dismiss
            </LemonButton>
        </LemonMenu>
    )
}
