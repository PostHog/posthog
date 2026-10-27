import { useActions, useValues } from 'kea'
import { type RefObject, useId, useState } from 'react'

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
import { cn } from 'lib/utils/css-classes'

import { todayShellLogic } from '~/layout/today/todayShellLogic'

import { attachedContextLogic } from '../../logics/attachedContextLogic'
import { CONTEXT_PICKER_GROUP_TYPES, contextPickerLogic } from '../../logics/contextPickerLogic'
import { COMPOSER_MENU_CLASS } from './composerMenuClass'

export interface QuillAttachedContextPickerProps {
    open?: boolean
    onOpenChange?: (open: boolean) => void
    anchor?: RefObject<HTMLElement>
}

export function QuillAttachedContextPicker({
    open: controlledOpen,
    onOpenChange,
    anchor,
}: QuillAttachedContextPickerProps = {}): JSX.Element {
    const [uncontrolledOpen, setUncontrolledOpen] = useState(false)
    const open = controlledOpen ?? uncontrolledOpen
    const setOpen = (next: boolean): void => {
        setUncontrolledOpen(next)
        onOpenChange?.(next)
    }
    const filterKey = `posthog-ai-context-picker-${useId()}`
    const { hasContext } = useValues(attachedContextLogic)
    const { handleTaxonomicFilterChange } = useActions(contextPickerLogic)
    const { todayRailEnabled, phoneLayout } = useValues(todayShellLogic)
    if (todayRailEnabled && phoneLayout) {
        return (
            <>
                {!anchor && (
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
                )}
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
            {!anchor && (
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
                                        <span className="@max-[480px]/composer:hidden">Add context</span>
                                    </Button>
                                }
                            />
                        }
                    />
                    <TooltipContent>Add context to help PostHog AI answer your question</TooltipContent>
                </Tooltip>
            )}
            <PopoverContent
                side="top"
                align="start"
                sideOffset={8}
                anchor={anchor}
                className={cn(
                    'overflow-hidden p-0',
                    COMPOSER_MENU_CLASS,
                    anchor
                        ? 'w-(--anchor-width) max-w-[calc(100vw-2rem)] transition-[opacity,translate] duration-[180ms] ease-[cubic-bezier(0.23,1,0.32,1)] data-[ending-style]:translate-y-1 data-[ending-style]:transform-none data-[ending-style]:duration-[120ms] data-[starting-style]:translate-y-1.5 data-[starting-style]:transform-none motion-reduce:data-[ending-style]:translate-y-0 motion-reduce:data-[starting-style]:translate-y-0'
                        : 'w-auto'
                )}
            >
                {/* The filter is Lemon, so it keeps Lemon's colors inside the quill popover. */}
                <div
                    data-not-quill
                    className="[&_.LemonInput]:rounded-none! [&_.LemonInput]:border-x-0! [&_.LemonInput]:border-t-0! [&_.LemonInput]:bg-transparent! [&_.LemonInput]:shadow-none! [&_.taxonomic-infinite-list]:min-h-0"
                >
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
                        width={anchor ? '100%' : 450}
                        height={anchor ? 240 : undefined}
                        popoverEnabled={!anchor}
                    />
                </div>
            </PopoverContent>
        </Popover>
    )
}
