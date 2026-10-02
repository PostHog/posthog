import { useActions, useValues } from 'kea'
import { useId, useState } from 'react'

import { IconAtSign } from '@posthog/icons'
import {
    Button,
    Popover,
    PopoverContent,
    PopoverTrigger,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill-primitives'

import { TaxonomicFilter } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { attachedContextLogic } from '../../logics/attachedContextLogic'
import { CONTEXT_PICKER_GROUP_TYPES, contextPickerLogic } from '../../logics/contextPickerLogic'

export function QuillAttachedContextPicker(): JSX.Element {
    const [open, setOpen] = useState(false)
    const filterKey = `posthog-ai-context-picker-${useId()}`
    const { hasContext } = useValues(attachedContextLogic)
    const { handleTaxonomicFilterChange } = useActions(contextPickerLogic)
    return (
        <Popover open={open} onOpenChange={setOpen}>
            <Tooltip>
                <TooltipTrigger
                    render={
                        <PopoverTrigger
                            render={
                                <Button
                                    variant="default"
                                    size={hasContext ? 'icon-sm' : 'sm'}
                                    aria-label="Add context"
                                    data-attr="posthog-ai-context-picker"
                                >
                                    <IconAtSign />
                                    {!hasContext && 'Add context'}
                                </Button>
                            }
                        />
                    }
                />
                <TooltipContent>Add context to help PostHog AI answer your question</TooltipContent>
            </Tooltip>
            <PopoverContent side="top" align="start" className="w-auto p-0">
                {/* The filter is Lemon, so it keeps Lemon's colors inside the quill popover. */}
                <div data-not-quill>
                    <TaxonomicFilter
                        taxonomicFilterLogicKey={filterKey}
                        groupType={TaxonomicFilterGroupType.Events}
                        taxonomicGroupTypes={CONTEXT_PICKER_GROUP_TYPES}
                        onChange={({ type }, value, item) => {
                            if (value !== null) {
                                handleTaxonomicFilterChange(value, type, item)
                            }
                            setOpen(false)
                        }}
                        onClose={() => setOpen(false)}
                        width={450}
                    />
                </div>
            </PopoverContent>
        </Popover>
    )
}
