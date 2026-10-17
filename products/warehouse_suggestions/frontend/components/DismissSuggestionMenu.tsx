import { useActions } from 'kea'

import { LemonButton, LemonMenu } from '@posthog/lemon-ui'

import { warehouseSuggestionsLogic } from '../warehouseSuggestionsLogic'

export interface DismissSuggestionMenuProps {
    suggestionId: string
    disabledReason?: string
}

export function DismissSuggestionMenu({ suggestionId, disabledReason }: DismissSuggestionMenuProps): JSX.Element {
    const { dismissSuggestion } = useActions(warehouseSuggestionsLogic)

    return (
        <LemonMenu
            items={[
                {
                    label: "Not useful. Won't be suggested again.",
                    onClick: () => dismissSuggestion(suggestionId, 'not_useful'),
                },
                {
                    label: 'Not now. Suggested again if reads grow.',
                    onClick: () => dismissSuggestion(suggestionId, 'not_now'),
                },
                { label: 'Something else', onClick: () => dismissSuggestion(suggestionId, 'other') },
            ]}
        >
            <LemonButton
                size="xsmall"
                type="tertiary"
                disabledReason={disabledReason}
                data-attr="warehouse-suggestions-dismiss"
            >
                Dismiss
            </LemonButton>
        </LemonMenu>
    )
}
