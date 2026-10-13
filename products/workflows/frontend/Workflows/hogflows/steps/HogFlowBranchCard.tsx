import type { ReactNode } from 'react'

import { IconX } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { cn } from 'lib/utils/css-classes'

import { useHogFlowBranchSelection } from '../HogFlowBranchSelection'
import { HogFlowBranchTag } from '../HogFlowBranchTag'
import { HogFlowBranchNameInput } from './HogFlowBranchNameInput'

export function HogFlowBranchCard({
    actionId,
    index,
    tagLabel,
    emphasizedTag = false,
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
    tagLabel: string
    emphasizedTag?: boolean
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
    const isSelected = selectedBranch?.actionId === actionId && selectedBranch.index === index

    return (
        <div
            className={cn(
                'flex flex-col gap-3 rounded border bg-surface-primary p-3 transition-colors motion-reduce:transition-none',
                isSelected && 'border-border-bold'
            )}
            onFocusCapture={() => setSelectedBranch({ actionId, index })}
            onPointerDownCapture={() => setSelectedBranch({ actionId, index })}
        >
            <div className="flex items-center justify-between gap-2">
                <div className="flex min-w-0 flex-1 items-center gap-2">
                    <HogFlowBranchTag index={index} label={tagLabel} emphasized={emphasizedTag} />
                    <HogFlowBranchNameInput
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
