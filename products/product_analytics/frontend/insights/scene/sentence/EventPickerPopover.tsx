import { useCallback, useId, useRef, useState } from 'react'

import type { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { EventPickerCombobox } from './EventPickerCombobox'

export interface EventPickerPopoverProps {
    groupType?: TaxonomicFilterGroupType
    value?: string | number | null
    onPick: (groupType: TaxonomicFilterGroupType, value: string | number | null, name?: string) => void
    trigger: (open: boolean, toggle: () => void) => JSX.Element
    /** Shown under the list. It receives a function that closes the picker. */
    footer?: (close: () => void) => React.ReactNode
    onClose?: () => void
}

export function EventPickerPopover({
    groupType,
    value,
    onPick,
    trigger,
    footer,
    onClose,
}: EventPickerPopoverProps): JSX.Element {
    const [open, setOpen] = useState(false)
    const pickerKey = useId()
    const triggerSlotRef = useRef<HTMLSpanElement>(null)
    // A trigger word that can be removed has a wrapper around its button.
    const getTriggerElement = useCallback(
        (): Element | null => triggerSlotRef.current?.querySelector('button') ?? null,
        []
    )

    return (
        <>
            {/* The slot has no box of its own, so the trigger keeps its place in the sentence and the popup anchors to the trigger. */}
            <span ref={triggerSlotRef} className="contents">
                {trigger(open, () => setOpen(!open))}
            </span>
            {open && (
                <EventPickerCombobox
                    pickerKey={pickerKey}
                    groupType={groupType}
                    value={value}
                    anchor={getTriggerElement}
                    footer={footer?.(() => {
                        setOpen(false)
                        onClose?.()
                    })}
                    onPick={onPick}
                    onClose={(returnFocus) => {
                        setOpen(false)
                        onClose?.()
                        const triggerElement = getTriggerElement()
                        if (returnFocus && triggerElement instanceof HTMLElement) {
                            triggerElement.focus()
                        }
                    }}
                />
            )}
        </>
    )
}
