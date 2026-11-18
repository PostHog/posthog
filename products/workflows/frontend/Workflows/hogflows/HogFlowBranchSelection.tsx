import { useValues } from 'kea'
import { createContext, useContext, useEffect, useState } from 'react'
import type { CSSProperties, ReactNode } from 'react'

import { hogFlowEditorLogic } from './hogFlowEditorLogic'

const BRANCH_COLORS = [
    'var(--data-color-1)',
    'var(--data-color-7)',
    'var(--data-color-14)',
    'var(--data-color-12)',
    'var(--data-color-11)',
    'var(--data-color-4)',
]

export interface HogFlowBranchSelection {
    actionId: string
    index: number | null
}

interface HogFlowBranchSelectionContextValue {
    selectedBranch: HogFlowBranchSelection | null
    setSelectedBranch: (branch: HogFlowBranchSelection | null) => void
}

const HogFlowBranchSelectionContext = createContext<HogFlowBranchSelectionContextValue>({
    selectedBranch: null,
    setSelectedBranch: () => undefined,
})

export function getHogFlowBranchColor(index: number | null): string {
    return index === null ? 'var(--muted-foreground)' : BRANCH_COLORS[index % BRANCH_COLORS.length]
}

export function getHogFlowBranchTint(index: number | null): string {
    return `color-mix(in oklab, ${getHogFlowBranchColor(index)} 8%, var(--color-bg-surface-primary))`
}

export function getHogFlowBranchStyle(index: number | null, selected: boolean): CSSProperties {
    const color = getHogFlowBranchColor(index)

    return {
        borderColor: color,
        ...(selected
            ? {
                  backgroundColor: getHogFlowBranchTint(index),
                  boxShadow: `0 0 0 2px color-mix(in oklab, ${color} 35%, transparent)`,
              }
            : {}),
    }
}

export function HogFlowBranchSelectionProvider({ children }: { children: ReactNode }): JSX.Element {
    const { selectedNodeId } = useValues(hogFlowEditorLogic)
    const [selectedBranch, setSelectedBranch] = useState<HogFlowBranchSelection | null>(null)

    useEffect(() => {
        if (selectedBranch && selectedBranch.actionId !== selectedNodeId) {
            setSelectedBranch(null)
        }
    }, [selectedBranch, selectedNodeId])

    return (
        <HogFlowBranchSelectionContext.Provider value={{ selectedBranch, setSelectedBranch }}>
            {children}
        </HogFlowBranchSelectionContext.Provider>
    )
}

export function useHogFlowBranchSelection(): HogFlowBranchSelectionContextValue {
    return useContext(HogFlowBranchSelectionContext)
}
