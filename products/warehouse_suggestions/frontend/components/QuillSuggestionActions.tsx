import { useActions } from 'kea'
import { ReactNode } from 'react'

import { IconChevronDown, IconClock, IconX } from '@posthog/icons'
import {
    Button,
    ButtonGroup,
    ButtonGroupSeparator,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
} from '@posthog/quill'

import type { WarehouseSuggestionApi } from '../generated/api.schemas'
import { notNowCondition } from '../suggestionCopy'
import { warehouseSuggestionsLogic } from '../warehouseSuggestionsLogic'

export interface QuillSuggestionActionsProps {
    suggestion: WarehouseSuggestionApi
    label: string
    icon: ReactNode
    onAccept: () => void
    acceptBlockedReason?: string
    dismissBlockedReason?: string
    loading?: boolean
    acceptDataAttr: string
}

export function QuillSuggestionActions({
    suggestion,
    label,
    icon,
    onAccept,
    acceptBlockedReason,
    dismissBlockedReason,
    loading,
    acceptDataAttr,
}: QuillSuggestionActionsProps): JSX.Element {
    const { dismissSuggestion } = useActions(warehouseSuggestionsLogic)

    return (
        <DropdownMenu>
            <ButtonGroup>
                <Button
                    variant="outline"
                    size="sm"
                    loading={loading}
                    disabledReason={acceptBlockedReason}
                    onClick={onAccept}
                    data-attr={acceptDataAttr}
                >
                    {icon}
                    {label}
                </Button>
                <ButtonGroupSeparator />
                <DropdownMenuTrigger
                    render={
                        <Button
                            variant="outline"
                            size="icon-sm"
                            aria-label={`More choices for ${suggestion.payload.subject_name}`}
                            disabledReason={dismissBlockedReason}
                            data-attr="warehouse-suggestions-more"
                        />
                    }
                >
                    <IconChevronDown />
                </DropdownMenuTrigger>
            </ButtonGroup>
            <DropdownMenuContent align="end" className="w-72">
                <DropdownMenuItem
                    description={notNowCondition(suggestion.kind)}
                    onClick={() => dismissSuggestion(suggestion.id, 'not_now')}
                    data-attr="warehouse-suggestions-not-now"
                >
                    <IconClock />
                    Not now
                </DropdownMenuItem>
                <DropdownMenuItem
                    description="It won't be suggested again."
                    onClick={() => dismissSuggestion(suggestion.id, 'not_useful')}
                    data-attr="warehouse-suggestions-dismiss"
                >
                    <IconX />
                    Dismiss
                </DropdownMenuItem>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
