import type { ReactNode } from 'react'

import { IconX } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'

import { getHogFlowBranchColor, getHogFlowBranchStyle, useHogFlowBranchSelection } from '../HogFlowBranchSelection'
import { HogFlowBranchNameInput } from './HogFlowBranchNameInput'

export function HogFlowBranchCard({
    actionId,
    index,
    name,
    onNameChange,
    placeholder,
    ariaLabel,
    onRemove,
    removeDisabledReason,
    headerAddon,
    children,
}: {
    actionId: string
    index: number
    name: string
    onNameChange: (value: string) => void
    placeholder: string
    ariaLabel: string
    onRemove: () => void
    removeDisabledReason?: string
    headerAddon?: ReactNode
    children: ReactNode
}): JSX.Element {
    const { selectedBranch, setSelectedBranch } = useHogFlowBranchSelection()
    const branchColor = getHogFlowBranchColor(index)
    const isSelected = selectedBranch?.actionId === actionId && selectedBranch.index === index

    return (
        <div
            className="flex flex-col gap-3 rounded border p-3 transition-colors motion-reduce:transition-none"
            style={getHogFlowBranchStyle(index, isSelected)}
            onFocusCapture={() => setSelectedBranch({ actionId, index })}
            onPointerDownCapture={() => setSelectedBranch({ actionId, index })}
        >
            <div className="flex items-center justify-between gap-2">
                <div className="flex min-w-0 flex-1 items-center gap-2">
                    <HogFlowBranchNameInput
                        branchColor={branchColor}
                        value={name}
                        onChange={onNameChange}
                        placeholder={placeholder}
                        ariaLabel={ariaLabel}
                    />
                    {headerAddon}
                </div>
                <LemonButton size="xsmall" icon={<IconX />} onClick={onRemove} disabledReason={removeDisabledReason} />
            </div>
            {children}
        </div>
    )
}
