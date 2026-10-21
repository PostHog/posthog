import { useActions, useValues } from 'kea'
import { useId, useState } from 'react'

import { IconAtSign, IconChevronLeft } from '@posthog/icons'
import {
    Button,
    Dialog,
    DialogContent,
    DialogTitle,
    Popover,
    PopoverContent,
    PopoverTrigger,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill-primitives'

import { TaxonomicFilter } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { todayShellLogic } from '~/layout/today/todayShellLogic'

import { attachedContextLogic } from '../../logics/attachedContextLogic'
import { CONTEXT_PICKER_GROUP_TYPES, contextPickerLogic } from '../../logics/contextPickerLogic'

export function QuillAttachedContextPicker(): JSX.Element {
    const [open, setOpen] = useState(false)
    const filterKey = `posthog-ai-context-picker-${useId()}`
    const { hasContext } = useValues(attachedContextLogic)
    const { handleTaxonomicFilterChange } = useActions(contextPickerLogic)
    const { todayRailEnabled, phoneLayout } = useValues(todayShellLogic)
    if (todayRailEnabled && phoneLayout) {
        return (
            <>
                <Button
                    variant="default"
                    size={hasContext ? 'icon-lg' : 'lg'}
                    aria-label="Add context"
                    onClick={() => setOpen(true)}
                    data-attr="posthog-ai-context-picker"
                >
                    <IconAtSign />
                    {!hasContext && 'Add context'}
                </Button>
                <Dialog open={open} onOpenChange={setOpen}>
                    <DialogContent
                        showCloseButton={false}
                        className="inset-0 flex h-dvh max-h-none w-screen max-w-none translate-none flex-col gap-0 rounded-none p-0 shadow-none"
                        data-attr="posthog-ai-context-page"
                    >
                        <div className="flex h-12 shrink-0 items-center gap-1 border-b border-border px-1">
                            <Button
                                size="icon-lg"
                                aria-label="Back"
                                onClick={() => setOpen(false)}
                                data-attr="posthog-ai-context-page-back"
                            >
                                <IconChevronLeft />
                            </Button>
                            <DialogTitle>Add context</DialogTitle>
                        </div>
                        <div data-not-quill className="min-h-0 flex-1 overflow-hidden px-5 pt-3">
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
                                width="100%"
                                height={window.innerHeight - 72}
                            />
                        </div>
                    </DialogContent>
                </Dialog>
            </>
        )
    }
    return (
        <Popover open={open} onOpenChange={setOpen}>
            <Tooltip>
                <TooltipTrigger
                    render={
                        <PopoverTrigger
                            render={
                                <Button
                                    variant="default"
                                    size="sm"
                                    aria-label="Add context"
                                    data-attr="posthog-ai-context-picker"
                                >
                                    <IconAtSign />
                                    <span>Add context</span>
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
