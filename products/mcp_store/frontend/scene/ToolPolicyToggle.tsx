import { IconCheck, IconShieldLock, IconX } from '@posthog/icons'
import { LemonSegmentedButton } from '@posthog/lemon-ui'
import { ToggleGroup, ToggleGroupItem } from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import type { ToolApprovalState } from '../mcpStoreLogic'

interface Props {
    value: ToolApprovalState
    onChange: (value: ToolApprovalState) => void
    size?: 'small' | 'xsmall' | 'medium'
    disabledReason?: string | null
    disabledStates?: Partial<Record<ToolApprovalState, string>>
    fullWidth?: boolean
}

// Labels map product language to the backend enum
// (`approved` / `needs_approval` / `do_not_use`). Display-only — no schema change.
const OPTIONS: { value: ToolApprovalState; label: string; icon: JSX.Element }[] = [
    { value: 'approved', label: 'Always Allow', icon: <IconCheck /> },
    { value: 'needs_approval', label: 'Needs Approval', icon: <IconShieldLock /> },
    { value: 'do_not_use', label: 'Blocked', icon: <IconX /> },
]

export function ToolPolicyToggle({
    value,
    onChange,
    size = 'xsmall',
    disabledReason,
    disabledStates,
    fullWidth,
}: Props): JSX.Element {
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    if (todayRailNav) {
        return (
            <ToggleGroup
                size="sm"
                value={[value]}
                onValueChange={(next: string[]) => {
                    const picked = OPTIONS.find((option) => option.value === next[0])
                    if (picked) {
                        onChange(picked.value)
                    }
                }}
                className={fullWidth ? 'w-full' : undefined}
            >
                {OPTIONS.map((option) => (
                    <ToggleGroupItem
                        key={option.value}
                        value={option.value}
                        disabledReason={disabledReason ?? disabledStates?.[option.value]}
                        className={fullWidth ? 'flex-1' : undefined}
                    >
                        {option.icon}
                        {option.label}
                    </ToggleGroupItem>
                ))}
            </ToggleGroup>
        )
    }

    return (
        <LemonSegmentedButton
            size={size}
            value={value}
            options={OPTIONS.map((option) => ({
                ...option,
                disabledReason: disabledStates?.[option.value],
            }))}
            onChange={onChange}
            disabledReason={disabledReason ?? undefined}
            fullWidth={fullWidth}
        />
    )
}
