import { useActions } from 'kea'

import { IconClock, IconX } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { notNowCondition } from '../suggestionCopy'
import { warehouseSuggestionsLogic } from '../warehouseSuggestionsLogic'

export interface DismissSuggestionButtonsProps {
    suggestionId: string
    kind: string
    disabledReason?: string
}

export function DismissSuggestionButtons({
    suggestionId,
    kind,
    disabledReason,
}: DismissSuggestionButtonsProps): JSX.Element {
    const { dismissSuggestion } = useActions(warehouseSuggestionsLogic)

    return (
        <>
            <LemonButton
                size="small"
                type="tertiary"
                icon={<IconClock />}
                tooltip={`Not now. ${notNowCondition(kind)}`}
                disabledReason={disabledReason}
                onClick={() => dismissSuggestion(suggestionId, 'not_now')}
                data-attr="warehouse-suggestions-not-now"
            />
            <LemonButton
                size="small"
                type="tertiary"
                icon={<IconX />}
                tooltip="Dismiss. Won't be suggested again."
                disabledReason={disabledReason}
                onClick={() => dismissSuggestion(suggestionId, 'not_useful')}
                data-attr="warehouse-suggestions-dismiss"
            />
        </>
    )
}
