import { IconCheck, IconShieldLock, IconX } from '@posthog/icons'
import { LemonSegmentedButton } from '@posthog/lemon-ui'

import type { ToolApprovalState } from '../mcpStoreLogic'

interface Props {
    value: ToolApprovalState
    onChange: (value: ToolApprovalState) => void
    size?: 'small' | 'xsmall' | 'medium'
    disabledReason?: string | null
    fullWidth?: boolean
}

// Labels map design language ("approved / ask / blocked") to the backend enum
// (`approved` / `needs_approval` / `do_not_use`). Display-only — no schema change.
const OPTIONS: { value: ToolApprovalState; label: string; icon: JSX.Element }[] = [
    { value: 'approved', label: 'Approved', icon: <IconCheck /> },
    { value: 'needs_approval', label: 'Requires approval', icon: <IconShieldLock /> },
    { value: 'do_not_use', label: 'Blocked', icon: <IconX /> },
]

export function ToolPolicyToggle({ value, onChange, size = 'xsmall', disabledReason, fullWidth }: Props): JSX.Element {
    return (
        <LemonSegmentedButton
            size={size}
            value={value}
            options={OPTIONS}
            onChange={onChange}
            disabledReason={disabledReason ?? undefined}
            fullWidth={fullWidth}
        />
    )
}
