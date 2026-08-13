import { forwardRef, useEffect, useState, type HTMLAttributes } from 'react'

import { IconPause, IconShield, IconUnlock } from '@posthog/icons'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@posthog/quill-primitives'

import { getModeOption, MODE_OPTIONS, type PermissionMode } from 'products/posthog_ai/frontend/utils/composerModes'
import { InitialPermissionModeEnumApi } from 'products/tasks/frontend/generated/api.schemas'

interface ModeStyle {
    icon: JSX.Element
    className: string
}

const MODE_STYLES: Record<PermissionMode, ModeStyle> = {
    [InitialPermissionModeEnumApi.Auto]: { icon: <IconShield />, className: 'text-success' },
    [InitialPermissionModeEnumApi.BypassPermissions]: { icon: <IconUnlock />, className: 'text-danger' },
    [InitialPermissionModeEnumApi.Plan]: { icon: <IconPause />, className: 'text-warning' },
}

interface ModeItemRowProps extends HTMLAttributes<HTMLDivElement> {
    highlighted: boolean
    mode: PermissionMode
    onHighlight: (mode: PermissionMode) => void
}

/**
 * Row body for a mode option. Rendered through the item's `render` prop so it can watch Base UI's
 * `highlighted` state — both pointer hover and keyboard navigation — and report it up for the
 * description footer. Must forward the ref: Base UI registers the element into its item list through
 * it, and an unregistered item is invisible to hover highlighting.
 */
const ModeItemRow = forwardRef<HTMLDivElement, ModeItemRowProps>(function ModeItemRow(
    { highlighted, mode, onHighlight, ...divProps },
    ref
): JSX.Element {
    useEffect(() => {
        if (highlighted) {
            onHighlight(mode)
        }
    }, [highlighted, mode, onHighlight])
    return <div ref={ref} {...divProps} />
})

export interface ComposerModePickerProps {
    selectedMode: PermissionMode
    onModeChange: (mode: PermissionMode) => void
    /** Restrict the picker to a subset of modes, such as the modes a plan approval offers. */
    modes?: PermissionMode[]
}

/**
 * Controlled, logic-free permission-mode picker for a composer footer, styled to match the adjacent
 * model/effort pickers. The caller owns the selection and its side effects. Also reused by the plan-approval
 * card, where `modes` narrows the menu to the wire-offered modes.
 *
 * The menu keeps each option to one line (icon + label); the highlighted option's description renders in
 * a footer strip pinned to two lines of height, so the menu never jumps while moving between modes.
 */
export function ComposerModePicker({ selectedMode, onModeChange, modes }: ComposerModePickerProps): JSX.Element {
    const options = modes ? MODE_OPTIONS.filter((option) => modes.includes(option.value)) : MODE_OPTIONS
    const selectedOption = getModeOption(selectedMode)
    // The mode whose description the footer shows. Base UI highlights the selected item on open, which
    // seeds this; reset on open so a hover from the previous open can't leak into the next one.
    const [highlightedMode, setHighlightedMode] = useState<PermissionMode | null>(null)
    // Resolve against `options`, not all modes: when `modes` narrows the menu, the footer must never
    // describe a mode that isn't offered (e.g. a selected mode the plan-approval card filtered out).
    const footerOption =
        options.find((option) => option.value === highlightedMode) ??
        options.find((option) => option.value === selectedMode) ??
        options[0]

    return (
        <Select
            value={selectedMode}
            onValueChange={(mode: PermissionMode | null) => mode && onModeChange(mode)}
            onOpenChange={() => setHighlightedMode(null)}
        >
            <SelectTrigger size="sm" aria-label="Mode">
                <SelectValue>
                    {selectedOption ? (
                        <>
                            <span className={MODE_STYLES[selectedOption.value].className}>
                                {MODE_STYLES[selectedOption.value].icon}
                            </span>
                            {selectedOption.label}
                        </>
                    ) : (
                        'Mode'
                    )}
                </SelectValue>
            </SelectTrigger>
            <SelectContent align="start" alignItemWithTrigger={false}>
                {options.map((option) => (
                    <SelectItem
                        key={option.value}
                        value={option.value}
                        render={(props, state) => (
                            <ModeItemRow
                                {...props}
                                highlighted={state.highlighted}
                                mode={option.value}
                                onHighlight={setHighlightedMode}
                            />
                        )}
                    >
                        <span className={MODE_STYLES[option.value].className}>{MODE_STYLES[option.value].icon}</span>
                        {option.label}
                    </SelectItem>
                ))}
                {footerOption && (
                    <div className="-mx-1 -mb-1 mt-1 flex min-h-[3.25rem] w-60 items-center border-t px-3 py-1.5 text-xs text-secondary">
                        {footerOption.description}
                    </div>
                )}
            </SelectContent>
        </Select>
    )
}
