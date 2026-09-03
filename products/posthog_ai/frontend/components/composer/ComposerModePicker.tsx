import { forwardRef, useEffect, useState, type HTMLAttributes } from 'react'

import { IconEye, IconLock, IconPause, IconPencil, IconShield, IconUnlock } from '@posthog/icons'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@posthog/quill-primitives'

import {
    getModeOption,
    getModesForRuntimeAdapter,
    MODE_OPTIONS,
    type PermissionMode,
} from 'products/posthog_ai/frontend/utils/composerModes'
import {
    CodexTaskRunCreateSchemaInitialPermissionModeEnumApi,
    InitialPermissionModeEnumApi,
    RuntimeAdapterEnumApi,
} from 'products/tasks/frontend/generated/api.schemas'

interface ModeStyle {
    icon: JSX.Element
    className: string
}

// Keyed by how much the agent may do unattended, so the same colour means the same freedom on both
// runtimes: read-only/plan warn, ask-first is neutral, unattended edits pass, never-ask is danger.
const MODE_STYLES: Record<PermissionMode, ModeStyle> = {
    [InitialPermissionModeEnumApi.Default]: { icon: <IconLock />, className: 'text-secondary' },
    [InitialPermissionModeEnumApi.AcceptEdits]: { icon: <IconPencil />, className: 'text-success' },
    [InitialPermissionModeEnumApi.Plan]: { icon: <IconPause />, className: 'text-warning' },
    [CodexTaskRunCreateSchemaInitialPermissionModeEnumApi.ReadOnly]: {
        icon: <IconEye />,
        className: 'text-warning',
    },
    [InitialPermissionModeEnumApi.Auto]: { icon: <IconShield />, className: 'text-success' },
    [InitialPermissionModeEnumApi.BypassPermissions]: { icon: <IconUnlock />, className: 'text-danger' },
    [CodexTaskRunCreateSchemaInitialPermissionModeEnumApi.FullAccess]: {
        icon: <IconUnlock />,
        className: 'text-danger',
    },
}

interface ModeItemRowProps extends HTMLAttributes<HTMLDivElement> {
    highlighted: boolean
    mode: PermissionMode
    onHighlight: (mode: PermissionMode) => void
}

/**
 * Row body for a mode option. Rendered through the item's `render` prop so it can watch Base UI's
 * `highlighted` state — both pointer hover and keyboard navigation — and report it up for the
 * description strip. Must forward the ref: Base UI registers the element into its item list through
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
    /**
     * The modes to offer, in order — normally the runtime's own set via `getModesForRuntimeAdapter`, or a
     * narrower list such as the modes a plan approval offers. Defaults to Claude's, the default harness.
     */
    modes?: PermissionMode[]
}

/**
 * Controlled, logic-free permission-mode picker for a composer footer, styled to match the adjacent
 * model/effort pickers. The caller owns the selection and its side effects. Also reused by the plan-approval
 * card, where `modes` narrows the menu to the wire-offered modes.
 *
 * The highlighted option's description renders in a panel attached to the menu's growing edge, so its
 * height changes never move the option rows.
 */
export function ComposerModePicker({ selectedMode, onModeChange, modes }: ComposerModePickerProps): JSX.Element {
    // Ordered by `modes`, not by MODE_OPTIONS: each runtime lists its modes in its own order.
    const offered = modes ?? getModesForRuntimeAdapter(RuntimeAdapterEnumApi.Claude)
    const options = offered.flatMap((mode) => MODE_OPTIONS.filter((option) => option.value === mode))
    const selectedOption = getModeOption(selectedMode)
    // The mode the description strip shows. Base UI highlights the selected item on open, which
    // seeds this; reset on open so a hover from the previous open can't leak into the next one.
    const [highlightedMode, setHighlightedMode] = useState<PermissionMode | null>(null)
    // Resolve against `options`, not all modes: when `modes` narrows the menu, the strip must never
    // describe a mode that isn't offered (e.g. a selected mode the plan-approval card filtered out).
    const descriptionOption =
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
            <SelectContent
                align="start"
                alignItemWithTrigger={false}
                className="min-w-60 data-[side=top]:rounded-t-none data-[side=bottom]:rounded-b-none"
                popupSibling={
                    descriptionOption && (
                        <>
                            <div className="absolute bottom-full left-0 right-0 hidden min-h-[3.25rem] items-center rounded-t-[var(--radius-md)] border border-b-0 border-[var(--border)] bg-[var(--card)] px-3 py-1.5 text-xs text-secondary [[data-side=top]_&]:flex">
                                {descriptionOption.description}
                            </div>
                            <div className="absolute top-full left-0 right-0 hidden min-h-[3.25rem] items-center rounded-b-[var(--radius-md)] border border-t-0 border-[var(--border)] bg-[var(--card)] px-3 py-1.5 text-xs text-secondary [[data-side=bottom]_&]:flex">
                                {descriptionOption.description}
                            </div>
                        </>
                    )
                }
            >
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
            </SelectContent>
        </Select>
    )
}
