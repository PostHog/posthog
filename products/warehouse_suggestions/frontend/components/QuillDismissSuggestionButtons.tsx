import { useActions } from 'kea'

import { IconClock, IconX } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { notNowCondition } from '../suggestionCopy'
import { warehouseSuggestionsLogic } from '../warehouseSuggestionsLogic'
import { DismissSuggestionButtonsProps } from './DismissSuggestionButtons'

const DISMISS_LABEL = "Dismiss. Won't be suggested again."

export function QuillDismissSuggestionButtons({
    suggestionId,
    kind,
    disabledReason,
}: DismissSuggestionButtonsProps): JSX.Element {
    const { dismissSuggestion } = useActions(warehouseSuggestionsLogic)
    const notNowLabel = `Not now. ${notNowCondition(kind)}`

    return (
        <>
            <Button
                size="icon"
                aria-label={notNowLabel}
                tooltip={notNowLabel}
                disabledReason={disabledReason}
                onClick={() => dismissSuggestion(suggestionId, 'not_now')}
                data-attr="warehouse-suggestions-not-now"
            >
                <IconClock />
            </Button>
            <Button
                size="icon"
                aria-label={DISMISS_LABEL}
                tooltip={DISMISS_LABEL}
                disabledReason={disabledReason}
                onClick={() => dismissSuggestion(suggestionId, 'not_useful')}
                data-attr="warehouse-suggestions-dismiss"
            >
                <IconX />
            </Button>
        </>
    )
}
