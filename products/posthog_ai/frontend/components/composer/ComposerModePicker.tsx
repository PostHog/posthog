import { IconPause, IconShield, IconUnlock } from '@posthog/icons'
import {
    ItemContent,
    ItemDescription,
    ItemTitle,
    Select,
    SelectContent,
    SelectGroup,
    SelectGroupLabel,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from '@posthog/quill-primitives'

import { getModeOption, MODE_OPTIONS, type PermissionMode } from 'products/posthog_ai/frontend/utils/composerModes'
import { InitialPermissionModeEnumApi } from 'products/tasks/frontend/generated/api.schemas'

interface ModeStyle {
    icon: JSX.Element
    className: string
}

// Auto keeps the former bypass-permissions treatment so its risk is visible even though it is the default.
const MODE_STYLES: Record<PermissionMode, ModeStyle> = {
    [InitialPermissionModeEnumApi.BypassPermissions]: { icon: <IconUnlock />, className: 'text-danger' },
    [InitialPermissionModeEnumApi.AcceptEdits]: { icon: <IconShield />, className: 'text-success' },
    [InitialPermissionModeEnumApi.Plan]: { icon: <IconPause />, className: 'text-warning' },
}

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
 */
export function ComposerModePicker({ selectedMode, onModeChange, modes }: ComposerModePickerProps): JSX.Element {
    const options = modes ? MODE_OPTIONS.filter((option) => modes.includes(option.value)) : MODE_OPTIONS
    const selectedOption = getModeOption(selectedMode)

    return (
        <Select value={selectedMode} onValueChange={(mode: PermissionMode | null) => mode && onModeChange(mode)}>
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
            <SelectContent align="start" alignItemWithTrigger={false} className="max-w-96">
                <SelectGroup>
                    <SelectGroupLabel>Mode</SelectGroupLabel>
                    {options.map((option) => (
                        <SelectItem key={option.value} value={option.value}>
                            <span className={MODE_STYLES[option.value].className}>
                                {MODE_STYLES[option.value].icon}
                            </span>
                            <ItemContent variant="menuItem">
                                <ItemTitle>{option.label}</ItemTitle>
                                <ItemDescription>{option.description}</ItemDescription>
                            </ItemContent>
                        </SelectItem>
                    ))}
                </SelectGroup>
            </SelectContent>
        </Select>
    )
}
